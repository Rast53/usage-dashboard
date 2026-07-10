#!/usr/bin/env python3
"""usage.raclaw.ru — multi-provider usage dashboard (CPA-first)."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover
    psycopg2 = None

CPA_BASE = os.environ.get("CPA_BASE", "http://127.0.0.1:8317")
CPA_MGMT_TOKEN = os.environ.get("CPA_MGMT_TOKEN", "openclaw")
# cliproxy dashboard postgres (usage_records is durable source of truth)
PG_DSN = os.environ.get(
    "USAGE_PG_DSN",
    "host=172.19.0.2 port=5432 dbname=cliproxyapi user=cliproxyapi password=CHANGE_ME_POSTGRES_PASSWORD",
)
USAGE_WINDOW_HOURS = int(os.environ.get("USAGE_WINDOW_HOURS", "24"))
DATA_DIR = Path(os.environ.get("USAGE_DATA_DIR", "/opt/usage-dashboard/data"))
STATIC_DIR = Path(os.environ.get("USAGE_STATIC_DIR", "/opt/usage-dashboard/static"))
SNAPSHOT_PATH = DATA_DIR / "snapshots.jsonl"
STATE_PATH = DATA_DIR / "state.json"
POLL_SECONDS = int(os.environ.get("USAGE_POLL_SECONDS", "60"))

app = FastAPI(title="usage.raclaw.ru", version="0.1.1")
_lock = threading.Lock()
_state: dict[str, Any] = {
    "updated_at": None,
    "providers": {},
    "accounts": [],
    "errors": [],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cpa_get(path: str, timeout: float = 10.0) -> Any:
    url = f"{CPA_BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {CPA_MGMT_TOKEN}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_state() -> None:
    global _state
    if STATE_PATH.exists():
        try:
            _state = json.loads(STATE_PATH.read_text())
        except Exception:
            pass


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(STATE_PATH)
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
                }
                for a in state.get("accounts", [])
            ],
        }, ensure_ascii=False) + "\n")


def fetch_usage_from_pg(window_hours: int = USAGE_WINDOW_HOURS) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Aggregate durable usage_records from cliproxy dashboard postgres."""
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


def collect_cpa() -> dict[str, Any]:
    errors: list[str] = []
    files: list[dict[str, Any]] = []

    try:
        auth = cpa_get("/v0/management/auth-files")
        files = auth.get("files") or []
    except Exception as e:
        errors.append(f"auth-files: {e}")

    usage_by_source, usage_errors = fetch_usage_from_pg()
    errors.extend(usage_errors)

    accounts: list[dict[str, Any]] = []
    provider_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "accounts": 0, "active": 0, "success": 0, "failed": 0,
        "tokens_total": 0, "tokens_in": 0, "tokens_out": 0, "requests": 0,
    })

    for f in files:
        email = f.get("email") or f.get("account") or f.get("name") or "unknown"
        provider = f.get("provider") or f.get("type") or "unknown"
        tok = usage_by_source.get(email, {})
        recent = f.get("recent_requests") or []
        recent_success = sum(int(x.get("success") or 0) for x in recent)
        recent_failed = sum(int(x.get("failed") or 0) for x in recent)

        account = {
            "provider": provider,
            "email": email,
            "name": f.get("name"),
            "status": f.get("status") or ("disabled" if f.get("disabled") else "unknown"),
            "status_message": f.get("status_message") or "",
            "disabled": bool(f.get("disabled")),
            "unavailable": bool(f.get("unavailable")),
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
            "source": "cpa+pg",
        }
        accounts.append(account)

        ps = provider_stats[provider]
        ps["accounts"] += 1
        if account["status"] == "active" and not account["disabled"]:
            ps["active"] += 1
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
            "source": "pg-usage-only",
        })

    accounts.sort(key=lambda a: (a["provider"], -(a["tokens_total"] or 0), a["email"] or ""))

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
            }
        },
        "accounts": accounts,
        "errors": errors,
        "notes": [
            "Tokens/models come from cliproxy dashboard postgres usage_records (durable), not from CPA usage-queue (ephemeral).",
            f"Usage window: last {USAGE_WINDOW_HOURS}h.",
            "success/failed still come from CPA auth-files live counters.",
            "CPA does not expose native SuperGrok remaining quota.",
        ],
    }


def refresh_once() -> dict[str, Any]:
    state = collect_cpa()
    with _lock:
        global _state
        _state = state
        save_state(state)
        return state


def poller() -> None:
    while True:
        try:
            refresh_once()
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
        refresh_once()
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


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    try:
        return refresh_once()
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
