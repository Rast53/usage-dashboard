#!/usr/bin/env python3
"""usage.raclaw.ru — multi-provider usage dashboard (CPA-first)."""

from __future__ import annotations

import base64
import json
import os
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

app = FastAPI(title="usage.raclaw.ru", version="0.2.0")
_lock = threading.Lock()
_state: dict[str, Any] = {
    "updated_at": None,
    "providers": {},
    "accounts": [],
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


def http_json(url: str, token: str, proxy: str | None = None, method: str = "GET", body: bytes | None = None, timeout: float = 20.0) -> tuple[int | None, dict[str, str], Any, str | None]:
    handlers = []
    if proxy:
        handlers.append(urlrequest.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urlrequest.build_opener(*handlers) if handlers else urlrequest.build_opener()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else None
            except Exception:
                data = raw
            return resp.status, dict(resp.headers.items()), data, None
    except HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            data = json.loads(raw) if raw else None
        except Exception:
            data = raw
        return e.code, dict(e.headers.items() if e.headers else []), data, raw[:500] or str(e)
    except URLError as e:
        return None, {}, None, str(e)
    except Exception as e:
        return None, {}, None, str(e)


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

    # /v1/me for team_blocked
    st, headers, data, err = http_json("https://api.x.ai/v1/me", token, proxy=proxy, timeout=15)
    if st == 200 and isinstance(data, dict):
        result["ok"] = True
        result["team_blocked"] = bool(data.get("team_blocked"))
        result["team_id"] = data.get("team_id") or result["team_id"]
        result["user_id"] = data.get("user_id") or result["user_id"]
        if result["team_blocked"]:
            result["blocked_reason"] = result["blocked_reason"] or "team_blocked=true"
            result["notes"].append("xAI /v1/me team_blocked=true")
        else:
            result["notes"].append("xAI /v1/me team_blocked=false")
    else:
        result["error"] = f"/v1/me failed: {st} {err or ''}".strip()

    # Rate-limit headers appear on chat/completions, not on /models.
    # Tiny completion is used only for live accounts; blocked accounts skip spend.
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

    # Interpret what we can honestly say about "remaining usage"
    if result["team_blocked"]:
        result["remaining_summary"] = "0 (team blocked / spending-limit)"
        result["reset_summary"] = result["cpa"].get("next_retry_after") or "unknown weekly/credit reset (not exposed by API)"
    elif rem_tok is not None and limit_tok is not None:
        result["remaining_summary"] = f"{rem_tok}/{limit_tok} tokens (rate-limit window)"
        result["reset_summary"] = reset_tok or reset_req or "rolling window (no reset timestamp from API)"
    else:
        result["remaining_summary"] = "unknown (no SuperGrok remaining endpoint)"
        result["reset_summary"] = result["cpa"].get("next_retry_after") or "unknown"

    result["notes"].append(
        "xAI API does not expose SuperGrok weekly remaining/reset; rate-limit headers are short-window RPM/TPM only."
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

    # quota probe cache
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
        if need_probe and files:
            try:
                _quota_cache = probe_all_xai(files)
            except Exception as e:
                errors.append(f"quota-probe: {e}")
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

    accounts.sort(key=lambda a: (
        0 if a.get("unavailable") or (a.get("quota") or {}).get("team_blocked") else 1,
        a["provider"],
        -(a["tokens_total"] or 0),
        a["email"] or "",
    ))

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
        "errors": errors,
        "notes": [
            "Tokens/models from cliproxy postgres usage_records (durable), not CPA usage-queue.",
            f"Usage window: last {USAGE_WINDOW_HOURS}h.",
            "xAI remaining: rate-limit window remaining (RPM/TPM headers) + team_blocked from /v1/me.",
            "xAI does NOT expose SuperGrok weekly remaining/reset via public API; that still requires console/UI.",
            "CPA next_retry_after is cooldown after quota/spending-limit error, not billing cycle reset.",
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
