#!/usr/bin/env python3
"""usage.raclaw.ru — multi-provider usage dashboard (CPA-first)."""

from __future__ import annotations

import base64
import json
import os
import struct
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover
    psycopg2 = None

CPA_BASE = os.environ.get("CPA_BASE", "http://127.0.0.1:8317")
CPA_MGMT_TOKEN = os.environ.get("CPA_MGMT_TOKEN", "openclaw")
CPA_AUTH_DIR = Path(os.environ.get("CPA_AUTH_DIR", "/root/.cli-proxy-api"))
PG_DSN = os.environ.get(
    "USAGE_PG_DSN",
    "host=172.19.0.2 port=5432 dbname=cliproxyapi user=cliproxyapi password=CHANGE_ME_POSTGRES_PASSWORD",
)
USAGE_WINDOW_HOURS = int(os.environ.get("USAGE_WINDOW_HOURS", "24"))
DATA_DIR = Path(os.environ.get("USAGE_DATA_DIR", "/opt/usage-dashboard/data"))
STATIC_DIR = Path(os.environ.get("USAGE_STATIC_DIR", "/opt/usage-dashboard/static"))
SNAPSHOT_PATH = DATA_DIR / "snapshots.jsonl"
STATE_PATH = DATA_DIR / "state.json"
QUOTA_CACHE_PATH = DATA_DIR / "quota_cache.json"
POLL_SECONDS = int(os.environ.get("USAGE_POLL_SECONDS", "60"))
QUOTA_PROBE_SECONDS = int(os.environ.get("USAGE_QUOTA_PROBE_SECONDS", "300"))
OPENCLAW_AGENTS_DIR = Path(os.environ.get("OPENCLAW_AGENTS_DIR", "/root/.openclaw/agents"))
# DeepSeek direct API usage is not in CPA postgres; aggregate OpenClaw trajectory model.completed events.
DEEPSEEK_USAGE_SOURCE = os.environ.get("DEEPSEEK_USAGE_SOURCE", "openclaw-trajectories")

app = FastAPI(title="usage.raclaw.ru", version="0.2.0")
_lock = threading.Lock()
_state: dict[str, Any] = {
    "updated_at": None,
    "providers": {},
    "accounts": [],
    "wallets": {},
    "errors": [],
}
_quota_cache: dict[str, Any] = {"updated_at": None, "accounts": {}}
_quota_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cpa_get(path: str, timeout: float = 10.0) -> Any:
    url = f"{CPA_BASE}{path}"
    req = urlrequest.Request(
        url,
        headers={"Authorization": f"Bearer {CPA_MGMT_TOKEN}", "Accept": "application/json"},
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def load_state() -> None:
    global _state, _quota_cache
    _state = load_json(STATE_PATH, _state)
    _quota_cache = load_json(QUOTA_CACHE_PATH, _quota_cache)


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    save_json(STATE_PATH, state)
    with SNAPSHOT_PATH.open("a") as f:
        f.write(json.dumps({
            "ts": state.get("updated_at"),
            "providers": state.get("providers"),
            "wallets": state.get("wallets") or {},
            "accounts": [
                {
                    "provider": a.get("provider"),
                    "email": a.get("email"),
                    "status": a.get("status"),
                    "success": a.get("success"),
                    "failed": a.get("failed"),
                    "tokens_total": a.get("tokens_total"),
                    "tokens_in": a.get("tokens_in"),
                    "tokens_out": a.get("tokens_out"),
                    "requests": a.get("requests"),
                    "models": a.get("models"),
                    "quota": a.get("quota"),
                }
                for a in state.get("accounts", [])
            ],
        }, ensure_ascii=False) + "\n")


def jwt_claims(token: str) -> dict[str, Any]:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def header_get(headers: dict[str, str], *names: str) -> str | None:
    lower = {str(k).lower(): v for k, v in headers.items()}
    for name in names:
        if name.lower() in lower:
            val = lower[name.lower()]
            if isinstance(val, list):
                return str(val[0]) if val else None
            return str(val)
    return None


def parse_int(val: Any) -> int | None:
    try:
        if val is None or val == "":
            return None
        return int(float(str(val).strip()))
    except Exception:
        return None


def http_request(
    url: str,
    token: str | None = None,
    proxy: str | None = None,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int | None, dict[str, str], bytes, str | None]:
    handlers = []
    if proxy:
        handlers.append(urlrequest.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urlrequest.build_opener(*handlers) if handlers else urlrequest.build_opener()
    hdrs: dict[str, str] = {}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    req = urlrequest.Request(url, data=body, headers=hdrs, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read(), None
    except HTTPError as e:
        raw = b""
        try:
            raw = e.read()
        except Exception:
            pass
        return e.code, dict(e.headers.items() if e.headers else []), raw, raw[:500].decode("utf-8", errors="replace") or str(e)
    except URLError as e:
        return None, {}, b"", str(e)
    except Exception as e:
        return None, {}, b"", str(e)


def http_json(
    url: str,
    token: str,
    proxy: str | None = None,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 20.0,
) -> tuple[int | None, dict[str, str], Any, str | None]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    st, hdrs, raw, err = http_request(url, token=token, proxy=proxy, method=method, body=body, headers=headers, timeout=timeout)
    text = raw.decode("utf-8", errors="replace") if raw else ""
    try:
        data = json.loads(text) if text else None
    except Exception:
        data = text
    return st, hdrs, data, err


def _read_varint(buf: bytes, index: int) -> tuple[int | None, int]:
    value = 0
    shift = 0
    while index < len(buf) and shift < 64:
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, index
        shift += 7
    return None, index


def grpc_web_data_frames(data: bytes) -> list[bytes]:
    frames: list[bytes] = []
    index = 0
    while index + 5 <= len(data):
        flags = data[index]
        length = int.from_bytes(data[index + 1 : index + 5], "big")
        start = index + 5
        end = start + length
        if length < 0 or end > len(data):
            return []
        if flags & 0x80 == 0:
            frames.append(data[start:end])
        index = end
    return frames


def parse_grok_credits_proto(data: bytes, now_ts: float | None = None) -> dict[str, Any]:
    """Parse GetGrokCreditsConfig protobuf/gRPC-web response.

    Based on CodexBar GrokWebBillingFetcher heuristics + live samples:
    - creditUsagePercent is fixed32 field path ending in 1 under current period
    - billingPeriodStart/End are unix seconds at paths [1,4,1] / [1,5,1]
    """
    now_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    frames = grpc_web_data_frames(data)
    payloads = frames if frames else ([data] if data else [])

    fixed32: list[tuple[tuple[int, ...], float]] = []
    varints: list[tuple[tuple[int, ...], int]] = []

    def scan(buf: bytes, depth: int = 0, path: tuple[int, ...] = ()) -> None:
        idx = 0
        while idx < len(buf):
            start = idx
            key, idx2 = _read_varint(buf, idx)
            if key is None or key == 0:
                idx = start + 1
                continue
            idx = idx2
            field = key >> 3
            wire = key & 0x07
            fpath = path + (field,)
            if wire == 0:
                val, idx = _read_varint(buf, idx)
                if val is not None:
                    varints.append((fpath, int(val)))
            elif wire == 1:
                if idx + 8 > len(buf):
                    break
                idx += 8
            elif wire == 2:
                length, idx = _read_varint(buf, idx)
                if length is None or idx + length > len(buf):
                    idx = start + 1
                    continue
                nested = buf[idx : idx + length]
                idx += length
                if depth < 4:
                    scan(nested, depth + 1, fpath)
            elif wire == 5:
                if idx + 4 > len(buf):
                    break
                bits = int.from_bytes(buf[idx : idx + 4], "little")
                idx += 4
                value = struct.unpack("<f", struct.pack("<I", bits))[0]
                fixed32.append((fpath, float(value)))
            else:
                idx = start + 1

    for payload in payloads:
        scan(payload)

    percent_candidates = [
        (path, value)
        for path, value in fixed32
        if path and path[-1] == 1 and 0.0 <= value <= 100.0
    ]
    used_percent = None
    if percent_candidates:
        percent_candidates.sort(key=lambda item: (len(item[0]), item[0]))
        used_percent = round(float(percent_candidates[0][1]), 2)

    timestamps = [(path, value) for path, value in varints if 1_700_000_000 <= value <= 2_100_000_000]
    period_start = next((value for path, value in timestamps if list(path) == [1, 4, 1]), None)
    period_end = next((value for path, value in timestamps if list(path) == [1, 5, 1]), None)
    if period_end is None:
        future = [value for _, value in timestamps if value > now_ts]
        period_end = min(future) if future else None
    if period_start is None:
        past = [value for _, value in timestamps if value <= now_ts]
        period_start = max(past) if past else None

    def iso(ts: int | None) -> str | None:
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    remaining_percent = None if used_percent is None else round(max(0.0, 100.0 - used_percent), 2)
    return {
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "period_start_unix": period_start,
        "period_end_unix": period_end,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "frames": len(frames),
        "raw_len": len(data),
    }


def fetch_grok_credits(token: str, proxy: str | None = None) -> dict[str, Any]:
    """Fetch SuperGrok/Grok Build credit pool from grok.com gRPC-web endpoint."""
    url = "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
    body = bytes([0x00, 0x00, 0x00, 0x00, 0x00])  # empty protobuf in gRPC-web frame
    headers = {
        "Origin": "https://grok.com",
        "Referer": "https://grok.com/?_s=usage",
        "Accept": "*/*",
        "Content-Type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "User-Agent": "usage-dashboard/0.3",
        "x-grok-client-version": "0.2.93",
    }
    # Prefer direct first: Cloudflare sometimes blocks proxy fingerprints, but
    # CPA Dallas proxy also works for these OAuth tokens in practice.
    attempts: list[str | None] = [None]
    if proxy and proxy not in attempts:
        attempts.append(proxy)

    last_error: str | None = None
    for use_proxy in attempts:
        st, hdrs, raw, err = http_request(
            url,
            token=token,
            proxy=use_proxy,
            method="POST",
            body=body,
            headers=headers,
            timeout=20.0,
        )
        if st != 200 or not raw:
            last_error = f"status={st} err={err or ''}".strip()
            continue
        grpc_status = header_get(hdrs, "grpc-status")
        if grpc_status and grpc_status not in ("0", ""):
            last_error = f"grpc-status={grpc_status} {header_get(hdrs, 'grpc-message') or ''}".strip()
            continue
        parsed = parse_grok_credits_proto(raw)
        if parsed.get("used_percent") is None and parsed.get("period_end") is None:
            last_error = "protobuf parse failed"
            continue
        parsed["ok"] = True
        parsed["proxy_used"] = use_proxy or "direct"
        parsed["source"] = "grok.com/GetGrokCreditsConfig"
        return parsed

    return {
        "ok": False,
        "error": last_error or "GetGrokCreditsConfig failed",
        "source": "grok.com/GetGrokCreditsConfig",
    }


def get_deepseek_api_key() -> str | None:
    """Get DeepSeek API key: env DEEPSEEK_API_KEY > openclaw.json apiKey field."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key and len(key) > 10:
        return key
    try:
        oc = json.loads(Path("/root/.openclaw/openclaw.json").read_text())
        ds = oc.get("models", {}).get("providers", {}).get("deepseek", {})
        ak = ds.get("apiKey")
        if isinstance(ak, str) and len(ak) > 10:
            return ak
        if isinstance(ak, dict) and ak.get("source") == "env":
            return os.environ.get(ak.get("id", "DEEPSEEK_API_KEY"), "")
    except Exception:
        pass
    return None


def probe_deepseek_balance() -> dict[str, Any]:
    """Fetch DeepSeek account balance from /user/balance."""
    key = get_deepseek_api_key()
    result: dict[str, Any] = {
        "provider": "deepseek",
        "email": "deepseek-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "deepseek-balance",
        "balance": [],
        "is_available": False,
        "error": None,
    }
    if not key:
        result["error"] = "DEEPSEEK_API_KEY not set"
        return result

    st, hdrs, data, err = http_json(
        "https://api.deepseek.com/user/balance",
        token=key,
        timeout=15.0,
    )
    if st != 200 or not isinstance(data, dict):
        result["error"] = f"balance API: {st} {err or data}".strip()
        return result

    result["ok"] = bool(data.get("is_available", False))
    result["balance"] = data.get("balance_infos", [])
    result["is_available"] = bool(data.get("is_available", False))

    lines = []
    for b in result["balance"]:
        cur = b.get("currency", "?")
        total = b.get("total_balance", "0")
        topped = b.get("topped_up_balance", "0")
        lines.append(f"{cur} {total} (topped_up {topped})")
    result["remaining_summary"] = " \u00b7 ".join(lines) if lines else "no balance info"
    result["reset_summary"] = ""
    return result



def _balance_totals(balance_infos: list[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for b in balance_infos or []:
        cur = str(b.get("currency") or "?").upper()
        try:
            out[cur] = float(b.get("total_balance") or 0)
        except Exception:
            out[cur] = 0.0
    return out


def _extract_deepseek_balance_from_snapshot(obj: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]] | None]:
    """Return (ts, balance_infos) from a snapshots.jsonl row."""
    ts = obj.get("ts")
    wallets = obj.get("wallets") or {}
    ds = wallets.get("deepseek") if isinstance(wallets, dict) else None
    if isinstance(ds, dict) and ds.get("balance") is not None:
        return ts, ds.get("balance")
    for a in obj.get("accounts") or []:
        if not isinstance(a, dict):
            continue
        if a.get("provider") == "deepseek" or a.get("email") == "deepseek-main":
            q = a.get("quota") or {}
            if isinstance(q, dict) and q.get("balance") is not None:
                return ts, q.get("balance")
    return ts, None


def compute_deepseek_spend_24h(
    current_balance: list[dict[str, Any]] | None,
    window_hours: int = USAGE_WINDOW_HOURS,
) -> dict[str, Any]:
    """Estimate 24h spend as baseline_total - current_total from local snapshots.

    Positive spent = balance decreased. Negative = top-up / credit increased.
    Prefer newest snapshot at/before window start; else earliest in-window (partial).
    """
    result: dict[str, Any] = {
        "window_hours": window_hours,
        "partial": True,
        "baseline_at": None,
        "current": _balance_totals(current_balance),
        "baseline": {},
        "spent": {},
        "spent_summary": "недостаточно истории",
        "note": "spend = baseline - current from local snapshots (DeepSeek API has no usage history)",
    }
    if not SNAPSHOT_PATH.exists():
        result["note"] = "no snapshots yet"
        return result

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - window_hours * 3600
    pre_window: tuple[str, list[dict[str, Any]]] | None = None
    first_in_window: tuple[str, list[dict[str, Any]]] | None = None
    latest: tuple[str, list[dict[str, Any]]] | None = None

    try:
        with SNAPSHOT_PATH.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts_raw, bal = _extract_deepseek_balance_from_snapshot(obj)
                if bal is None:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    ts_epoch = ts.timestamp()
                    ts_s = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    continue
                if ts_epoch < cutoff:
                    pre_window = (ts_s, bal)
                    continue
                if first_in_window is None:
                    first_in_window = (ts_s, bal)
                latest = (ts_s, bal)
    except Exception as e:
        result["note"] = f"snapshot read error: {e}"
        return result

    if pre_window is not None:
        baseline_ts, baseline_balance = pre_window
        partial = False
    elif first_in_window is not None:
        baseline_ts, baseline_balance = first_in_window
        partial = True
    else:
        return result

    cur_bal = current_balance if current_balance is not None else (latest[1] if latest else baseline_balance)
    cur = _balance_totals(cur_bal)
    base = _balance_totals(baseline_balance)
    spent: dict[str, float] = {}
    for code in sorted(set(cur) | set(base)):
        spent[code] = round(base.get(code, 0.0) - cur.get(code, 0.0), 4)

    pretty = []
    for code, val in spent.items():
        sym = "¥" if code == "CNY" else ("$" if code == "USD" else f"{code} ")
        if abs(val) < 0.0001:
            pretty.append(f"{code} 0.00")
        elif val > 0:
            pretty.append(f"−{sym}{val:.2f}")
        else:
            pretty.append(f"+{sym}{abs(val):.2f}")

    result.update({
        "partial": partial,
        "baseline_at": baseline_ts,
        "baseline": base,
        "current": cur,
        "spent": spent,
        "spent_summary": (" · ".join(pretty) if pretty else "0") + (" (частичная история)" if partial else ""),
        "note": (
            "24h spend estimated from local snapshots: baseline_balance - current_balance. "
            "DeepSeek API does not expose usage history."
        ),
    })
    return result


def build_deepseek_wallet(ds_quota: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ds_quota:
        return None
    spend = compute_deepseek_spend_24h(ds_quota.get("balance"))
    return {
        "provider": "deepseek",
        "email": "deepseek-main",
        "name": "DeepSeek API",
        "kind": "wallet-balance",
        "status": "active" if ds_quota.get("ok") else "error",
        "ok": bool(ds_quota.get("ok")),
        "is_available": bool(ds_quota.get("is_available")),
        "balance": ds_quota.get("balance") or [],
        "remaining_summary": ds_quota.get("remaining_summary") or "",
        "error": ds_quota.get("error"),
        "probed_at": ds_quota.get("probed_at"),
        "spend_24h": spend,
        "source": "deepseek-balance-api+local-snapshots",
    }



def load_auth_file(path_hint: str | None, email: str | None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if path_hint:
        candidates.append(Path(path_hint))
    if email:
        candidates.append(CPA_AUTH_DIR / f"xai-{email}.json")
        safe = email.replace("@", "-").replace(".", "-")
        candidates.append(CPA_AUTH_DIR / f"xai-{safe}.json")
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                continue
    # last resort scan
    if email:
        for p in CPA_AUTH_DIR.glob("xai-*.json"):
            try:
                d = json.loads(p.read_text())
                if d.get("email") == email:
                    return d
            except Exception:
                continue
    return None


def probe_xai_account(auth_meta: dict[str, Any]) -> dict[str, Any]:
    email = auth_meta.get("email") or auth_meta.get("account") or "unknown"
    auth = load_auth_file(auth_meta.get("path"), email)
    result: dict[str, Any] = {
        "provider": "xai",
        "email": email,
        "probed_at": now_iso(),
        "ok": False,
        "team_blocked": None,
        "blocked_reason": None,
        "tier": None,
        "team_id": None,
        "user_id": None,
        "credits": {},
        "rate": {},
        "cpa": {
            "status": auth_meta.get("status"),
            "unavailable": bool(auth_meta.get("unavailable")),
            "disabled": bool(auth_meta.get("disabled")),
            "status_message": auth_meta.get("status_message") or "",
            "next_retry_after": auth_meta.get("next_retry_after"),
            "failed": auth_meta.get("failed"),
            "success": auth_meta.get("success"),
        },
        "source": "xai-probe",
        "notes": [],
        "error": None,
    }

    # Parse CPA blocked message if present
    msg = result["cpa"]["status_message"]
    if msg:
        try:
            jm = json.loads(msg) if isinstance(msg, str) and msg.strip().startswith("{") else None
        except Exception:
            jm = None
        if isinstance(jm, dict):
            result["blocked_reason"] = jm.get("code") or jm.get("error")
            if "spending-limit" in str(jm.get("code") or "").lower() or "run out of credits" in str(jm.get("error") or "").lower():
                result["team_blocked"] = True
                result["notes"].append("CPA reports spending-limit / credits exhausted")
        elif "spending-limit" in msg.lower() or "run out of credits" in msg.lower():
            result["team_blocked"] = True
            result["blocked_reason"] = msg[:200]
            result["notes"].append("CPA status_message indicates spending limit")

    if result["cpa"].get("next_retry_after"):
        result["notes"].append(f"CPA next_retry_after={result['cpa']['next_retry_after']}")

    if not auth or not auth.get("access_token"):
        result["error"] = "auth file/token missing"
        return result

    token = auth["access_token"]
    proxy = auth.get("proxy_url") or None
    claims = jwt_claims(token)
    result["tier"] = claims.get("tier")
    result["team_id"] = claims.get("team_id")
    result["user_id"] = claims.get("sub") or claims.get("principal_id")

    # Primary signal: SuperGrok/Grok Build credits (same source as Grok CLI TUI).
    credits = fetch_grok_credits(token, proxy=proxy)
    result["credits"] = credits
    if credits.get("ok"):
        result["ok"] = True
        used = credits.get("used_percent")
        rem = credits.get("remaining_percent")
        if used is not None and rem is not None:
            result["remaining_summary"] = f"{rem:g}% left · used {used:g}% (SuperGrok/Build pool)"
        elif rem is not None:
            result["remaining_summary"] = f"{rem:g}% left (SuperGrok/Build pool)"
        else:
            result["remaining_summary"] = "credits ok (percent missing)"
        if credits.get("period_end"):
            result["reset_summary"] = credits["period_end"]
            result["reset_at"] = credits["period_end"]
        else:
            result["reset_summary"] = "unknown credit period end"
        if used is not None and used >= 100:
            result["team_blocked"] = True if result["team_blocked"] is None else result["team_blocked"]
            result["blocked_reason"] = result["blocked_reason"] or "credit pool exhausted (100% used)"
            result["notes"].append("GetGrokCreditsConfig used_percent=100")
        result["notes"].append(
            f"credits from GetGrokCreditsConfig via {credits.get('proxy_used') or 'direct'}"
        )
    else:
        result["notes"].append(f"credits probe failed: {credits.get('error')}")

    # /v1/me for team_blocked / identity
    st, headers, data, err = http_json("https://api.x.ai/v1/me", token, proxy=proxy, timeout=15)
    if st == 200 and isinstance(data, dict):
        result["ok"] = True
        me_blocked = bool(data.get("team_blocked"))
        if result["team_blocked"] is None:
            result["team_blocked"] = me_blocked
        elif me_blocked:
            result["team_blocked"] = True
        result["team_id"] = data.get("team_id") or result["team_id"]
        result["user_id"] = data.get("user_id") or result["user_id"]
        if me_blocked:
            result["blocked_reason"] = result["blocked_reason"] or "team_blocked=true"
            result["notes"].append("xAI /v1/me team_blocked=true")
        else:
            result["notes"].append("xAI /v1/me team_blocked=false")
    else:
        if not result.get("error"):
            result["error"] = f"/v1/me failed: {st} {err or ''}".strip()
        else:
            result["notes"].append(f"/v1/me failed: {st} {err or ''}".strip())

    # Secondary: short-window RPM/TPM rate-limit headers via tiny chat completion.
    # Skip when already blocked to avoid useless spend/noise.
    hdrs = headers or {}
    st2, headers2, data2, err2 = None, {}, None, None
    if not result.get("team_blocked"):
        body = json.dumps({
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode()
        st2, headers2, data2, err2 = http_json(
            "https://api.x.ai/v1/chat/completions",
            token,
            proxy=proxy,
            method="POST",
            body=body,
            timeout=40,
        )
        hdrs = headers2 or headers or {}
    else:
        result["notes"].append("skipped chat probe because team_blocked")

    limit_req = parse_int(header_get(hdrs, "x-ratelimit-limit-requests", "X-Ratelimit-Limit-Requests"))
    rem_req = parse_int(header_get(hdrs, "x-ratelimit-remaining-requests", "X-Ratelimit-Remaining-Requests"))
    limit_tok = parse_int(header_get(hdrs, "x-ratelimit-limit-tokens", "X-Ratelimit-Limit-Tokens"))
    rem_tok = parse_int(header_get(hdrs, "x-ratelimit-remaining-tokens", "X-Ratelimit-Remaining-Tokens"))
    reset_req = header_get(hdrs, "x-ratelimit-reset-requests", "X-Ratelimit-Reset-Requests")
    reset_tok = header_get(hdrs, "x-ratelimit-reset-tokens", "X-Ratelimit-Reset-Tokens")

    result["rate"] = {
        "limit_requests": limit_req,
        "remaining_requests": rem_req,
        "limit_tokens": limit_tok,
        "remaining_tokens": rem_tok,
        "reset_requests": reset_req,
        "reset_tokens": reset_tok,
        "probe_status": st2,
        "probe_error": None if st2 and st2 < 400 else (err2 or f"status {st2}"),
    }
    if rem_req is not None and limit_req:
        result["rate"]["remaining_requests_pct"] = round(100.0 * rem_req / limit_req, 2)
    if rem_tok is not None and limit_tok:
        result["rate"]["remaining_tokens_pct"] = round(100.0 * rem_tok / limit_tok, 2)

    # Fallback summaries only if credits probe did not fill them.
    if not result.get("remaining_summary"):
        if result["team_blocked"]:
            result["remaining_summary"] = "0 (team blocked / spending-limit)"
        elif rem_tok is not None and limit_tok is not None:
            result["remaining_summary"] = f"{rem_tok}/{limit_tok} tokens (rate-limit window)"
        else:
            result["remaining_summary"] = "unknown"
    if not result.get("reset_summary"):
        if result["cpa"].get("next_retry_after"):
            result["reset_summary"] = result["cpa"]["next_retry_after"]
        elif reset_tok or reset_req:
            result["reset_summary"] = reset_tok or reset_req
        else:
            result["reset_summary"] = "unknown"

    # Keep rate-limit detail as secondary note, not primary truth.
    if rem_tok is not None and limit_tok is not None:
        result["notes"].append(f"API rate-limit window: {rem_tok}/{limit_tok} tokens")
    result["notes"].append(
        "Primary remaining/reset = SuperGrok/Build credit pool via GetGrokCreditsConfig; rate headers are short-window only."
    )
    return result


def probe_all_xai(files: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"updated_at": now_iso(), "accounts": {}}
    for f in files:
        if (f.get("provider") or f.get("type")) != "xai":
            continue
        email = f.get("email") or f.get("account")
        if not email:
            continue
        try:
            out["accounts"][email] = probe_xai_account(f)
        except Exception as e:
            out["accounts"][email] = {
                "provider": "xai",
                "email": email,
                "probed_at": now_iso(),
                "ok": False,
                "error": str(e),
                "notes": ["probe exception"],
            }
    save_json(QUOTA_CACHE_PATH, out)
    return out


def fetch_usage_from_pg(window_hours: int = USAGE_WINDOW_HOURS) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    by_source: dict[str, dict[str, Any]] = {}

    if psycopg2 is None:
        return by_source, ["psycopg2 not installed"]

    try:
        conn = psycopg2.connect(PG_DSN, connect_timeout=5)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                      source,
                      model,
                      count(*)::int AS requests,
                      COALESCE(sum("inputTokens"), 0)::bigint AS tokens_in,
                      COALESCE(sum("outputTokens"), 0)::bigint AS tokens_out,
                      COALESCE(sum("totalTokens"), 0)::bigint AS tokens_total,
                      COALESCE(sum("reasoningTokens"), 0)::bigint AS reasoning,
                      COALESCE(sum("cachedTokens"), 0)::bigint AS cached,
                      COALESCE(sum(CASE WHEN failed THEN 1 ELSE 0 END), 0)::int AS fail,
                      max(timestamp) AS last_seen
                    FROM usage_records
                    WHERE timestamp > now() - (%s || ' hours')::interval
                    GROUP BY source, model
                    ORDER BY source, tokens_total DESC
                    """,
                    (str(window_hours),),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:
        return by_source, [f"postgres usage_records: {e}"]

    for row in rows:
        src = row["source"] or "unknown"
        bucket = by_source.setdefault(src, {
            "requests": 0,
            "fail": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_total": 0,
            "reasoning": 0,
            "cached": 0,
            "models": [],
            "model_stats": [],
            "last_seen": None,
        })
        bucket["requests"] += int(row["requests"] or 0)
        bucket["fail"] += int(row["fail"] or 0)
        bucket["tokens_in"] += int(row["tokens_in"] or 0)
        bucket["tokens_out"] += int(row["tokens_out"] or 0)
        bucket["tokens_total"] += int(row["tokens_total"] or 0)
        bucket["reasoning"] += int(row["reasoning"] or 0)
        bucket["cached"] += int(row["cached"] or 0)
        model = row["model"]
        if model and model not in bucket["models"]:
            bucket["models"].append(model)
        bucket["model_stats"].append({
            "model": model,
            "requests": int(row["requests"] or 0),
            "tokens_total": int(row["tokens_total"] or 0),
            "tokens_in": int(row["tokens_in"] or 0),
            "tokens_out": int(row["tokens_out"] or 0),
            "fail": int(row["fail"] or 0),
        })
        last = row["last_seen"]
        if last is not None:
            last_s = last.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if getattr(last, "tzinfo", None) is None else last.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if bucket["last_seen"] is None or last_s > bucket["last_seen"]:
                bucket["last_seen"] = last_s

    return by_source, errors


def collect_cpa(force_quota: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    files: list[dict[str, Any]] = []

    try:
        auth = cpa_get("/v0/management/auth-files")
        files = auth.get("files") or []
    except Exception as e:
        errors.append(f"auth-files: {e}")

    usage_by_source, usage_errors = fetch_usage_from_pg()
    errors.extend(usage_errors)

    # quota probe cache (xAI + DeepSeek)
    with _quota_lock:
        global _quota_cache
        need_probe = force_quota
        if not _quota_cache.get("accounts"):
            need_probe = True
        else:
            updated = _quota_cache.get("updated_at")
            if not updated:
                need_probe = True
            else:
                try:
                    ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - ts).total_seconds() > QUOTA_PROBE_SECONDS:
                        need_probe = True
                except Exception:
                    need_probe = True
        if need_probe:
            # xAI probe
            if files:
                try:
                    _quota_cache = probe_all_xai(files)
                except Exception as e:
                    errors.append(f"xai-quota-probe: {e}")
            # DeepSeek balance probe
            try:
                ds_accounts = dict((_quota_cache or {}).get("accounts") or {})
                ds_result = probe_deepseek_balance()
                if ds_result is not None:
                    ds_accounts["deepseek-main"] = ds_result
                _quota_cache["accounts"] = ds_accounts
                _quota_cache["updated_at"] = now_iso()
                save_json(QUOTA_CACHE_PATH, _quota_cache)
            except Exception as e:
                errors.append(f"deepseek-balance-probe: {e}")
        quota_accounts = dict((_quota_cache or {}).get("accounts") or {})

    accounts: list[dict[str, Any]] = []
    provider_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "accounts": 0, "active": 0, "success": 0, "failed": 0,
        "tokens_total": 0, "tokens_in": 0, "tokens_out": 0, "requests": 0,
        "blocked": 0,
    })

    for f in files:
        email = f.get("email") or f.get("account") or f.get("name") or "unknown"
        provider = f.get("provider") or f.get("type") or "unknown"
        tok = usage_by_source.get(email, {})
        recent = f.get("recent_requests") or []
        recent_success = sum(int(x.get("success") or 0) for x in recent)
        recent_failed = sum(int(x.get("failed") or 0) for x in recent)
        quota = quota_accounts.get(email) if provider == "xai" else None

        account = {
            "provider": provider,
            "email": email,
            "name": f.get("name"),
            "status": f.get("status") or ("disabled" if f.get("disabled") else "unknown"),
            "status_message": f.get("status_message") or "",
            "disabled": bool(f.get("disabled")),
            "unavailable": bool(f.get("unavailable")),
            "next_retry_after": f.get("next_retry_after"),
            "account_type": f.get("account_type") or f.get("type"),
            "success": int(f.get("success") or 0),
            "failed": int(f.get("failed") or 0),
            "recent_success": recent_success,
            "recent_failed": recent_failed,
            "recent_requests": recent[-12:],
            "last_refresh": f.get("last_refresh"),
            "last_seen": tok.get("last_seen"),
            "requests": int(tok.get("requests") or 0),
            "tokens_in": int(tok.get("tokens_in") or 0),
            "tokens_out": int(tok.get("tokens_out") or 0),
            "tokens_total": int(tok.get("tokens_total") or 0),
            "reasoning_tokens": int(tok.get("reasoning") or 0),
            "cached_tokens": int(tok.get("cached") or 0),
            "models": list(tok.get("models") or []),
            "model_stats": list(tok.get("model_stats") or []),
            "window_hours": USAGE_WINDOW_HOURS,
            "quota": quota,
            "source": "cpa+pg+xai-probe" if provider == "xai" else "cpa+pg",
        }
        accounts.append(account)

        ps = provider_stats[provider]
        ps["accounts"] += 1
        if account["status"] == "active" and not account["disabled"] and not account["unavailable"]:
            ps["active"] += 1
        if account.get("unavailable") or (quota and quota.get("team_blocked")):
            ps["blocked"] += 1
        ps["success"] += account["success"]
        ps["failed"] += account["failed"]
        ps["tokens_total"] += account["tokens_total"]
        ps["tokens_in"] += account["tokens_in"]
        ps["tokens_out"] += account["tokens_out"]
        ps["requests"] += account["requests"]

    known_emails = {a["email"] for a in accounts}
    for src, tok in usage_by_source.items():
        if src in known_emails:
            continue
        accounts.append({
            "provider": "unknown",
            "email": src,
            "name": src,
            "status": "orphan-usage",
            "status_message": "seen in usage_records, no auth-file",
            "disabled": False,
            "unavailable": False,
            "next_retry_after": None,
            "account_type": "unknown",
            "success": int(tok.get("requests") or 0) - int(tok.get("fail") or 0),
            "failed": int(tok.get("fail") or 0),
            "recent_success": 0,
            "recent_failed": 0,
            "recent_requests": [],
            "last_refresh": None,
            "last_seen": tok.get("last_seen"),
            "requests": int(tok.get("requests") or 0),
            "tokens_in": int(tok.get("tokens_in") or 0),
            "tokens_out": int(tok.get("tokens_out") or 0),
            "tokens_total": int(tok.get("tokens_total") or 0),
            "reasoning_tokens": int(tok.get("reasoning") or 0),
            "cached_tokens": int(tok.get("cached") or 0),
            "models": list(tok.get("models") or []),
            "model_stats": list(tok.get("model_stats") or []),
            "window_hours": USAGE_WINDOW_HOURS,
            "quota": None,
            "source": "pg-usage-only",
        })

    # DeepSeek is NOT a CPA account: keep wallet-only (balance + estimated 24h spend).
    # No tokens/models in the CPA table — DeepSeek API has no usage history endpoint.
    ds_quota = quota_accounts.get("deepseek-main") if quota_accounts else None
    # If probe cache is stale/missing deepseek, try a lightweight probe when forced path already ran;
    # otherwise use cached value only.
    deepseek_wallet = build_deepseek_wallet(ds_quota)

    # Drop any orphan PG rows that look like deepseek (rare historical CPA key traffic)
    accounts = [
        a for a in accounts
        if not (
            a.get("source") == "pg-usage-only"
            and any("deepseek" in str(m).lower() for m in (a.get("models") or []))
        )
        and a.get("provider") != "deepseek"
    ]

    accounts.sort(key=lambda a: (
        0 if a.get("unavailable") or (a.get("quota") or {}).get("team_blocked") else 1,
        a["provider"],
        -(a["tokens_total"] or 0),
        a["email"] or "",
    ))

    wallets: dict[str, Any] = {}
    if deepseek_wallet:
        wallets["deepseek"] = deepseek_wallet

    return {
        "updated_at": now_iso(),
        "providers": {
            "cpa": {
                "label": "CLIProxyAPI",
                "kind": "proxy",
                "accounts": len(files),
                "stats_by_provider": dict(provider_stats),
                "usage_window_hours": USAGE_WINDOW_HOURS,
                "usage_sources": len(usage_by_source),
                "quota_probe_updated_at": (_quota_cache or {}).get("updated_at"),
            }
        },
        "accounts": accounts,
        "wallets": wallets,
        "errors": errors,
        "notes": [
            "Tokens/models for CPA accounts from cliproxy postgres usage_records (durable), not CPA usage-queue.",
            "DeepSeek is shown separately as wallet balance only; 24h spend estimated from local snapshots (API has no usage history).",
            f"Usage window: last {USAGE_WINDOW_HOURS}h.",
            "xAI SuperGrok/Build remaining% + reset: grok.com GetGrokCreditsConfig (same source as Grok CLI TUI).",
            "Secondary: team_blocked from /v1/me; short-window RPM/TPM from chat rate-limit headers.",
            "CPA next_retry_after is cooldown after quota/spending-limit error, not credit-period reset.",
        ],
    }


def refresh_once(force_quota: bool = False) -> dict[str, Any]:
    state = collect_cpa(force_quota=force_quota)
    with _lock:
        global _state
        _state = state
        save_state(state)
        return state


def poller() -> None:
    while True:
        try:
            refresh_once(force_quota=False)
        except Exception as e:
            with _lock:
                _state["errors"] = list(_state.get("errors") or []) + [f"poller: {e}"]
                _state["updated_at"] = now_iso()
        time.sleep(POLL_SECONDS)


@app.on_event("startup")
def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_state()
    try:
        refresh_once(force_quota=True)
    except Exception as e:
        _state["errors"] = [f"startup: {e}"]
        _state["updated_at"] = now_iso()
    t = threading.Thread(target=poller, name="usage-poller", daemon=True)
    t.start()


@app.get("/api/health")
def health() -> dict[str, Any]:
    with _lock:
        return {
            "ok": True,
            "updated_at": _state.get("updated_at"),
            "accounts": len(_state.get("accounts") or []),
            "errors": _state.get("errors") or [],
            "quota_probe_updated_at": ((_state.get("providers") or {}).get("cpa") or {}).get("quota_probe_updated_at"),
        }


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_state))


@app.get("/api/accounts")
def accounts() -> dict[str, Any]:
    with _lock:
        return {"updated_at": _state.get("updated_at"), "accounts": _state.get("accounts") or []}


@app.get("/api/providers")
def providers() -> dict[str, Any]:
    with _lock:
        return {"updated_at": _state.get("updated_at"), "providers": _state.get("providers") or {}}


@app.get("/api/wallets")
def wallets() -> dict[str, Any]:
    with _lock:
        return {
            "updated_at": _state.get("updated_at"),
            "wallets": _state.get("wallets") or {},
        }


@app.get("/api/quota")
def quota() -> dict[str, Any]:
    with _quota_lock:
        return json.loads(json.dumps(_quota_cache))


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    try:
        return refresh_once(force_quota=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def index() -> FileResponse:
    path = STATIC_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="index.html missing")
    return FileResponse(path)


@app.get("/favicon.ico")
def favicon() -> JSONResponse:
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=int(os.environ.get("USAGE_PORT", "3210")),
        log_level="info",
    )
