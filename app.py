#!/usr/bin/env python3
"""usage.ragpt.ru — multi-provider usage dashboard (wallets)."""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

try:
    import socks
    from sockshandler import SocksiPyHandler
except Exception:  # pragma: no cover
    socks = None
    SocksiPyHandler = None

DATA_DIR = Path(os.environ.get("USAGE_DATA_DIR", "/opt/usage-dashboard/data"))
STATIC_DIR = Path(os.environ.get("USAGE_STATIC_DIR", "/opt/usage-dashboard/static"))
SNAPSHOT_PATH = DATA_DIR / "snapshots.jsonl"
STATE_PATH = DATA_DIR / "state.json"
QUOTA_CACHE_PATH = DATA_DIR / "quota_cache.json"
POLL_SECONDS = int(os.environ.get("USAGE_POLL_SECONDS", "60"))
QUOTA_PROBE_SECONDS = int(os.environ.get("USAGE_QUOTA_PROBE_SECONDS", "300"))
USAGE_WINDOW_HOURS = int(os.environ.get("USAGE_WINDOW_HOURS", "24"))
WALLET_PROBE_KEYS = ("deepseek-main", "openrouter-main", "zai-main", "commandcode-main")

COMMANDCODE_API_BASE = "https://api.commandcode.ai"
COMMANDCODE_CREDITS_PATH = "/alpha/billing/credits"
COMMANDCODE_SUBSCRIPTIONS_PATH = "/alpha/billing/subscriptions"
# Published plan grants/caps (docs 2026-08-25). monthlyCredits on the wire is remaining, not total.
COMMANDCODE_PLANS: dict[str, dict[str, Any]] = {
    "individual-go": {"label": "Go", "monthly_credits": 10.0, "session_cap": 3.0, "weekly_cap": 6.0},
    "individual-goat": {"label": "GOAT", "monthly_credits": 70.0, "session_cap": 14.0, "weekly_cap": 35.0},
    "individual-pro": {"label": "Pro", "monthly_credits": 80.0, "session_cap": 16.0, "weekly_cap": 40.0},
    "individual-max": {"label": "Max 10x", "monthly_credits": 150.0, "session_cap": 45.0, "weekly_cap": 90.0},
    "individual-ultra": {"label": "Max 20x", "monthly_credits": 300.0, "session_cap": 90.0, "weekly_cap": 180.0},
}

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai"

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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_openrouter_base_url() -> str:
    raw = os.environ.get("OPENROUTER_BASE_URL", "").strip().rstrip("/")
    return raw or OPENROUTER_DEFAULT_BASE_URL


def get_openrouter_proxy() -> str | None:
    raw = os.environ.get("OPENROUTER_PROXY", "").strip()
    return raw or None


def get_openrouter_ssl_verify() -> bool:
    return not _env_flag("OPENROUTER_SSL_NO_VERIFY", default=False)


def openrouter_api_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return get_openrouter_base_url() + path


def redact_proxy_url(proxy: str | None) -> str | None:
    """Strip userinfo from a proxy URL for logs / probe debug fields."""
    if not proxy:
        return None
    parts = urlsplit(proxy)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def _proxy_handlers(proxy: str) -> list[Any]:
    parsed = urlsplit(proxy)
    scheme = (parsed.scheme or "http").lower()
    if scheme in ("http", "https"):
        return [urlrequest.ProxyHandler({"http": proxy, "https": proxy})]
    if scheme in ("socks", "socks5", "socks5h", "socks4"):
        if socks is None or SocksiPyHandler is None:
            raise RuntimeError("SOCKS proxy requires PySocks (pip install PySocks)")
        host = parsed.hostname
        if not host:
            raise ValueError("SOCKS proxy URL is missing host")
        port = parsed.port or 1080
        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        rdns = scheme != "socks4"
        proxy_type = socks.SOCKS4 if scheme == "socks4" else socks.SOCKS5
        return [SocksiPyHandler(proxy_type, host, port, rdns, username, password)]
    raise ValueError(f"unsupported proxy scheme: {scheme}")


def _build_opener(proxy: str | None = None, ssl_verify: bool = True):
    handlers: list[Any] = []
    if proxy:
        handlers.extend(_proxy_handlers(proxy))
    if not ssl_verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urlrequest.HTTPSHandler(context=ctx))
    if handlers:
        return urlrequest.build_opener(*handlers)
    return urlrequest.build_opener()


def http_request(
    url: str,
    token: str | None = None,
    proxy: str | None = None,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    ssl_verify: bool = True,
) -> tuple[int | None, dict[str, str], bytes, str | None]:
    opener = _build_opener(proxy=proxy, ssl_verify=ssl_verify)
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


DASHBOARD_USER_AGENT = "usage-dashboard/1.0 (+https://usage.ragpt.ru)"


def http_json(
    url: str,
    token: str,
    proxy: str | None = None,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 20.0,
    ssl_verify: bool = True,
) -> tuple[int | None, dict[str, str], Any, str | None]:
    headers = {"Accept": "application/json", "User-Agent": DASHBOARD_USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    st, hdrs, raw, err = http_request(
        url,
        token=token,
        proxy=proxy,
        method=method,
        body=body,
        headers=headers,
        timeout=timeout,
        ssl_verify=ssl_verify,
    )
    text = raw.decode("utf-8", errors="replace") if raw else ""
    try:
        data = json.loads(text) if text else None
    except Exception:
        data = text
    return st, hdrs, data, err

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




def get_openrouter_api_key() -> str | None:
    """Env OPENROUTER_API_KEY > openclaw.json models.providers.openrouter > credentials/openrouter.env."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key and len(key) > 10:
        return key
    try:
        oc = json.loads(Path("/root/.openclaw/openclaw.json").read_text())
        orp = oc.get("models", {}).get("providers", {}).get("openrouter", {})
        ak = orp.get("apiKey")
        if isinstance(ak, str) and len(ak) > 10:
            return ak
        if isinstance(ak, dict) and ak.get("source") == "env":
            key = os.environ.get(ak.get("id", "OPENROUTER_API_KEY"), "")
            if key and len(key) > 10:
                return key
    except Exception:
        pass
    for p in (
        Path("/root/.openclaw/credentials/openrouter.env"),
        Path("/root/.openclaw/gateway.systemd.env"),
    ):
        try:
            for line in p.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and len(val) > 10:
                        return val
        except Exception:
            pass
    return None


def get_openrouter_management_key() -> str | None:
    key = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
    if key and len(key) > 10:
        return key
    try:
        p = Path("/root/.openclaw/credentials/openrouter-management.env")
        for line in p.read_text().splitlines():
            if line.startswith("OPENROUTER_MANAGEMENT_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and len(val) > 10:
                    return val
    except Exception:
        pass
    return None


def probe_openrouter_wallet() -> dict[str, Any]:
    """Fetch OpenRouter account credits + key usage.

    - GET /api/v1/credits → total_credits / total_usage (account-level)
    - GET /api/v1/key → per-key usage_daily/weekly/monthly
    Remaining ≈ total_credits - total_usage
    """
    key = get_openrouter_api_key()
    result: dict[str, Any] = {
        "provider": "openrouter",
        "email": "openrouter-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "openrouter-credits",
        "total_credits": None,
        "total_usage": None,
        "remaining": None,
        "key": None,
        "keys": [],
        "error": None,
    }
    if not key:
        result["error"] = "OPENROUTER_API_KEY not set"
        return result

    proxy = get_openrouter_proxy()
    ssl_verify = get_openrouter_ssl_verify()
    result["via"] = {
        "base_url": get_openrouter_base_url(),
        "proxy": redact_proxy_url(proxy),
        "ssl_verify": ssl_verify,
    }

    st, _hdrs, data, err = http_json(
        openrouter_api_url("/api/v1/credits"),
        token=key,
        proxy=proxy,
        timeout=15.0,
        ssl_verify=ssl_verify,
    )
    if st != 200 or not isinstance(data, dict):
        result["error"] = f"credits API: {st} {err or data}".strip()
        return result

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    try:
        total_credits = float(payload.get("total_credits") or 0)
        total_usage = float(payload.get("total_usage") or 0)
    except Exception:
        result["error"] = f"credits parse failed: {payload}"
        return result

    remaining = round(total_credits - total_usage, 6)
    result["ok"] = True
    result["total_credits"] = total_credits
    result["total_usage"] = total_usage
    result["remaining"] = remaining
    result["remaining_summary"] = f"${remaining:.2f} left · used ${total_usage:.2f} / ${total_credits:.2f}"

    # primary key stats
    st2, _h2, data2, err2 = http_json(
        openrouter_api_url("/api/v1/key"),
        token=key,
        proxy=proxy,
        timeout=15.0,
        ssl_verify=ssl_verify,
    )
    if st2 == 200 and isinstance(data2, dict):
        kpayload = data2.get("data") if isinstance(data2.get("data"), dict) else data2
        result["key"] = {
            "label": kpayload.get("label"),
            "usage": kpayload.get("usage"),
            "usage_daily": kpayload.get("usage_daily"),
            "usage_weekly": kpayload.get("usage_weekly"),
            "usage_monthly": kpayload.get("usage_monthly"),
            "limit": kpayload.get("limit"),
            "limit_remaining": kpayload.get("limit_remaining"),
            "is_free_tier": kpayload.get("is_free_tier"),
        }
    elif err2:
        result["key_error"] = f"key API: {st2} {err2}"

    # optional: list keys via management key
    mkey = get_openrouter_management_key()
    if mkey:
        st3, _h3, data3, err3 = http_json(
            openrouter_api_url("/api/v1/keys"),
            token=mkey,
            proxy=proxy,
            timeout=20.0,
            ssl_verify=ssl_verify,
        )
        if st3 == 200 and isinstance(data3, dict):
            items = data3.get("data") or []
            keys_out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("disabled"):
                    continue
                keys_out.append({
                    "name": it.get("name"),
                    "label": it.get("label"),
                    "usage": it.get("usage"),
                    "usage_daily": it.get("usage_daily"),
                    "usage_weekly": it.get("usage_weekly"),
                    "usage_monthly": it.get("usage_monthly"),
                    "limit_remaining": it.get("limit_remaining"),
                })
            # sort by daily usage desc
            keys_out.sort(key=lambda x: float(x.get("usage_daily") or 0), reverse=True)
            result["keys"] = keys_out[:12]
        elif err3:
            result["keys_error"] = f"keys API: {st3} {err3}"

    return result


def compute_openrouter_spend_24h(
    current_total_usage: float | None,
    window_hours: int = USAGE_WINDOW_HOURS,
) -> dict[str, Any]:
    """Estimate rolling 24h spend from snapshots of account total_usage.

    spent = current_total_usage - baseline_total_usage (usage only goes up).
    """
    result: dict[str, Any] = {
        "window_hours": window_hours,
        "partial": True,
        "baseline_at": None,
        "baseline_total_usage": None,
        "current_total_usage": current_total_usage,
        "spent": None,
        "spent_summary": "недостаточно истории",
        "note": "rolling 24h spend from local snapshots of OpenRouter total_usage",
    }
    if current_total_usage is None:
        result["note"] = "no current total_usage"
        return result
    if not SNAPSHOT_PATH.exists():
        result["note"] = "no snapshots yet"
        return result

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - window_hours * 3600
    pre_window: tuple[str, float] | None = None
    first_in_window: tuple[str, float] | None = None

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
                ts_raw = obj.get("ts")
                usage_val = None
                wallets = obj.get("wallets") or {}
                orw = wallets.get("openrouter") if isinstance(wallets, dict) else None
                if isinstance(orw, dict) and orw.get("total_usage") is not None:
                    try:
                        usage_val = float(orw.get("total_usage"))
                    except Exception:
                        usage_val = None
                if usage_val is None:
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
                    pre_window = (ts_s, usage_val)
                    continue
                if first_in_window is None:
                    first_in_window = (ts_s, usage_val)
    except Exception as e:
        result["note"] = f"snapshot read error: {e}"
        return result

    if pre_window is not None:
        baseline_at, baseline_usage = pre_window
        partial = False
    elif first_in_window is not None:
        baseline_at, baseline_usage = first_in_window
        partial = True
    else:
        return result

    spent = round(float(current_total_usage) - float(baseline_usage), 6)
    if spent < 0:
        # top-up / refund / reset edge-case
        spent_summary = f"+${abs(spent):.2f} (usage dropped)"
    else:
        spent_summary = f"−${spent:.2f}"
    if partial:
        spent_summary += " (частичная история)"

    result.update({
        "partial": partial,
        "baseline_at": baseline_at,
        "baseline_total_usage": baseline_usage,
        "current_total_usage": float(current_total_usage),
        "spent": spent,
        "spent_summary": spent_summary,
    })
    return result


def build_openrouter_wallet(or_probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not or_probe:
        return None
    spend = compute_openrouter_spend_24h(or_probe.get("total_usage"))
    key = or_probe.get("key") or {}
    keys = or_probe.get("keys") or []
    daily = key.get("usage_daily")
    try:
        daily_f = float(daily) if daily is not None else None
    except Exception:
        daily_f = None

    # Sum usage_daily across management keys when available (= account-ish today UTC)
    keys_daily = None
    if keys:
        try:
            keys_daily = round(sum(float(k.get("usage_daily") or 0) for k in keys), 6)
        except Exception:
            keys_daily = None

    spent_summary = spend.get("spent_summary")
    # Prefer rolling snapshot 24h when not partial; else API daily figures
    if spend.get("spent") is not None and not spend.get("partial"):
        spent_summary = spend.get("spent_summary")
    elif keys_daily is not None:
        spent_summary = f"−${keys_daily:.2f} today (UTC, all keys)"
        if spend.get("spent") is not None and spend.get("partial"):
            spent_summary += f" · snap {spend.get('spent_summary')}"
    elif daily_f is not None:
        if spend.get("spent") is None:
            spent_summary = f"−${daily_f:.2f} today (UTC, key)"
        else:
            spent_summary = f"{spend.get('spent_summary')} · key today −${daily_f:.2f}"

    remaining = or_probe.get("remaining")
    return {
        "provider": "openrouter",
        "email": "openrouter-main",
        "name": "OpenRouter",
        "kind": "wallet-credits",
        "status": "active" if or_probe.get("ok") else "error",
        "ok": bool(or_probe.get("ok")),
        "total_credits": or_probe.get("total_credits"),
        "total_usage": or_probe.get("total_usage"),
        "remaining": remaining,
        "remaining_summary": or_probe.get("remaining_summary") or "",
        "key": key,
        "keys": keys,
        "usage_daily": daily_f,
        "usage_daily_all_keys": keys_daily,
        "usage_weekly": key.get("usage_weekly"),
        "usage_monthly": key.get("usage_monthly"),
        "error": or_probe.get("error"),
        "probed_at": or_probe.get("probed_at"),
        "spend_24h": spend,
        "spent_summary": spent_summary,
        "source": "openrouter-credits-api+local-snapshots",
        "via": or_probe.get("via"),
    }




def get_zai_proxy() -> str | None:
    """HTTP CONNECT or SOCKS5/SOCKS5h for api.z.ai (docker-egress on tw-msk)."""
    raw = os.environ.get("ZAI_PROXY", "").strip()
    return raw or None


def get_zai_api_key() -> str | None:
    """Env ZAI_API_KEY > openclaw.json > gateway.systemd.env."""
    key = os.environ.get("ZAI_API_KEY")
    if key and len(key) > 10:
        return key
    try:
        oc = json.loads(Path("/root/.openclaw/openclaw.json").read_text())
        zp = oc.get("models", {}).get("providers", {}).get("zai", {})
        ak = zp.get("apiKey")
        if isinstance(ak, str) and len(ak) > 10:
            return ak
        if isinstance(ak, dict) and ak.get("source") == "env":
            key = os.environ.get(ak.get("id", "ZAI_API_KEY"), "")
            if key and len(key) > 10:
                return key
    except Exception:
        pass
    for p in (
        Path("/root/.openclaw/gateway.systemd.env"),
        Path("/root/.openclaw/credentials/zai.env"),
    ):
        try:
            for line in p.read_text().splitlines():
                if line.startswith("ZAI_API_KEY=") or line.startswith("GLM_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and len(val) > 10:
                        return val
        except Exception:
            pass
    return None


def _ms_to_iso(ms: Any) -> str | None:
    try:
        v = int(ms)
        # accept seconds accidentally
        if v < 10_000_000_000:
            v *= 1000
        return datetime.fromtimestamp(v / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _classify_zai_limit(item: dict[str, Any]) -> str:
    """Map Z.AI limit entry to session|weekly|mcp|other.

    OpenUsage convention:
    - TOKENS_LIMIT sub-daily (hours) → session (short 5h)
    - TOKENS_LIMIT multi-day → weekly (long)
    - TIME_LIMIT → monthly MCP/tools
    """
    typ = str(item.get("type") or "").upper()
    unit = item.get("unit")
    number = item.get("number")
    try:
        unit_i = int(unit) if unit is not None else None
    except Exception:
        unit_i = None
    try:
        num_i = int(number) if number is not None else None
    except Exception:
        num_i = None

    if typ == "TIME_LIMIT":
        return "mcp"
    if typ == "TOKENS_LIMIT":
        # empirical from live API + openusage:
        # unit=3 number=5 → 5 hours session
        # unit=6 number=1 → 1 week
        if unit_i == 3 or (num_i is not None and num_i <= 24 and unit_i is not None and unit_i <= 4):
            return "session"
        if unit_i == 6 or (num_i is not None and num_i >= 1 and unit_i is not None and unit_i >= 5):
            return "weekly"
        # fallback by nextReset horizon
        reset = item.get("nextResetTime")
        try:
            reset_s = int(reset) / 1000.0
            horizon_h = (reset_s - datetime.now(timezone.utc).timestamp()) / 3600.0
            if horizon_h <= 12:
                return "session"
            if horizon_h <= 24 * 10:
                return "weekly"
        except Exception:
            pass
        return "tokens"
    return "other"


def probe_zai_quota() -> dict[str, Any]:
    """Fetch Z.AI GLM Coding Plan quotas (short session + weekly + MCP).

    Primary: GET https://api.z.ai/api/monitor/usage/quota/limit
    Optional: GET https://api.z.ai/api/biz/subscription/list
    """
    key = get_zai_api_key()
    result: dict[str, Any] = {
        "provider": "zai",
        "email": "zai-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "zai-coding-quota",
        "level": None,
        "limits": [],
        "session": None,
        "weekly": None,
        "mcp": None,
        "error": None,
    }
    if not key:
        result["error"] = "ZAI_API_KEY not set"
        return result

    proxy = get_zai_proxy()
    result["via"] = {"proxy": redact_proxy_url(proxy)}

    st, _hdrs, data, err = http_json(
        "https://api.z.ai/api/monitor/usage/quota/limit",
        token=key,
        proxy=proxy,
        timeout=15.0,
    )
    if st != 200 or not isinstance(data, dict):
        result["error"] = f"quota/limit API: {st} {err or data}".strip()
        return result

    # envelope: {code, success, data:{limits, level}}
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if data.get("success") is False or (data.get("code") not in (None, 200, "200") and data.get("code") != 200):
        # still try parse if data present
        if not isinstance(payload, dict):
            result["error"] = f"quota/limit failed: {data}"
            return result

    limits = payload.get("limits") or []
    result["level"] = payload.get("level")
    result["ok"] = True
    parsed = []
    for item in limits:
        if not isinstance(item, dict):
            continue
        kind = _classify_zai_limit(item)
        used_pct = item.get("percentage")
        try:
            used_pct_f = float(used_pct) if used_pct is not None else None
        except Exception:
            used_pct_f = None
        rem_pct = None if used_pct_f is None else round(max(0.0, 100.0 - used_pct_f), 2)
        entry = {
            "kind": kind,
            "type": item.get("type"),
            "unit": item.get("unit"),
            "number": item.get("number"),
            "usage": item.get("usage"),
            "currentValue": item.get("currentValue"),
            "remaining": item.get("remaining"),
            "used_percent": used_pct_f,
            "remaining_percent": rem_pct,
            "next_reset_at": _ms_to_iso(item.get("nextResetTime")),
            "next_reset_ms": item.get("nextResetTime"),
            "usageDetails": item.get("usageDetails") or [],
        }
        # human summary
        if kind in ("session", "weekly", "tokens") and rem_pct is not None:
            label = {"session": "5h", "weekly": "week", "tokens": "tokens"}.get(kind, kind)
            entry["summary"] = f"{rem_pct:.0f}% left ({label})"
            if used_pct_f is not None:
                entry["summary"] += f" · used {used_pct_f:.0f}%"
        elif kind == "mcp":
            cur = item.get("currentValue")
            usage_lim = item.get("usage")
            rem = item.get("remaining")
            entry["summary"] = f"MCP {cur}/{usage_lim}" + (f" · rem {rem}" if rem is not None else "")
        else:
            entry["summary"] = str(item.get("type") or kind)
        parsed.append(entry)
        if kind == "session" and result["session"] is None:
            result["session"] = entry
        elif kind == "weekly" and result["weekly"] is None:
            result["weekly"] = entry
        elif kind == "mcp" and result["mcp"] is None:
            result["mcp"] = entry

    result["limits"] = parsed

    # remaining_summary for cards
    parts = []
    if result.get("session"):
        parts.append("5h " + str(result["session"].get("remaining_percent")) + "%")
    if result.get("weekly"):
        parts.append("week " + str(result["weekly"].get("remaining_percent")) + "%")
    if result.get("mcp"):
        parts.append(result["mcp"].get("summary") or "MCP")
    level = result.get("level") or "?"
    result["remaining_summary"] = f"plan {level} · " + " · ".join(parts) if parts else f"plan {level}"

    # best-effort subscription name
    try:
        st2, _h2, data2, _e2 = http_json(
            "https://api.z.ai/api/biz/subscription/list",
            token=key,
            proxy=proxy,
            timeout=5.0,
        )
        if st2 == 200 and isinstance(data2, dict):
            result["subscription"] = data2.get("data") or data2
    except Exception:
        pass

    return result


def build_zai_wallet(probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not probe:
        return None
    session = probe.get("session") or {}
    weekly = probe.get("weekly") or {}
    mcp = probe.get("mcp") or {}
    return {
        "provider": "zai",
        "email": "zai-main",
        "name": "Z.AI GLM Coding",
        "kind": "coding-quota",
        "status": "active" if probe.get("ok") else "error",
        "ok": bool(probe.get("ok")),
        "level": probe.get("level"),
        "session": session,
        "weekly": weekly,
        "mcp": mcp,
        "limits": probe.get("limits") or [],
        "remaining_summary": probe.get("remaining_summary") or "",
        "subscription": probe.get("subscription"),
        "error": probe.get("error"),
        "probed_at": probe.get("probed_at"),
        "source": "zai-monitor-quota-limit",
        "via": probe.get("via"),
    }


def get_commandcode_proxy() -> str | None:
    """HTTP CONNECT or SOCKS5/SOCKS5h for api.commandcode.ai (optional tw-msk egress)."""
    raw = os.environ.get("COMMANDCODE_PROXY", "").strip()
    return raw or None


def get_commandcode_api_key() -> str | None:
    """Env COMMANDCODE_API_KEY or COMMAND_CODE_API_KEY (pi-sub alias)."""
    for name in ("COMMANDCODE_API_KEY", "COMMAND_CODE_API_KEY"):
        key = os.environ.get(name)
        if key and len(key.strip()) > 10:
            return key.strip()
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(data: dict[str, Any] | None, *names: str) -> Any:
    if not isinstance(data, dict):
        return None
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _commandcode_reset_iso(value: Any) -> str | None:
    ms = _as_float(value)
    if ms is None or ms <= 0:
        return None
    if ms < 10_000_000_000:
        ms *= 1000
    return _ms_to_iso(ms)


def _parse_commandcode_window(raw: Any, kind: str, label: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used = _as_float(_pick(raw, "used", "usage"))
    cap = _as_float(_pick(raw, "cap", "limit", "allowance"))
    if used is None or cap is None or cap <= 0:
        return None
    used_pct = round((used / cap) * 100.0, 2)
    rem_pct = round(max(0.0, 100.0 - used_pct), 2)
    remaining_usd = round(max(0.0, cap - used), 4)
    exceeded = raw.get("exceeded")
    reset_at = _commandcode_reset_iso(_pick(raw, "resetAt", "reset_at", "resetsAt"))
    entry: dict[str, Any] = {
        "kind": kind,
        "used": used,
        "cap": cap,
        "remaining_usd": remaining_usd,
        "used_percent": used_pct,
        "remaining_percent": rem_pct,
        "exceeded": bool(exceeded) if exceeded is not None else rem_pct <= 0,
        "next_reset_at": reset_at,
        "summary": f"{rem_pct:.0f}% left ({label}) · ${remaining_usd:.2f} / ${cap:.2f}",
    }
    return entry


def _commandcode_plan_from_caps(
    session_cap: float | None,
    weekly_cap: float | None,
    plan_id: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Trust catalog total only when rolling caps match the published plan."""
    if plan_id and plan_id in COMMANDCODE_PLANS:
        plan = COMMANDCODE_PLANS[plan_id]
        if session_cap is not None and weekly_cap is not None:
            if abs(session_cap - float(plan["session_cap"])) <= 0.05 and abs(
                weekly_cap - float(plan["weekly_cap"])
            ) <= 0.05:
                return plan_id, plan
    if session_cap is None or weekly_cap is None:
        return plan_id if plan_id in COMMANDCODE_PLANS else None, None
    matches = [
        (pid, spec)
        for pid, spec in COMMANDCODE_PLANS.items()
        if abs(session_cap - float(spec["session_cap"])) <= 0.05
        and abs(weekly_cap - float(spec["weekly_cap"])) <= 0.05
    ]
    if len(matches) == 1:
        return matches[0]
    return None, None


def _unwrap_commandcode_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    inner = data.get("data")
    if isinstance(inner, dict):
        return inner
    return data


def probe_commandcode_credits() -> dict[str, Any]:
    """Fetch Command Code GOAT (and other plans) credits + rolling windows.

    Primary: GET https://api.commandcode.ai/alpha/billing/credits (Bearer Provider key).
    Optional: GET .../alpha/billing/subscriptions for planId / billing period.
    Cookie /internal/billing/* is not used (session, not Dockhand secret).
    """
    key = get_commandcode_api_key()
    result: dict[str, Any] = {
        "provider": "commandcode",
        "email": "commandcode-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "commandcode-credits",
        "status": "error",
        "plan_id": None,
        "plan_label": None,
        "monthly_credits": None,
        "monthly_allowance": None,
        "purchased_credits": None,
        "session": None,
        "weekly": None,
        "monthly": None,
        "error": None,
        "source": "commandcode-alpha-billing-credits",
    }
    if not key:
        result["status"] = "manual"
        result["error"] = "COMMANDCODE_API_KEY not set"
        return result

    proxy = get_commandcode_proxy()
    result["via"] = {"proxy": redact_proxy_url(proxy)}

    st, _hdrs, data, err = http_json(
        COMMANDCODE_API_BASE + COMMANDCODE_CREDITS_PATH,
        token=key,
        proxy=proxy,
        timeout=15.0,
    )
    if st != 200 or not isinstance(data, dict):
        err_obj = data.get("error") if isinstance(data, dict) else None
        msg = err_obj.get("message") if isinstance(err_obj, dict) else None
        result["error"] = f"credits API: {st} {msg or err or data}".strip()
        return result
    if data.get("success") is False:
        err_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
        msg = err_obj.get("message") or data
        result["error"] = f"credits API: {st} {msg}".strip()
        return result

    payload = _unwrap_commandcode_payload(data) or {}
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else payload
    window_limits = _pick(payload, "windowLimits", "window_limits")
    if not isinstance(window_limits, dict):
        window_limits = _pick(credits if isinstance(credits, dict) else {}, "windowLimits", "window_limits")
    if not isinstance(window_limits, dict):
        window_limits = {}
    if not isinstance(credits, dict):
        credits = {}

    monthly_remaining = _as_float(_pick(credits, "monthlyCredits", "monthly_credits"))
    purchased = _as_float(_pick(credits, "purchasedCredits", "purchased_credits")) or 0.0
    five_raw = _pick(window_limits, "fiveHour", "five_hour")
    week_raw = _pick(window_limits, "weekly")
    session = _parse_commandcode_window(five_raw, "session", "5h")
    weekly = _parse_commandcode_window(week_raw, "weekly", "week")

    plan_id = None
    period_end = None
    try:
        st2, _h2, data2, _e2 = http_json(
            COMMANDCODE_API_BASE + COMMANDCODE_SUBSCRIPTIONS_PATH,
            token=key,
            proxy=proxy,
            timeout=8.0,
        )
        if st2 == 200 and isinstance(data2, dict) and data2.get("success") is not False:
            sub = _unwrap_commandcode_payload(data2) or {}
            plan_id = _pick(sub, "planId", "plan_id")
            if isinstance(plan_id, str):
                plan_id = plan_id.strip() or None
            period_end = _pick(sub, "currentPeriodEnd", "current_period_end")
            result["subscription"] = {
                "plan_id": plan_id,
                "status": _pick(sub, "status"),
                "current_period_end": period_end,
            }
    except Exception:
        pass

    session_cap = session["cap"] if session else None
    weekly_cap = weekly["cap"] if weekly else None
    matched_id, plan = _commandcode_plan_from_caps(session_cap, weekly_cap, plan_id if isinstance(plan_id, str) else None)
    allowance = float(plan["monthly_credits"]) if plan else None
    if (
        allowance is not None
        and monthly_remaining is not None
        and monthly_remaining > allowance + 0.05
    ):
        allowance = None
        plan = None
        matched_id = None

    monthly = None
    if monthly_remaining is not None:
        if allowance and allowance > 0:
            used = round(max(0.0, allowance - monthly_remaining), 4)
            used_pct = round((used / allowance) * 100.0, 2)
            rem_pct = round(max(0.0, (monthly_remaining / allowance) * 100.0), 2)
            monthly = {
                "kind": "monthly",
                "used": used,
                "cap": allowance,
                "remaining_usd": round(monthly_remaining, 4),
                "used_percent": used_pct,
                "remaining_percent": rem_pct,
                "next_reset_at": period_end if isinstance(period_end, str) else None,
                "summary": f"{rem_pct:.0f}% left (month) · ${monthly_remaining:.2f} / ${allowance:.2f}",
            }
        else:
            monthly = {
                "kind": "monthly",
                "used": None,
                "cap": None,
                "remaining_usd": round(monthly_remaining, 4),
                "used_percent": None,
                "remaining_percent": None,
                "next_reset_at": period_end if isinstance(period_end, str) else None,
                "summary": f"${monthly_remaining:.2f} left (month)",
            }

    result["ok"] = True
    result["status"] = "active"
    result["plan_id"] = matched_id or (plan_id if isinstance(plan_id, str) else None)
    result["plan_label"] = (plan or {}).get("label") if plan else None
    result["monthly_credits"] = monthly_remaining
    result["monthly_allowance"] = allowance
    result["purchased_credits"] = purchased
    result["session"] = session
    result["weekly"] = weekly
    result["monthly"] = monthly

    parts = []
    if monthly_remaining is not None:
        parts.append(f"${monthly_remaining:.2f} month")
    if session:
        parts.append(session["summary"])
    if weekly:
        parts.append(weekly["summary"])
    label = result["plan_label"] or result["plan_id"] or "Command Code"
    result["remaining_summary"] = f"{label} · " + " · ".join(parts) if parts else str(label)
    return result


def build_commandcode_wallet(probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not probe:
        return None
    status = probe.get("status") or ("active" if probe.get("ok") else "error")
    return {
        "provider": "commandcode",
        "email": "commandcode-main",
        "name": "Command Code",
        "kind": "commandcode-credits",
        "status": status,
        "ok": bool(probe.get("ok")),
        "plan_id": probe.get("plan_id"),
        "plan_label": probe.get("plan_label"),
        "monthly_credits": probe.get("monthly_credits"),
        "monthly_allowance": probe.get("monthly_allowance"),
        "purchased_credits": probe.get("purchased_credits"),
        "session": probe.get("session") or {},
        "weekly": probe.get("weekly") or {},
        "monthly": probe.get("monthly") or {},
        "remaining_summary": probe.get("remaining_summary") or "",
        "subscription": probe.get("subscription"),
        "error": probe.get("error"),
        "probed_at": probe.get("probed_at"),
        "source": probe.get("source") or "commandcode-alpha-billing-credits",
        "via": probe.get("via"),
    }


def _probe_cache_stale(cache: dict[str, Any]) -> bool:
    acc = (cache or {}).get("accounts") or {}
    if not all(k in acc for k in WALLET_PROBE_KEYS):
        return True
    updated = cache.get("updated_at")
    if not updated:
        return True
    try:
        ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() > QUOTA_PROBE_SECONDS
    except Exception:
        return True


def collect_state(force_quota: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    with _quota_lock:
        global _quota_cache
        need_probe = force_quota or _probe_cache_stale(_quota_cache)
        if need_probe:
            probed: dict[str, Any] = {}
            try:
                ds_result = probe_deepseek_balance()
                if ds_result is not None:
                    probed["deepseek-main"] = ds_result
            except Exception as e:
                errors.append(f"deepseek-balance-probe: {e}")
            try:
                or_result = probe_openrouter_wallet()
                if or_result is not None:
                    probed["openrouter-main"] = or_result
            except Exception as e:
                errors.append(f"openrouter-wallet-probe: {e}")
            try:
                zai_result = probe_zai_quota()
                if zai_result is not None:
                    probed["zai-main"] = zai_result
            except Exception as e:
                errors.append(f"zai-quota-probe: {e}")
            try:
                cc_result = probe_commandcode_credits()
                if cc_result is not None:
                    probed["commandcode-main"] = cc_result
            except Exception as e:
                errors.append(f"commandcode-credits-probe: {e}")
            _quota_cache = {
                "updated_at": now_iso(),
                "accounts": probed,
            }
            save_json(QUOTA_CACHE_PATH, _quota_cache)
        quota_accounts = dict((_quota_cache or {}).get("accounts") or {})

    wallets: dict[str, Any] = {}
    deepseek_wallet = build_deepseek_wallet(quota_accounts.get("deepseek-main"))
    openrouter_wallet = build_openrouter_wallet(quota_accounts.get("openrouter-main"))
    zai_wallet = build_zai_wallet(quota_accounts.get("zai-main"))
    commandcode_wallet = build_commandcode_wallet(quota_accounts.get("commandcode-main"))
    if deepseek_wallet:
        wallets["deepseek"] = deepseek_wallet
    if openrouter_wallet:
        wallets["openrouter"] = openrouter_wallet
    if zai_wallet:
        wallets["zai"] = zai_wallet
    if commandcode_wallet:
        wallets["commandcode"] = commandcode_wallet

    return {
        "updated_at": now_iso(),
        "providers": {
            "wallets": {
                "label": "Wallets",
                "kind": "wallets",
                "keys": list(wallets.keys()),
                "quota_probe_updated_at": (_quota_cache or {}).get("updated_at"),
            }
        },
        "accounts": [],
        "wallets": wallets,
        "errors": errors,
        "notes": [
            "DeepSeek wallet: balance only; 24h spend from local snapshots (no usage history API).",
            "OpenRouter wallet: account credits (total_credits-total_usage) + key usage_daily; rolling 24h from snapshots.",
            "Z.AI wallet: short session + weekly token limits + MCP tools from quota/limit API.",
            "Command Code wallet: monthly remaining credits + 5h/weekly rolling windows from /alpha/billing/credits.",
            f"Usage window: last {USAGE_WINDOW_HOURS}h.",
        ],
    }


def refresh_once(force_quota: bool = False) -> dict[str, Any]:
    state = collect_state(force_quota=force_quota)
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
def _startup() -> None:
    load_state()
    # Do not block uvicorn bind on network probes (DeepSeek/OpenRouter/Z.AI/Command Code).
    def _bg() -> None:
        try:
            refresh_once(force_quota=True)
        except Exception as e:
            with _lock:
                _state["errors"] = list(_state.get("errors") or []) + [f"startup-refresh: {e}"]
                _state["updated_at"] = now_iso()
    threading.Thread(target=_bg, name="usage-startup-refresh", daemon=True).start()
    threading.Thread(target=poller, name="usage-poller", daemon=True).start()


@app.get("/api/health")
def health() -> dict[str, Any]:
    with _lock:
        providers = _state.get("providers") or {}
        wallets = _state.get("wallets") or {}
        probe_at = (providers.get("wallets") or {}).get("quota_probe_updated_at")
        return {
            "ok": True,
            "updated_at": _state.get("updated_at"),
            "wallets": len(wallets),
            "errors": _state.get("errors") or [],
            "quota_probe_updated_at": probe_at,
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

