#!/usr/bin/env python3
"""usage.ragpt.ru — multi-provider usage dashboard (wallets)."""

from __future__ import annotations

import html as html_lib
import json
import os
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

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
USAGE_WINDOW_7D_HOURS = 168
SPEND_SERIES_DAYS = 8
# Today + 30 complete prior calendar days for Alan MSK table.
CALENDAR_SPEND_DAYS = 31
# Moscow is UTC+3 year-round (no DST since 2014). Avoid tzdata in slim image.
MSK_TZ = timezone(timedelta(hours=3), name="MSK")
DISPLAY_TZ_UTC = "UTC"
DISPLAY_TZ_MSK = "Europe/Moscow"
NO_MODEL_BREAKDOWN = "нет разбивки от провайдера"
NO_FRESH_EXPORT = "нет свежих данных экспорта"
OPENROUTER_EXPORT_DEFAULT_PATH = "/app/export/openrouter_key_models.json"
OPENROUTER_EXPORT_THROTTLE_SECONDS = 300
OPENROUTER_IMPORT_MAX_AGE_SECONDS = 1800
OPENROUTER_EXPORT_HASH_SUFFIX_LEN = 8
DEFAULT_SITE_TITLE = "Мои подписки"
KNOWN_PROVIDERS: tuple[str, ...] = (
    "deepseek",
    "openrouter",
    "zai",
    "commandcode",
    "kimi",
    "opencode-go",
)
WALLET_PROBE_KEYS = tuple(f"{name}-main" for name in KNOWN_PROVIDERS)

COMMANDCODE_API_BASE = "https://api.commandcode.ai"
COMMANDCODE_CREDITS_PATH = "/alpha/billing/credits"
COMMANDCODE_SUBSCRIPTIONS_PATH = "/alpha/billing/subscriptions"
KIMI_CODE_DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
KIMI_CODE_USAGES_PATH = "/usages"
OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
OPENCODE_GO_USAGE_PATH = "/usage"
# Published Go windows (docs 2026-08-25). The usage API returns used %, not USD.
OPENCODE_GO_CAPS: dict[str, float] = {
    "session": 12.0,
    "weekly": 30.0,
    "monthly": 60.0,
}
# Mirror frontend pill semantics: ok if delta_pp <= 5, warn if <= 20, else danger.
PACE_OK_DELTA_PP = 5
PACE_WARN_DELTA_PP = 20
PACE_SESSION_MINUTES = 300
PACE_WEEKLY_MINUTES = 10080
PACE_WINDOW_SPECS: tuple[tuple[str, str, int], ...] = (
    ("session", "5h", PACE_SESSION_MINUTES),
    ("weekly", "weekly", PACE_WEEKLY_MINUTES),
)
# Published weekly request quotas (Kimi Code membership docs 2026-08-25). 5h cap is 200 for all tiers.
KIMI_WEEKLY_PLANS: dict[float, str] = {
    1024.0: "Andante",
    2048.0: "Moderato",
    7168.0: "Allegretto",
}
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
_openrouter_export_lock = threading.Lock()
_openrouter_export_last_mono: float = 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def save_json(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)


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
    invalidate_snapshot_cache()


_snapshot_rows_cache: list[dict[str, Any]] | None = None
_snapshot_rows_key: tuple[str, float, int] | None = None


def invalidate_snapshot_cache() -> None:
    global _snapshot_rows_cache, _snapshot_rows_key
    _snapshot_rows_cache = None
    _snapshot_rows_key = None


def models_unavailable(detail: str | None = None, *, reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "available": False,
        "reason": reason or NO_MODEL_BREAKDOWN,
        "items": [],
    }
    if detail:
        out["detail"] = detail
    return out


def parse_snapshot_ts(ts_raw: Any) -> tuple[float, str] | None:
    if ts_raw is None:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_s = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return ts.timestamp(), ts_s
    except Exception:
        return None


def load_snapshot_rows() -> list[dict[str, Any]]:
    """Parse snapshots.jsonl once per (path, mtime, size). Skip malformed lines; never raise."""
    global _snapshot_rows_cache, _snapshot_rows_key
    if not SNAPSHOT_PATH.exists():
        invalidate_snapshot_cache()
        return []
    try:
        st = SNAPSHOT_PATH.stat()
        key = (str(SNAPSHOT_PATH), st.st_mtime, st.st_size)
    except OSError:
        return []
    if _snapshot_rows_cache is not None and _snapshot_rows_key == key:
        return _snapshot_rows_cache
    rows: list[dict[str, Any]] = []
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
                if isinstance(obj, dict):
                    rows.append(obj)
    except Exception:
        return []
    _snapshot_rows_cache = rows
    _snapshot_rows_key = key
    return rows


def pick_baseline(
    points: list[tuple[float, str, Any]],
    window_hours: int,
    now: datetime | None = None,
) -> tuple[str | None, Any, bool, str | None]:
    """Newest point at/before window start, else first in-window (partial).

    Returns (baseline_at, value, partial, gap).
    """
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    cutoff = now_ts - window_hours * 3600
    pre: tuple[str, Any] | None = None
    first_in: tuple[str, Any] | None = None
    for epoch, ts_s, value in points:
        if epoch < cutoff:
            pre = (ts_s, value)
            continue
        if first_in is None:
            first_in = (ts_s, value)
    if pre is not None:
        return pre[0], pre[1], False, None
    if first_in is not None:
        return first_in[0], first_in[1], True, None
    return None, None, True, "no-history"


def _empty_spend(window_hours: int, note: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "window_hours": window_hours,
        "partial": True,
        "gap": "no-history",
        "baseline_at": None,
        "spent": None,
        "spent_summary": "недостаточно истории",
        "note": note,
    }
    if extra:
        out.update(extra)
    return out


def _empty_spend_series(unit: str, note: str, days: int = SPEND_SERIES_DAYS) -> dict[str, Any]:
    return {
        "days": days,
        "partial": True,
        "gap": "no-history",
        "unit": unit,
        "points": [],
        "note": note,
    }


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_site_title() -> str:
    raw = os.environ.get("SITE_TITLE", "").strip()
    return raw or DEFAULT_SITE_TITLE


def get_enabled_providers() -> list[str]:
    """Comma-separated PROVIDERS allowlist. Empty/unset → all known providers."""
    raw = os.environ.get("PROVIDERS")
    if raw is None or not str(raw).strip():
        return list(KNOWN_PROVIDERS)
    known = set(KNOWN_PROVIDERS)
    seen: list[str] = []
    for part in str(raw).split(","):
        name = part.strip().lower()
        if name in known and name not in seen:
            seen.append(name)
    return seen


def get_openrouter_base_url() -> str:
    raw = os.environ.get("OPENROUTER_BASE_URL", "").strip().rstrip("/")
    return raw or OPENROUTER_DEFAULT_BASE_URL


def get_openrouter_proxy() -> str | None:
    raw = os.environ.get("OPENROUTER_PROXY", "").strip()
    return raw or None


def get_openrouter_ssl_verify() -> bool:
    return not _env_flag("OPENROUTER_SSL_NO_VERIFY", default=False)


def openrouter_key_only() -> bool:
    """OPENROUTER_KEY_ONLY=1 → GET /api/v1/key only; no credits/keys/activity."""
    return _env_flag("OPENROUTER_KEY_ONLY", default=False)


def get_display_tz() -> str:
    """IANA tz for UI timestamps. Unset = UTC; key-only without DISPLAY_TZ = Moscow."""
    raw = os.environ.get("DISPLAY_TZ", "").strip()
    if raw:
        key = raw.lower().replace(" ", "")
        if key in {"utc", "gmt", "etc/utc", "z"}:
            return DISPLAY_TZ_UTC
        if key in {"europe/moscow", "msk", "moscow", "msd"}:
            return DISPLAY_TZ_MSK
        return raw
    if openrouter_key_only():
        return DISPLAY_TZ_MSK
    return DISPLAY_TZ_UTC


def display_tz_label(name: str | None = None) -> str:
    tz = name or get_display_tz()
    if tz == DISPLAY_TZ_MSK:
        return "МСК"
    return "UTC"


def display_tzinfo(name: str | None = None) -> timezone:
    tz = name or get_display_tz()
    if tz == DISPLAY_TZ_MSK:
        return MSK_TZ
    return timezone.utc


def hide_partial_spend_chips() -> bool:
    """Alan page: do not render snapshot 24h/7d chips (often partial with ~)."""
    return openrouter_key_only() or get_display_tz() == DISPLAY_TZ_MSK


def get_openrouter_tracked_key_hash() -> str | None:
    """OPENROUTER_TRACKED_KEY_HASH empty/unset → export off. Refuse raw key-shaped values."""
    raw = os.environ.get("OPENROUTER_TRACKED_KEY_HASH", "").strip()
    if not raw:
        return None
    if raw.lower().startswith("sk-"):
        return None
    return raw


def get_openrouter_export_path() -> Path:
    raw = os.environ.get("OPENROUTER_EXPORT_PATH", "").strip()
    return Path(raw or OPENROUTER_EXPORT_DEFAULT_PATH)


def get_openrouter_import_path() -> Path:
    raw = os.environ.get("OPENROUTER_IMPORT_PATH", "").strip()
    return Path(raw or OPENROUTER_EXPORT_DEFAULT_PATH)


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
    """Estimate window spend as baseline_total - current_total from local snapshots.

    Positive spent = balance decreased. Negative = top-up / credit increased.
    Prefer newest snapshot at/before window start; else earliest in-window (partial).
    """
    result: dict[str, Any] = {
        "window_hours": window_hours,
        "partial": True,
        "gap": "no-history",
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

    points: list[tuple[float, str, list[dict[str, Any]]]] = []
    latest: tuple[str, list[dict[str, Any]]] | None = None
    try:
        for obj in load_snapshot_rows():
            ts_raw, bal = _extract_deepseek_balance_from_snapshot(obj)
            if bal is None:
                continue
            parsed = parse_snapshot_ts(ts_raw)
            if parsed is None:
                continue
            epoch, ts_s = parsed
            points.append((epoch, ts_s, bal))
            latest = (ts_s, bal)
    except Exception as e:
        result["note"] = f"snapshot read error: {e}"
        return result

    baseline_ts, baseline_balance, partial, gap = pick_baseline(points, window_hours)
    if gap or baseline_balance is None:
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
        "gap": None,
        "baseline_at": baseline_ts,
        "baseline": base,
        "current": cur,
        "spent": spent,
        "spent_summary": (" · ".join(pretty) if pretty else "0") + (" (частичная история)" if partial else ""),
        "note": (
            f"{window_hours}h spend estimated from local snapshots: baseline_balance - current_balance. "
            "DeepSeek API does not expose usage history."
        ),
    })
    return result


def compute_deepseek_spend_7d(
    current_balance: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return compute_deepseek_spend_24h(current_balance, window_hours=USAGE_WINDOW_7D_HOURS)


def build_deepseek_wallet(ds_quota: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ds_quota:
        return None
    spend = compute_deepseek_spend_24h(ds_quota.get("balance"))
    spend_7d = compute_deepseek_spend_7d(ds_quota.get("balance"))
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
        "spend_7d": spend_7d,
        "spend_series_7d": compute_deepseek_spend_series_7d(ds_quota.get("balance")),
        "models": models_unavailable("DeepSeek API has no per-model usage endpoint"),
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


def _openrouter_activity_day(item: dict[str, Any]) -> str:
    # реальный API: "2026-08-24 00:00:00", не ISO-only
    return str(item.get("date") or "")[:10]


def _openrouter_activity_model_name(item: dict[str, Any]) -> str:
    return str(item.get("model") or item.get("model_permaslug") or "?").strip() or "?"


def _openrouter_day_windows(now: datetime) -> dict[str, set[str]]:
    today = now.date()
    return {
        "24h": {today.isoformat(), (today - timedelta(days=1)).isoformat()},
        "7d": {(today - timedelta(days=i)).isoformat() for i in range(7)},
        "30d": {(today - timedelta(days=i)).isoformat() for i in range(30)},
    }


def _fmt_iso_day(iso: str | None) -> str:
    raw = str(iso or "")[:10]
    if len(raw) < 10 or raw[4] != "-" or raw[7] != "-":
        return "—"
    year, month, day = raw.split("-")
    return f"{day}.{month}"


def _openrouter_key_window_meta(now: datetime) -> dict[str, Any]:
    """UTC calendar windows for Alan per-model: yesterday / last 7d / last 30d."""
    today = now.date()
    yesterday = today - timedelta(days=1)
    return {
        "tz": "UTC",
        "yesterday": yesterday.isoformat(),
        "days_7": {
            "from": (today - timedelta(days=6)).isoformat(),
            "to": today.isoformat(),
        },
        "days_30": {
            "from": (today - timedelta(days=29)).isoformat(),
            "to": today.isoformat(),
        },
    }


def openrouter_key_models_note(windows: dict[str, Any] | None) -> str:
    """Footnote with explicit UTC dates; no 'export from account' jargon."""
    if not isinstance(windows, dict):
        return "UTC-дни activity"
    y = _fmt_iso_day(windows.get("yesterday") if isinstance(windows.get("yesterday"), str) else None)
    d7 = windows.get("days_7") if isinstance(windows.get("days_7"), dict) else {}
    d30 = windows.get("days_30") if isinstance(windows.get("days_30"), dict) else {}
    return (
        f"вчера {y} UTC · "
        f"7 дней {_fmt_iso_day(d7.get('from'))}–{_fmt_iso_day(d7.get('to'))} UTC · "
        f"30 дней {_fmt_iso_day(d30.get('from'))}–{_fmt_iso_day(d30.get('to'))} UTC"
    )


def aggregate_openrouter_models(
    items: list[Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Roll GET /api/v1/activity rows into per-model spend (UTC calendar days)."""
    now = now or datetime.now(timezone.utc)
    windows = _openrouter_day_windows(now)

    def _accumulate(subset: set[str]) -> list[dict[str, Any]]:
        by_model: dict[str, dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            day = _openrouter_activity_day(it)
            if day not in subset:
                continue
            model = _openrouter_activity_model_name(it)
            bucket = by_model.setdefault(
                model,
                {
                    "model": model,
                    "usage": 0.0,
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                },
            )
            bucket["usage"] += float(it.get("usage") or 0)
            bucket["requests"] += int(it.get("requests") or 0)
            bucket["prompt_tokens"] += int(it.get("prompt_tokens") or 0)
            bucket["completion_tokens"] += int(it.get("completion_tokens") or 0)
            bucket["reasoning_tokens"] += int(it.get("reasoning_tokens") or 0)
        out = sorted(by_model.values(), key=lambda row: float(row["usage"]), reverse=True)[:8]
        for row in out:
            row["usage"] = round(float(row["usage"]), 6)
        return out

    return {
        "available": True,
        "source": "openrouter-activity",
        "endpoint": "/api/v1/activity",
        "partial": True,
        "reason": None,
        "items": _accumulate(windows["7d"]),
        "items_24h": _accumulate(windows["24h"]),
        "note": "UTC calendar days from GET /api/v1/activity (management key); not rolling hours",
    }


def aggregate_openrouter_key_models(
    items: list[Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-key activity rows → export contract (yesterday / 7d / 30d UTC calendar days).

    `usage_24h` keeps the schema-1 field name and means yesterday (completed UTC day),
    not today+yesterday. Account-wide `aggregate_openrouter_models` is unchanged.
    """
    now = now or datetime.now(timezone.utc)
    windows = _openrouter_day_windows(now)
    meta = _openrouter_key_window_meta(now)
    yesterday = meta["yesterday"]
    by_model: dict[str, dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        day = _openrouter_activity_day(it)
        if day not in windows["30d"]:
            continue
        model = _openrouter_activity_model_name(it)
        usage = float(it.get("usage") or 0)
        requests = int(it.get("requests") or 0)
        bucket = by_model.setdefault(
            model,
            {
                "model": model,
                "usage_24h": 0.0,
                "usage_7d": 0.0,
                "usage_30d": 0.0,
                "requests_24h": 0,
                "requests_7d": 0,
            },
        )
        if day == yesterday:
            bucket["usage_24h"] += usage
            bucket["requests_24h"] += requests
        if day in windows["7d"]:
            bucket["usage_7d"] += usage
            bucket["requests_7d"] += requests
        bucket["usage_30d"] += usage
    models = sorted(
        by_model.values(),
        key=lambda row: (float(row["usage_7d"]), float(row["usage_30d"])),
        reverse=True,
    )
    for row in models:
        for key in ("usage_24h", "usage_7d", "usage_30d"):
            row[key] = round(float(row[key]), 6)
    return {
        "models": models,
        "totals": {
            "usage_24h": round(sum(float(row["usage_24h"]) for row in models), 6),
            "usage_7d": round(sum(float(row["usage_7d"]) for row in models), 6),
            "usage_30d": round(sum(float(row["usage_30d"]) for row in models), 6),
        },
        "windows": meta,
    }


def _openrouter_hash_suffix(tracked_hash: str) -> str:
    n = OPENROUTER_EXPORT_HASH_SUFFIX_LEN
    if len(tracked_hash) <= n:
        return tracked_hash
    return tracked_hash[-n:]


def _openrouter_export_skeleton(
    *,
    updated_at: str,
    suffix: str,
    models: list[dict[str, Any]],
    totals: dict[str, Any],
    last_error: str | None = None,
    windows: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "updated_at": updated_at,
        "key_label_hash_suffix": suffix,
        "models": models,
        "totals": {
            "usage_24h": float(totals.get("usage_24h") or 0),
            "usage_7d": float(totals.get("usage_7d") or 0),
            "usage_30d": float(totals.get("usage_30d") or 0),
        },
    }
    if isinstance(windows, dict) and windows:
        payload["windows"] = windows
    if last_error:
        payload["last_error"] = last_error
    return payload


def _read_openrouter_export_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _write_openrouter_export_error(path: Path, suffix: str, err: str) -> None:
    prev = _read_openrouter_export_file(path) or {}
    models = prev.get("models") if isinstance(prev.get("models"), list) else []
    totals = prev.get("totals") if isinstance(prev.get("totals"), dict) else {}
    prev_suffix = prev.get("key_label_hash_suffix")
    if isinstance(prev_suffix, str) and prev_suffix:
        suffix = prev_suffix
    prev_windows = prev.get("windows") if isinstance(prev.get("windows"), dict) else None
    atomic_write_json(
        path,
        _openrouter_export_skeleton(
            updated_at=now_iso(),
            suffix=suffix,
            models=[row for row in models if isinstance(row, dict)],
            totals=totals,
            last_error=err,
            windows=prev_windows,
        ),
    )


def fetch_openrouter_key_activity(
    tracked_hash: str,
) -> tuple[list[Any] | None, str | None]:
    mkey = get_openrouter_management_key()
    if not mkey:
        return None, "OPENROUTER_MANAGEMENT_KEY not set"
    proxy = get_openrouter_proxy()
    ssl_verify = get_openrouter_ssl_verify()
    url = openrouter_api_url("/api/v1/activity") + "?" + urlencode(
        {"api_key_hash": tracked_hash}
    )
    st, _hdrs, data, err = http_json(
        url,
        token=mkey,
        proxy=proxy,
        timeout=20.0,
        ssl_verify=ssl_verify,
    )
    if st == 200 and isinstance(data, dict) and isinstance(data.get("data"), list):
        return data.get("data") or [], None
    msg = None
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        msg = data["error"].get("message")
    return None, f"activity API: {st} {msg or err or 'error'}".strip()


def reset_openrouter_export_throttle() -> None:
    global _openrouter_export_last_mono
    _openrouter_export_last_mono = 0.0


def maybe_export_openrouter_key_models(
    *,
    now: datetime | None = None,
    force: bool = False,
) -> None:
    """Side-effect export for the main instance. No-op when hash unset. Never raises."""
    global _openrouter_export_last_mono
    tracked = get_openrouter_tracked_key_hash()
    if not tracked:
        return
    path = get_openrouter_export_path()
    suffix = _openrouter_hash_suffix(tracked)
    try:
        with _openrouter_export_lock:
            mono = time.monotonic()
            if (
                not force
                and _openrouter_export_last_mono
                and (mono - _openrouter_export_last_mono) < OPENROUTER_EXPORT_THROTTLE_SECONDS
            ):
                return
            _openrouter_export_last_mono = mono
            rows, err = fetch_openrouter_key_activity(tracked)
            if err or rows is None:
                _write_openrouter_export_error(path, suffix, err or "activity fetch failed")
                return
            rolled = aggregate_openrouter_key_models(rows, now=now)
            atomic_write_json(
                path,
                _openrouter_export_skeleton(
                    updated_at=now_iso(),
                    suffix=suffix,
                    models=rolled["models"],
                    totals=rolled["totals"],
                    windows=rolled.get("windows"),
                ),
            )
    except Exception as exc:
        try:
            _write_openrouter_export_error(path, suffix, f"export: {exc}")
        except Exception:
            pass


def _parse_export_updated_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def models_from_openrouter_key_export(payload: dict[str, Any]) -> dict[str, Any]:
    rows_in = payload.get("models") if isinstance(payload.get("models"), list) else []
    items: list[dict[str, Any]] = []
    items_24h: list[dict[str, Any]] = []
    for row in rows_in:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model") or "?").strip() or "?"
        usage_24h = round(float(row.get("usage_24h") or 0), 6)
        usage_7d = round(float(row.get("usage_7d") or 0), 6)
        usage_30d = round(float(row.get("usage_30d") or 0), 6)
        requests_24h = int(row.get("requests_24h") or 0)
        requests_7d = int(row.get("requests_7d") or 0)
        mapped = {
            "model": model,
            "usage": usage_7d,
            "requests": requests_7d,
            "usage_24h": usage_24h,
            "usage_7d": usage_7d,
            "usage_30d": usage_30d,
            "requests_24h": requests_24h,
            "requests_7d": requests_7d,
        }
        items.append(mapped)
        items_24h.append(
            {
                "model": model,
                "usage": usage_24h,
                "requests": requests_24h,
                "usage_24h": usage_24h,
                "usage_7d": usage_7d,
                "usage_30d": usage_30d,
                "requests_24h": requests_24h,
                "requests_7d": requests_7d,
            }
        )
    items.sort(key=lambda row: float(row["usage"]), reverse=True)
    items_24h.sort(key=lambda row: float(row["usage"]), reverse=True)
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    windows = payload.get("windows") if isinstance(payload.get("windows"), dict) else None
    if not windows:
        ts = _parse_export_updated_at(payload.get("updated_at"))
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        windows = _openrouter_key_window_meta(ts or datetime.now(timezone.utc))
    return {
        "available": True,
        "source": "openrouter-key-export",
        "endpoint": None,
        "partial": True,
        "reason": None,
        "items": items,
        "items_24h": items_24h,
        "windows": windows,
        "note": openrouter_key_models_note(windows),
        "totals": {
            "usage_24h": round(float(totals.get("usage_24h") or 0), 6),
            "usage_7d": round(float(totals.get("usage_7d") or 0), 6),
            "usage_30d": round(float(totals.get("usage_30d") or 0), 6),
        },
    }


def load_openrouter_key_models_import(
    now: datetime | None = None,
) -> dict[str, Any]:
    """Key-only importer. Missing → no breakdown; stale → no fresh export. Never raises."""
    path = get_openrouter_import_path()
    if not path.exists():
        return models_unavailable()
    payload = _read_openrouter_export_file(path)
    if not payload:
        return models_unavailable(reason=NO_FRESH_EXPORT)
    ts = _parse_export_updated_at(payload.get("updated_at"))
    if ts is None:
        return models_unavailable(reason=NO_FRESH_EXPORT)
    now = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age > OPENROUTER_IMPORT_MAX_AGE_SECONDS or age < -60:
        return models_unavailable(reason=NO_FRESH_EXPORT)
    try:
        return models_from_openrouter_key_export(payload)
    except Exception:
        return models_unavailable(reason=NO_FRESH_EXPORT)


def _openrouter_key_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": payload.get("label"),
        "usage": payload.get("usage"),
        "usage_daily": payload.get("usage_daily"),
        "usage_weekly": payload.get("usage_weekly"),
        "usage_monthly": payload.get("usage_monthly"),
        "limit": payload.get("limit"),
        "limit_remaining": payload.get("limit_remaining"),
        "is_free_tier": payload.get("is_free_tier"),
    }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _openrouter_key_remaining_summary(key: dict[str, Any]) -> str:
    """Spend-only summary for key-only mode. Never includes account remaining/credits.

    OpenRouter windows are UTC calendar (day / Mon–Sun week / month), not MSK.
    """
    parts: list[str] = []
    daily = _float_or_none(key.get("usage_daily"))
    weekly = _float_or_none(key.get("usage_weekly"))
    monthly = _float_or_none(key.get("usage_monthly"))
    if daily is not None:
        parts.append(f"−${daily:.2f} сутки UTC")
    if weekly is not None:
        parts.append(f"−${weekly:.2f} неделя UTC (пн–вс)")
    if monthly is not None:
        parts.append(f"−${monthly:.2f} месяц UTC")
    return " · ".join(parts)


def probe_openrouter_wallet() -> dict[str, Any]:
    """Fetch OpenRouter account credits + key usage.

    - GET /api/v1/credits → total_credits / total_usage (account-level)
    - GET /api/v1/key → per-key usage_daily/weekly/monthly
    - GET /api/v1/activity → per-model usage (management key, last 30 UTC days)
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
        "models": models_unavailable("GET /api/v1/activity требует management key"),
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

    if openrouter_key_only():
        st2, _h2, data2, err2 = http_json(
            openrouter_api_url("/api/v1/key"),
            token=key,
            proxy=proxy,
            timeout=15.0,
            ssl_verify=ssl_verify,
        )
        if st2 != 200 or not isinstance(data2, dict):
            result["error"] = f"key API: {st2} {err2 or data2}".strip()
            return result
        kpayload = data2.get("data") if isinstance(data2.get("data"), dict) else data2
        if not isinstance(kpayload, dict):
            result["error"] = f"key parse failed: {data2}"
            return result
        result["ok"] = True
        result["kind"] = "openrouter-key"
        result["key"] = _openrouter_key_from_payload(kpayload)
        result["remaining_summary"] = _openrouter_key_remaining_summary(result["key"])
        return result

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
        result["key"] = _openrouter_key_from_payload(kpayload)
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

    act_token = mkey or None
    if act_token:
        st4, _h4, data4, err4 = http_json(
            openrouter_api_url("/api/v1/activity"),
            token=act_token,
            proxy=proxy,
            timeout=20.0,
            ssl_verify=ssl_verify,
        )
        if st4 == 200 and isinstance(data4, dict) and isinstance(data4.get("data"), list):
            result["models"] = aggregate_openrouter_models(data4.get("data") or [])
        else:
            msg = None
            if isinstance(data4, dict) and isinstance(data4.get("error"), dict):
                msg = data4["error"].get("message")
            result["models"] = models_unavailable(
                f"activity API: {st4} {msg or err4 or data4}".strip()
            )
    return result


def _extract_openrouter_usage_from_snapshot(obj: dict[str, Any]) -> float | None:
    wallets = obj.get("wallets") or {}
    orw = wallets.get("openrouter") if isinstance(wallets, dict) else None
    if isinstance(orw, dict) and orw.get("total_usage") is not None:
        try:
            return float(orw.get("total_usage"))
        except Exception:
            return None
    return None


def compute_openrouter_spend_24h(
    current_total_usage: float | None,
    window_hours: int = USAGE_WINDOW_HOURS,
) -> dict[str, Any]:
    """Estimate rolling window spend from snapshots of account total_usage.

    spent = current_total_usage - baseline_total_usage (usage only goes up).
    """
    result: dict[str, Any] = {
        "window_hours": window_hours,
        "partial": True,
        "gap": "no-history",
        "baseline_at": None,
        "baseline_total_usage": None,
        "current_total_usage": current_total_usage,
        "spent": None,
        "spent_summary": "недостаточно истории",
        "note": f"rolling {window_hours}h spend from local snapshots of OpenRouter total_usage",
    }
    if current_total_usage is None:
        result["note"] = "no current total_usage"
        result["gap"] = "no-metric"
        return result
    if not SNAPSHOT_PATH.exists():
        result["note"] = "no snapshots yet"
        return result

    points: list[tuple[float, str, float]] = []
    try:
        for obj in load_snapshot_rows():
            usage_val = _extract_openrouter_usage_from_snapshot(obj)
            if usage_val is None:
                continue
            parsed = parse_snapshot_ts(obj.get("ts"))
            if parsed is None:
                continue
            points.append((parsed[0], parsed[1], usage_val))
    except Exception as e:
        result["note"] = f"snapshot read error: {e}"
        return result

    baseline_at, baseline_usage, partial, gap = pick_baseline(points, window_hours)
    if gap or baseline_usage is None:
        return result

    spent = round(float(current_total_usage) - float(baseline_usage), 6)
    if spent < 0:
        spent_summary = f"+${abs(spent):.2f} (usage dropped)"
    else:
        spent_summary = f"−${spent:.2f}"
    if partial:
        spent_summary += " (частичная история)"

    result.update({
        "partial": partial,
        "gap": None,
        "baseline_at": baseline_at,
        "baseline_total_usage": baseline_usage,
        "current_total_usage": float(current_total_usage),
        "spent": spent,
        "spent_summary": spent_summary,
    })
    return result


def compute_openrouter_spend_7d(current_total_usage: float | None) -> dict[str, Any]:
    return compute_openrouter_spend_24h(
        current_total_usage, window_hours=USAGE_WINDOW_7D_HOURS
    )


def build_openrouter_wallet(or_probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not or_probe:
        return None
    key = or_probe.get("key") or {}
    key_only = openrouter_key_only()
    keys = [] if key_only else (or_probe.get("keys") or [])
    total_usage = or_probe.get("total_usage")
    if key_only:
        total_usage = _float_or_none(key.get("usage"))
    spend = compute_openrouter_spend_24h(total_usage)
    spend_7d = compute_openrouter_spend_7d(total_usage)
    daily = key.get("usage_daily")
    try:
        daily_f = float(daily) if daily is not None else None
    except Exception:
        daily_f = None

    # Sum usage_daily across management keys when available (= account-ish today UTC)
    keys_daily = None
    if keys and not key_only:
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

    remaining = None if key_only else or_probe.get("remaining")
    remaining_summary = (
        _openrouter_key_remaining_summary(key)
        if key_only
        else (or_probe.get("remaining_summary") or "")
    )
    models = or_probe.get("models")
    if not isinstance(models, dict):
        models = models_unavailable("GET /api/v1/activity требует management key")
    if key_only:
        models = load_openrouter_key_models_import()
    return {
        "provider": "openrouter",
        "email": "openrouter-main",
        "name": "OpenRouter",
        "kind": "wallet-credits",
        "status": "active" if or_probe.get("ok") else "error",
        "ok": bool(or_probe.get("ok")),
        "total_credits": None if key_only else or_probe.get("total_credits"),
        "total_usage": total_usage,
        "remaining": remaining,
        "remaining_summary": remaining_summary,
        "key": key,
        "keys": keys,
        "usage_daily": daily_f,
        "usage_daily_all_keys": keys_daily,
        "usage_weekly": key.get("usage_weekly"),
        "usage_monthly": key.get("usage_monthly"),
        "error": or_probe.get("error"),
        "probed_at": or_probe.get("probed_at"),
        "spend_24h": spend,
        "spend_7d": spend_7d,
        "spend_series_7d": compute_openrouter_spend_series_7d(total_usage),
        "spend_calendar": (
            compute_openrouter_calendar_spend(total_usage) if key_only else None
        ),
        "spent_summary": spent_summary,
        "models": models,
        "source": (
            "openrouter-key-api+local-snapshots"
            if key_only
            else "openrouter-credits-api+local-snapshots"
        ),
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
        "spend_24h": compute_zai_spend(probe, USAGE_WINDOW_HOURS),
        "spend_7d": compute_zai_spend(probe, USAGE_WINDOW_7D_HOURS),
        "spend_series_7d": compute_zai_spend_series_7d(probe),
        "models": models_unavailable("Z.AI quota/limit API has no per-model breakdown"),
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


def _wallet_from_snapshot(obj: dict[str, Any], key: str) -> dict[str, Any] | None:
    wallets = obj.get("wallets")
    if not isinstance(wallets, dict):
        return None
    wallet = wallets.get(key)
    return wallet if isinstance(wallet, dict) else None


def _float_snapshot_points(
    extract,
) -> list[tuple[float, str, float]]:
    points: list[tuple[float, str, float]] = []
    for obj in load_snapshot_rows():
        parsed = parse_snapshot_ts(obj.get("ts"))
        if parsed is None:
            continue
        val = extract(obj)
        if val is None:
            continue
        points.append((parsed[0], parsed[1], val))
    return points


def compute_quota_spend(
    points: list[tuple[float, str, float]],
    current: float | None,
    window_hours: int,
    *,
    direction: str,
    unit: str,
    note: str,
) -> dict[str, Any]:
    """Snapshot delta for quota metrics.

    direction='increase' → spent = current - baseline (used tokens/requests/%).
    direction='decrease' → spent = baseline - current (remaining credits).
    Negative consumption (window reset / refill) → gap window-reset, spent null.
    """
    extra = {"current": current, "unit": unit, "baseline": None}
    result = _empty_spend(window_hours, note, extra=extra)
    if current is None:
        result["gap"] = "no-metric"
        result["note"] = "no current metric"
        return result
    if not SNAPSHOT_PATH.exists():
        result["note"] = "no snapshots yet"
        return result
    baseline_at, baseline, partial, gap = pick_baseline(points, window_hours)
    if gap or baseline is None:
        return result
    if direction == "increase":
        spent = round(float(current) - float(baseline), 6)
    else:
        spent = round(float(baseline) - float(current), 6)
    if spent < 0:
        result.update({
            "partial": True,
            "gap": "window-reset",
            "baseline_at": baseline_at,
            "baseline": baseline,
            "current": float(current),
            "spent": None,
            "spent_summary": "сброс окна, дельта недоступна",
            "note": note,
        })
        return result
    if unit == "$":
        summary = f"−${spent:.2f}"
    elif unit == "%":
        summary = f"−{spent:.1f}%"
    else:
        summary = f"−{spent:.2f} {unit}"
    if partial:
        summary += " (частичная история)"
    result.update({
        "partial": partial,
        "gap": None,
        "baseline_at": baseline_at,
        "baseline": baseline,
        "current": float(current),
        "spent": spent,
        "spent_summary": summary,
        "note": note,
        "unit": unit,
    })
    return result


def compute_spend_series_7d(
    points: list[tuple[float, str, float]],
    current: float | None,
    *,
    direction: str,
    unit: str,
    note: str,
    now: datetime | None = None,
    days: int = SPEND_SERIES_DAYS,
    tz: timezone | None = None,
) -> dict[str, Any]:
    """Daily spend points for a sparkline (calendar days in tz, including today).

    Default tz is UTC (8-day sparkline on usage.ragpt.ru). spent[day] = delta(
    last observation on day, last observation before day start). Missing days stay
    null (do not invent 0). Window reset → spent null + gap.
    """
    tzinfo = tz or timezone.utc
    now_dt = (now or datetime.now(timezone.utc)).astimezone(tzinfo)
    result = _empty_spend_series(unit, note, days=days)
    series_points = list(points)
    if current is not None:
        utc_now = now_dt.astimezone(timezone.utc)
        series_points.append(
            (utc_now.timestamp(), utc_now.strftime("%Y-%m-%dT%H:%M:%SZ"), float(current))
        )
    series_points.sort(key=lambda item: item[0])
    if len(series_points) < 2:
        result["note"] = "недостаточно точек для серии"
        return result

    today = now_dt.date()
    out_points: list[dict[str, Any]] = []
    any_value = False
    any_partial = False

    def last_before(epoch: float) -> float | None:
        val: float | None = None
        for item_epoch, _ts, value in series_points:
            if item_epoch < epoch:
                val = value
            else:
                break
        return val

    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        day_start = datetime(day.year, day.month, day.day, tzinfo=tzinfo)
        next_midnight = day_start + timedelta(days=1)
        start_ts = day_start.timestamp()
        end_excl = next_midnight.timestamp()
        now_ts = now_dt.timestamp() + 1e-9
        in_day = [
            item
            for item in series_points
            if start_ts <= item[0] < end_excl and item[0] <= now_ts
        ]
        row: dict[str, Any] = {"date": day.isoformat(), "spent": None, "partial": True}
        if not in_day:
            any_partial = True
            out_points.append(row)
            continue
        pre = last_before(start_ts)
        end_val = in_day[-1][2]
        if pre is None:
            if len(in_day) < 2:
                any_partial = True
                out_points.append(row)
                continue
            baseline = in_day[0][2]
            partial = True
        else:
            baseline = pre
            partial = False
        if direction == "increase":
            spent = round(float(end_val) - float(baseline), 6)
        else:
            spent = round(float(baseline) - float(end_val), 6)
        if spent < 0:
            row["gap"] = "window-reset"
            any_partial = True
            out_points.append(row)
            continue
        row["spent"] = spent
        row["partial"] = partial
        if partial:
            any_partial = True
        any_value = True
        out_points.append(row)

    result["points"] = out_points
    if not any_value:
        return result
    result["gap"] = None
    result["partial"] = any_partial
    return result


def _deepseek_series_scalar(
    balance_infos: list[dict[str, Any]] | None,
) -> tuple[float | None, str]:
    totals = _balance_totals(balance_infos)
    if "CNY" in totals:
        return totals["CNY"], "¥"
    if "USD" in totals:
        return totals["USD"], "$"
    if totals:
        code, val = next(iter(totals.items()))
        return val, str(code)
    return None, "¥"


def _deepseek_series_snapshot_points() -> list[tuple[float, str, float]]:
    points: list[tuple[float, str, float]] = []
    for obj in load_snapshot_rows():
        ts_raw, bal = _extract_deepseek_balance_from_snapshot(obj)
        if bal is None:
            continue
        parsed = parse_snapshot_ts(ts_raw)
        if parsed is None:
            continue
        scalar, _unit = _deepseek_series_scalar(bal)
        if scalar is None:
            continue
        points.append((parsed[0], parsed[1], scalar))
    return points


def compute_deepseek_spend_series_7d(
    current_balance: list[dict[str, Any]] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current, unit = _deepseek_series_scalar(current_balance)
    return compute_spend_series_7d(
        _deepseek_series_snapshot_points(),
        current,
        direction="decrease",
        unit=unit,
        note="DeepSeek daily balance delta from local snapshots",
        now=now,
    )


def compute_openrouter_spend_series_7d(
    current_total_usage: float | None,
    now: datetime | None = None,
    *,
    tz: timezone | None = None,
    days: int = SPEND_SERIES_DAYS,
) -> dict[str, Any]:
    points: list[tuple[float, str, float]] = []
    for obj in load_snapshot_rows():
        usage_val = _extract_openrouter_usage_from_snapshot(obj)
        if usage_val is None:
            continue
        parsed = parse_snapshot_ts(obj.get("ts"))
        if parsed is None:
            continue
        points.append((parsed[0], parsed[1], usage_val))
    return compute_spend_series_7d(
        points,
        current_total_usage,
        direction="increase",
        unit="$",
        note="OpenRouter daily total_usage delta from local snapshots",
        now=now,
        tz=tz,
        days=days,
    )


def _complete_calendar_spent(point: dict[str, Any] | None) -> float | None:
    if not point or point.get("spent") is None:
        return None
    if point.get("partial") or point.get("gap"):
        return None
    try:
        return float(point["spent"])
    except (TypeError, ValueError):
        return None


def _calendar_window(points: list[dict[str, Any]], asked_days: int) -> dict[str, Any]:
    """Sum of `asked_days` complete calendar days ending yesterday (today excluded)."""
    empty: dict[str, Any] = {
        "spent": None,
        "partial": True,
        "gap": "no-history",
        "complete_days": 0,
        "asked_days": asked_days,
        "from": None,
        "to": None,
    }
    if len(points) < asked_days + 1:
        return empty
    chunk = points[-(asked_days + 1) : -1]
    vals = [_complete_calendar_spent(p) for p in chunk]
    complete = [v for v in vals if v is not None]
    out = {
        "spent": None,
        "partial": True,
        "gap": "incomplete",
        "complete_days": len(complete),
        "asked_days": asked_days,
        "from": chunk[0].get("date") if chunk else None,
        "to": chunk[-1].get("date") if chunk else None,
    }
    if len(complete) < asked_days:
        return out
    out.update({
        "spent": round(sum(complete), 6),
        "partial": False,
        "gap": None,
    })
    return out


def compute_openrouter_calendar_spend(
    current_total_usage: float | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """MSK calendar windows from snapshots: yesterday / 7d / 30d complete days + total.

    Incomplete windows stay spent=null (UI shows em dash, no tilde). Total is
    lifetime key.usage from the API, not a snapshot delta.
    """
    series = compute_openrouter_spend_series_7d(
        current_total_usage,
        now=now,
        tz=MSK_TZ,
        days=CALENDAR_SPEND_DAYS,
    )
    points = list(series.get("points") or [])
    yesterday_pt = points[-2] if len(points) >= 2 else None
    y_spent = _complete_calendar_spent(yesterday_pt)
    yesterday = {
        "date": (yesterday_pt or {}).get("date"),
        "spent": y_spent,
        "partial": y_spent is None,
        "gap": None if y_spent is not None else (
            (yesterday_pt or {}).get("gap") or ("incomplete" if yesterday_pt else "no-history")
        ),
    }
    total_spent = _float_or_none(current_total_usage)
    days_7 = _calendar_window(points, 7)
    days_30 = _calendar_window(points, 30)
    y_date = yesterday.get("date")
    return {
        "tz": DISPLAY_TZ_MSK,
        "tz_label": "МСК",
        "yesterday": yesterday,
        "days_7": days_7,
        "days_30": days_30,
        "total": {
            "spent": total_spent,
            "partial": False,
            "gap": None if total_spent is not None else "no-history",
            "source": "key.usage",
        },
        "note": (
            f"вчера {_fmt_iso_day(y_date)}; "
            f"7 дней {_fmt_iso_day(days_7.get('from'))}–{_fmt_iso_day(days_7.get('to'))}; "
            f"30 дней {_fmt_iso_day(days_30.get('from'))}–{_fmt_iso_day(days_30.get('to'))} "
            "— полные сутки МСК (UTC+3); сегодняшние неполные сутки не входят. "
            "Всего — расход ключа за всё время. Окна OpenRouter API "
            "(сутки / неделя пн–вс / месяц) — UTC."
        ),
    }


def compute_zai_spend_series_7d(
    probe: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    weekly = (probe or {}).get("weekly") if isinstance(probe, dict) else None
    current = _as_float(weekly.get("currentValue")) if isinstance(weekly, dict) else None
    return compute_spend_series_7d(
        _float_snapshot_points(_extract_zai_weekly_used),
        current,
        direction="increase",
        unit="tok",
        note="Z.AI daily weekly.currentValue delta from local snapshots",
        now=now,
    )


def compute_commandcode_spend_series_7d(
    probe: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    current = None
    if isinstance(probe, dict):
        monthly = probe.get("monthly")
        if isinstance(monthly, dict):
            current = _as_float(monthly.get("remaining_usd"))
        if current is None:
            current = _as_float(probe.get("monthly_credits"))
    return compute_spend_series_7d(
        _float_snapshot_points(_extract_commandcode_monthly_remaining),
        current,
        direction="decrease",
        unit="$",
        note="Command Code daily monthly remaining delta from local snapshots",
        now=now,
    )


def compute_kimi_spend_series_7d(
    probe: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    weekly = (probe or {}).get("weekly") if isinstance(probe, dict) else None
    current = _as_float(weekly.get("used")) if isinstance(weekly, dict) else None
    return compute_spend_series_7d(
        _float_snapshot_points(_extract_kimi_weekly_used),
        current,
        direction="increase",
        unit="req",
        note="Kimi daily weekly.used delta from local snapshots",
        now=now,
    )


def compute_opencode_go_spend_series_7d(
    probe: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    monthly = (probe or {}).get("monthly") if isinstance(probe, dict) else None
    current = _as_float(monthly.get("used_usd")) if isinstance(monthly, dict) else None
    return compute_spend_series_7d(
        _float_snapshot_points(_extract_opencode_monthly_used),
        current,
        direction="increase",
        unit="$",
        note="OpenCode Go daily monthly.used_usd delta from local snapshots",
        now=now,
    )


def _extract_zai_weekly_used(obj: dict[str, Any]) -> float | None:
    wallet = _wallet_from_snapshot(obj, "zai")
    if not wallet:
        return None
    weekly = wallet.get("weekly")
    if not isinstance(weekly, dict):
        return None
    return _as_float(weekly.get("currentValue"))


def compute_zai_spend(
    probe: dict[str, Any] | None, window_hours: int
) -> dict[str, Any]:
    weekly = (probe or {}).get("weekly") if isinstance(probe, dict) else None
    current = _as_float(weekly.get("currentValue")) if isinstance(weekly, dict) else None
    return compute_quota_spend(
        _float_snapshot_points(_extract_zai_weekly_used),
        current,
        window_hours,
        direction="increase",
        unit="tok",
        note="Z.AI weekly currentValue delta from local snapshots",
    )


def _extract_commandcode_monthly_remaining(obj: dict[str, Any]) -> float | None:
    wallet = _wallet_from_snapshot(obj, "commandcode")
    if not wallet:
        return None
    monthly = wallet.get("monthly")
    if isinstance(monthly, dict):
        val = _as_float(monthly.get("remaining_usd"))
        if val is not None:
            return val
    return _as_float(wallet.get("monthly_credits"))


def compute_commandcode_spend(
    probe: dict[str, Any] | None, window_hours: int
) -> dict[str, Any]:
    current = None
    if isinstance(probe, dict):
        monthly = probe.get("monthly")
        if isinstance(monthly, dict):
            current = _as_float(monthly.get("remaining_usd"))
        if current is None:
            current = _as_float(probe.get("monthly_credits"))
    return compute_quota_spend(
        _float_snapshot_points(_extract_commandcode_monthly_remaining),
        current,
        window_hours,
        direction="decrease",
        unit="$",
        note="Command Code monthly remaining credits delta from local snapshots",
    )


def _extract_kimi_weekly_used(obj: dict[str, Any]) -> float | None:
    wallet = _wallet_from_snapshot(obj, "kimi")
    if not wallet:
        return None
    weekly = wallet.get("weekly")
    if not isinstance(weekly, dict):
        return None
    return _as_float(weekly.get("used"))


def compute_kimi_spend(
    probe: dict[str, Any] | None, window_hours: int
) -> dict[str, Any]:
    weekly = (probe or {}).get("weekly") if isinstance(probe, dict) else None
    current = _as_float(weekly.get("used")) if isinstance(weekly, dict) else None
    return compute_quota_spend(
        _float_snapshot_points(_extract_kimi_weekly_used),
        current,
        window_hours,
        direction="increase",
        unit="req",
        note="Kimi weekly used delta from local snapshots",
    )


def _extract_opencode_monthly_used(obj: dict[str, Any]) -> float | None:
    wallet = _wallet_from_snapshot(obj, "opencode-go")
    if not wallet:
        return None
    monthly = wallet.get("monthly")
    if not isinstance(monthly, dict):
        return None
    used_usd = _as_float(monthly.get("used_usd"))
    if used_usd is not None:
        return used_usd
    return None


def compute_opencode_go_spend(
    probe: dict[str, Any] | None, window_hours: int
) -> dict[str, Any]:
    monthly = (probe or {}).get("monthly") if isinstance(probe, dict) else None
    current = None
    if isinstance(monthly, dict):
        current = _as_float(monthly.get("used_usd"))
    return compute_quota_spend(
        _float_snapshot_points(_extract_opencode_monthly_used),
        current,
        window_hours,
        direction="increase",
        unit="$",
        note="OpenCode Go monthly used_usd delta from local snapshots",
    )


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
        "spend_24h": compute_commandcode_spend(probe, USAGE_WINDOW_HOURS),
        "spend_7d": compute_commandcode_spend(probe, USAGE_WINDOW_7D_HOURS),
        "spend_series_7d": compute_commandcode_spend_series_7d(probe),
        "models": models_unavailable("Command Code billing API has no per-model breakdown"),
        "source": probe.get("source") or "commandcode-alpha-billing-credits",
        "via": probe.get("via"),
    }


def get_kimi_proxy() -> str | None:
    """HTTP CONNECT or SOCKS5/SOCKS5h for api.kimi.com (optional tw-msk egress)."""
    for name in ("KIMI_PROXY", "KIMI_CODE_PROXY"):
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return None


def get_kimi_api_key() -> str | None:
    """Env KIMI_API_KEY or KIMI_CODE_API_KEY (CodexBar / kimi-cli alias)."""
    for name in ("KIMI_API_KEY", "KIMI_CODE_API_KEY"):
        key = os.environ.get(name)
        if key and len(key.strip()) > 10:
            return key.strip()
    return None


def get_kimi_code_base_url() -> str:
    raw = os.environ.get("KIMI_CODE_BASE_URL", "").strip().rstrip("/")
    return raw or KIMI_CODE_DEFAULT_BASE_URL


def kimi_usages_url() -> str:
    base = get_kimi_code_base_url()
    if base.endswith(KIMI_CODE_USAGES_PATH):
        return base
    return base + KIMI_CODE_USAGES_PATH


def _kimi_reset_iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.replace(".", "", 1).isdigit():
            return _commandcode_reset_iso(text)
        try:
            ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return text
    return _commandcode_reset_iso(value)


def _kimi_window_minutes(window: Any) -> float | None:
    if not isinstance(window, dict):
        return None
    duration = _as_float(_pick(window, "duration"))
    if duration is None:
        return None
    unit = str(_pick(window, "timeUnit", "time_unit") or "").upper()
    if "SECOND" in unit:
        return duration / 60.0
    if "HOUR" in unit:
        return duration * 60.0
    if "DAY" in unit:
        return duration * 1440.0
    return duration


def _parse_kimi_quota(raw: Any, kind: str, label: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cap = _as_float(_pick(raw, "limit", "cap", "totalQuota", "total_quota"))
    used = _as_float(_pick(raw, "used", "usage"))
    remaining = _as_float(_pick(raw, "remaining"))
    if remaining is None and cap is not None and used is not None:
        remaining = max(0.0, cap - used)
    if used is None and cap is not None and remaining is not None:
        used = max(0.0, cap - remaining)
    if cap is None or cap <= 0:
        return None
    if used is None:
        used = 0.0
    if remaining is None:
        remaining = max(0.0, cap - used)
    used_pct = round((used / cap) * 100.0, 2)
    rem_pct = round(max(0.0, (remaining / cap) * 100.0), 2)
    reset_at = _kimi_reset_iso(_pick(raw, "resetTime", "reset_time", "reset_at", "resetAt"))
    name = _pick(raw, "name")
    summary = f"{rem_pct:.0f}% left ({label}) · {remaining:.0f} / {cap:.0f}"
    if isinstance(name, str) and name.strip():
        summary = f"{name.strip()} · {summary}"
    return {
        "kind": kind,
        "used": used,
        "cap": cap,
        "remaining": remaining,
        "used_percent": used_pct,
        "remaining_percent": rem_pct,
        "next_reset_at": reset_at,
        "name": name if isinstance(name, str) else None,
        "summary": summary,
    }


def _kimi_fresh_session() -> dict[str, Any]:
    return {
        "kind": "session",
        "used": 0.0,
        "cap": None,
        "remaining": None,
        "used_percent": 0.0,
        "remaining_percent": 100.0,
        "next_reset_at": None,
        "name": None,
        "summary": "100% left (5h) · window not started",
    }


def _kimi_plan_label(weekly_cap: float | None) -> str | None:
    if weekly_cap is None:
        return None
    for cap, label in KIMI_WEEKLY_PLANS.items():
        if abs(weekly_cap - cap) <= 0.05:
            return label
    return None


def _kimi_api_error(data: Any, err: str | None, st: int | None) -> str:
    if isinstance(data, dict):
        err_obj = data.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or err_obj.get("type")
            if msg:
                return f"usages API: {st} {msg}".strip()
        if isinstance(err_obj, str) and err_obj:
            return f"usages API: {st} {err_obj}".strip()
        code = data.get("code")
        if code:
            return f"usages API: {st} {code}".strip()
    return f"usages API: {st} {err or data}".strip()


def probe_kimi_usage() -> dict[str, Any]:
    """Fetch Kimi Coding weekly quota + rolling 5h window.

    Primary: GET https://api.kimi.com/coding/v1/usages (Bearer Kimi Code API key).
    Cookie GetUsages / Moonshot Open Platform are not used.
    """
    key = get_kimi_api_key()
    result: dict[str, Any] = {
        "provider": "kimi",
        "email": "kimi-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "kimi-coding-quota",
        "status": "error",
        "plan_label": None,
        "session": None,
        "weekly": None,
        "error": None,
        "source": "kimi-coding-v1-usages",
    }
    if not key:
        result["status"] = "manual"
        result["error"] = "KIMI_API_KEY not set"
        return result

    proxy = get_kimi_proxy()
    result["via"] = {
        "base_url": get_kimi_code_base_url(),
        "proxy": redact_proxy_url(proxy),
    }

    st, _hdrs, data, err = http_json(
        kimi_usages_url(),
        token=key,
        proxy=proxy,
        timeout=15.0,
    )
    if st != 200 or not isinstance(data, dict):
        result["error"] = _kimi_api_error(data, err, st)
        return result

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        payload = data
    usage_raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    weekly = _parse_kimi_quota(usage_raw, "weekly", "week")
    limits_raw = payload.get("limits")
    if not isinstance(limits_raw, list):
        limits_raw = []

    session = None
    saw_five_hour = False
    for item in limits_raw:
        if not isinstance(item, dict):
            continue
        minutes = _kimi_window_minutes(item.get("window"))
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else item
        parsed = _parse_kimi_quota(detail, "session", "5h")
        if minutes is not None and abs(minutes - 300.0) <= 0.5:
            saw_five_hour = True
            session = parsed or _kimi_fresh_session()
            break
        if session is None and parsed:
            session = parsed
    if session is None and saw_five_hour:
        session = _kimi_fresh_session()

    plan_label = _kimi_plan_label(weekly["cap"] if weekly else None)

    result["ok"] = True
    result["status"] = "active"
    result["plan_label"] = plan_label
    result["session"] = session
    result["weekly"] = weekly

    parts = []
    if weekly:
        parts.append(weekly["summary"])
    if session:
        parts.append(session["summary"])
    label = plan_label or "Kimi Coding"
    result["remaining_summary"] = f"{label} · " + " · ".join(parts) if parts else str(label)
    return result


def build_kimi_wallet(probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not probe:
        return None
    status = probe.get("status") or ("active" if probe.get("ok") else "error")
    return {
        "provider": "kimi",
        "email": "kimi-main",
        "name": "Kimi Coding",
        "kind": "kimi-coding-quota",
        "status": status,
        "ok": bool(probe.get("ok")),
        "plan_label": probe.get("plan_label"),
        "session": probe.get("session") or {},
        "weekly": probe.get("weekly") or {},
        "remaining_summary": probe.get("remaining_summary") or "",
        "error": probe.get("error"),
        "probed_at": probe.get("probed_at"),
        "spend_24h": compute_kimi_spend(probe, USAGE_WINDOW_HOURS),
        "spend_7d": compute_kimi_spend(probe, USAGE_WINDOW_7D_HOURS),
        "spend_series_7d": compute_kimi_spend_series_7d(probe),
        "models": models_unavailable("Kimi /coding/v1/usages has no per-model breakdown"),
        "source": probe.get("source") or "kimi-coding-v1-usages",
        "via": probe.get("via"),
    }


def get_opencode_go_proxy() -> str | None:
    """HTTP CONNECT or SOCKS5/SOCKS5h for opencode.ai (optional tw-msk egress)."""
    for name in ("OPENCODE_GO_PROXY", "OPENCODE_PROXY"):
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return None


def get_opencode_go_api_key() -> str | None:
    """Env OPENCODE_GO_API_KEY or OPENCODE_API_KEY (Hermes / pi-go-bars alias)."""
    for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"):
        key = os.environ.get(name)
        if key and len(key.strip()) > 10:
            return key.strip()
    return None


def get_opencode_go_base_url() -> str:
    raw = os.environ.get("OPENCODE_GO_BASE_URL", "").strip().rstrip("/")
    return raw or OPENCODE_GO_DEFAULT_BASE_URL


def opencode_go_usage_url() -> str:
    base = get_opencode_go_base_url()
    if base.endswith(OPENCODE_GO_USAGE_PATH):
        return base
    return base + OPENCODE_GO_USAGE_PATH


def _opencode_go_reset_iso(raw: dict[str, Any]) -> str | None:
    reset_at = _kimi_reset_iso(_pick(raw, "resetsAt", "resets_at", "resetAt", "reset_at"))
    if reset_at:
        return reset_at
    reset_in = _as_float(_pick(raw, "resetInSec", "reset_in_sec", "resets_in_seconds", "resetInSeconds"))
    if reset_in is None or reset_in < 0:
        return None
    ts = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + reset_in, timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_opencode_go_window(raw: Any, kind: str, label: str) -> dict[str, Any] | None:
    """Parse one Go window. Wire `percent` is used %, remaining = 100 - used."""
    if not isinstance(raw, dict):
        return None
    used_pct = _as_float(_pick(raw, "percent", "usagePercent", "usage_percent", "used_percent"))
    rem_pct = _as_float(_pick(raw, "remaining_percent", "remainingPercent"))
    if used_pct is None and rem_pct is None:
        return None
    if used_pct is None and rem_pct is not None:
        used_pct = round(max(0.0, 100.0 - rem_pct), 2)
    if rem_pct is None and used_pct is not None:
        rem_pct = round(max(0.0, 100.0 - used_pct), 2)
    status = _pick(raw, "status")
    if isinstance(status, str):
        status = status.strip().lower() or None
    else:
        status = None
    if status == "rate-limited":
        used_pct = 100.0 if used_pct is None else used_pct
        rem_pct = 0.0
    cap = OPENCODE_GO_CAPS.get(kind)
    remaining_usd = round(cap * rem_pct / 100.0, 4) if cap is not None and rem_pct is not None else None
    used_usd = round(cap * used_pct / 100.0, 4) if cap is not None and used_pct is not None else None
    reset_at = _opencode_go_reset_iso(raw)
    headline_pct = rem_pct if rem_pct is not None else 0.0
    summary = f"{headline_pct:.0f}% left ({label})"
    if remaining_usd is not None and cap is not None:
        summary += f" · ${remaining_usd:.2f} / ${cap:.2f}"
    return {
        "kind": kind,
        "status": status,
        "used_percent": round(used_pct, 2) if used_pct is not None else None,
        "remaining_percent": round(rem_pct, 2) if rem_pct is not None else None,
        "cap": cap,
        "remaining_usd": remaining_usd,
        "used_usd": used_usd,
        "next_reset_at": reset_at,
        "summary": summary,
    }


def _unwrap_opencode_go_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    usage = data.get("usage")
    if isinstance(usage, dict):
        return usage
    inner = data.get("data")
    if isinstance(inner, dict):
        nested = inner.get("usage")
        if isinstance(nested, dict):
            return nested
        if any(
            key in inner
            for key in ("rolling", "weekly", "monthly", "rollingUsage", "weeklyUsage", "monthlyUsage")
        ):
            return inner
    if any(
        key in data
        for key in ("rolling", "weekly", "monthly", "rollingUsage", "weeklyUsage", "monthlyUsage")
    ):
        return data
    return None


def _opencode_go_api_error(data: Any, err: str | None, st: int | None) -> str:
    if isinstance(data, dict):
        err_obj = data.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or err_obj.get("type")
            if msg:
                return f"usage API: {st} {msg}".strip()
        if isinstance(err_obj, str) and err_obj:
            return f"usage API: {st} {err_obj}".strip()
        if data.get("type") == "error" and isinstance(data.get("message"), str):
            return f"usage API: {st} {data['message']}".strip()
    if isinstance(data, str) and data.lstrip().startswith("<"):
        return f"usage API: {st} HTML (not JSON)".strip()
    return f"usage API: {st} {err or data}".strip()


def probe_opencode_go_usage() -> dict[str, Any]:
    """Fetch OpenCode Go rolling / weekly / monthly windows.

    Primary: GET https://opencode.ai/zen/go/v1/usage (Bearer Go API key).
    Cookie workspace scrape / Zen balance are not used.
    """
    key = get_opencode_go_api_key()
    result: dict[str, Any] = {
        "provider": "opencode-go",
        "email": "opencode-go-main",
        "probed_at": now_iso(),
        "ok": False,
        "kind": "opencode-go-quota",
        "status": "error",
        "plan_label": "Go",
        "session": None,
        "weekly": None,
        "monthly": None,
        "error": None,
        "source": "opencode-go-zen-v1-usage",
    }
    if not key:
        result["status"] = "manual"
        result["error"] = "OPENCODE_GO_API_KEY not set"
        return result

    proxy = get_opencode_go_proxy()
    result["via"] = {
        "base_url": get_opencode_go_base_url(),
        "proxy": redact_proxy_url(proxy),
    }

    st, _hdrs, data, err = http_json(
        opencode_go_usage_url(),
        token=key,
        proxy=proxy,
        timeout=15.0,
    )
    if st != 200 or not isinstance(data, dict):
        result["error"] = _opencode_go_api_error(data, err, st)
        return result
    if data.get("type") == "error" or data.get("success") is False:
        result["error"] = _opencode_go_api_error(data, err, st)
        return result

    payload = _unwrap_opencode_go_payload(data)
    if not payload:
        result["error"] = "usage API: missing usage windows"
        return result

    session = _parse_opencode_go_window(
        _pick(payload, "rolling", "rollingUsage", "rolling_usage", "fiveHour", "five_hour"),
        "session",
        "5h",
    )
    weekly = _parse_opencode_go_window(
        _pick(payload, "weekly", "weeklyUsage", "weekly_usage"),
        "weekly",
        "week",
    )
    monthly = _parse_opencode_go_window(
        _pick(payload, "monthly", "monthlyUsage", "monthly_usage"),
        "monthly",
        "month",
    )
    if session is None and weekly is None and monthly is None:
        result["error"] = "usage API: missing usage windows"
        return result

    result["ok"] = True
    result["status"] = "active"
    result["session"] = session
    result["weekly"] = weekly
    result["monthly"] = monthly

    parts = []
    if monthly:
        parts.append(monthly["summary"])
    if session:
        parts.append(session["summary"])
    if weekly:
        parts.append(weekly["summary"])
    result["remaining_summary"] = "Go · " + " · ".join(parts) if parts else "Go"
    return result


def build_opencode_go_wallet(probe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not probe:
        return None
    status = probe.get("status") or ("active" if probe.get("ok") else "error")
    return {
        "provider": "opencode-go",
        "email": "opencode-go-main",
        "name": "OpenCode Go",
        "kind": "opencode-go-quota",
        "status": status,
        "ok": bool(probe.get("ok")),
        "plan_label": probe.get("plan_label") or "Go",
        "session": probe.get("session") or {},
        "weekly": probe.get("weekly") or {},
        "monthly": probe.get("monthly") or {},
        "remaining_summary": probe.get("remaining_summary") or "",
        "error": probe.get("error"),
        "probed_at": probe.get("probed_at"),
        "spend_24h": compute_opencode_go_spend(probe, USAGE_WINDOW_HOURS),
        "spend_7d": compute_opencode_go_spend(probe, USAGE_WINDOW_7D_HOURS),
        "spend_series_7d": compute_opencode_go_spend_series_7d(probe),
        "models": models_unavailable("OpenCode Go /zen/go/v1/usage has no per-model breakdown"),
        "source": probe.get("source") or "opencode-go-zen-v1-usage",
        "via": probe.get("via"),
    }


def _probe_cache_stale(
    cache: dict[str, Any],
    required_keys: tuple[str, ...] | list[str] | None = None,
) -> bool:
    keys = WALLET_PROBE_KEYS if required_keys is None else tuple(required_keys)
    acc = (cache or {}).get("accounts") or {}
    if not all(k in acc for k in keys):
        return True
    updated = cache.get("updated_at")
    if not updated:
        return True
    try:
        ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() > QUOTA_PROBE_SECONDS
    except Exception:
        return True


_PROVIDER_PROBE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("deepseek", "probe_deepseek_balance", "deepseek-balance-probe"),
    ("openrouter", "probe_openrouter_wallet", "openrouter-wallet-probe"),
    ("zai", "probe_zai_quota", "zai-quota-probe"),
    ("commandcode", "probe_commandcode_credits", "commandcode-credits-probe"),
    ("kimi", "probe_kimi_usage", "kimi-usage-probe"),
    ("opencode-go", "probe_opencode_go_usage", "opencode-go-usage-probe"),
)

_PROVIDER_NOTES: tuple[tuple[str, str], ...] = (
    (
        "deepseek",
        "DeepSeek wallet: balance only; 24h/7d spend from local snapshots (no usage history API); no per-model breakdown.",
    ),
    (
        "openrouter",
        "OpenRouter wallet: account credits + rolling 24h/7d from snapshots; per-model from GET /api/v1/activity (management key).",
    ),
    (
        "zai",
        "Z.AI wallet: short session + weekly token limits + MCP; 24h/7d from weekly currentValue snapshots; no per-model.",
    ),
    (
        "commandcode",
        "Command Code wallet: monthly remaining credits + 5h/weekly rolling windows; 24h/7d from monthly remaining snapshots; no per-model.",
    ),
    (
        "kimi",
        "Kimi Coding wallet: weekly request quota + rolling 5h window; 24h/7d from weekly.used snapshots; no per-model.",
    ),
    (
        "opencode-go",
        "OpenCode Go wallet: monthly remaining + 5h/weekly windows from /zen/go/v1/usage; 24h/7d from monthly used_usd snapshots; no per-model.",
    ),
)


def _wallet_builders() -> dict[str, Any]:
    return {
        "deepseek": build_deepseek_wallet,
        "openrouter": build_openrouter_wallet,
        "zai": build_zai_wallet,
        "commandcode": build_commandcode_wallet,
        "kimi": build_kimi_wallet,
        "opencode-go": build_opencode_go_wallet,
    }


def collect_state(force_quota: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    enabled = get_enabled_providers()
    enabled_set = set(enabled)
    required_keys = tuple(f"{name}-main" for name in enabled)
    builders = _wallet_builders()
    missing = [name for name in KNOWN_PROVIDERS if name not in builders]
    extra = [name for name in builders if name not in KNOWN_PROVIDERS]
    if missing or extra:
        raise RuntimeError(f"provider builder map mismatch: missing={missing} extra={extra}")
    probe_names = tuple(spec[0] for spec in _PROVIDER_PROBE_SPECS)
    if probe_names != KNOWN_PROVIDERS:
        raise RuntimeError(f"provider probe spec mismatch: {probe_names}")

    with _quota_lock:
        global _quota_cache
        need_probe = force_quota or _probe_cache_stale(_quota_cache, required_keys)
        if need_probe:
            probed: dict[str, Any] = {}
            for name, fn_name, err_label in _PROVIDER_PROBE_SPECS:
                if name not in enabled_set:
                    continue
                fn = globals()[fn_name]
                try:
                    result = fn()
                    if result is not None:
                        probed[f"{name}-main"] = result
                except Exception as e:
                    errors.append(f"{err_label}: {e}")
            _quota_cache = {
                "updated_at": now_iso(),
                "accounts": probed,
            }
            save_json(QUOTA_CACHE_PATH, _quota_cache)
        quota_accounts = dict((_quota_cache or {}).get("accounts") or {})

    maybe_export_openrouter_key_models()

    wallets: dict[str, Any] = {}
    for name in enabled:
        builder = builders.get(name)
        if builder is None:
            raise RuntimeError(f"unknown provider {name}")
        wallet = builder(quota_accounts.get(f"{name}-main"))
        if wallet:
            wallets[name] = wallet

    notes = [text for name, text in _PROVIDER_NOTES if name in enabled_set]
    notes.append(
        f"Usage windows: last {USAGE_WINDOW_HOURS}h and {USAGE_WINDOW_7D_HOURS}h (7d)."
    )

    return {
        "updated_at": now_iso(),
        "site_title": get_site_title(),
        "enabled_providers": list(enabled),
        "display_tz": get_display_tz(),
        "display_tz_label": display_tz_label(),
        "hide_partial_spend_chips": hide_partial_spend_chips(),
        "openrouter_key_only": openrouter_key_only(),
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
        "notes": notes,
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
    # Do not block uvicorn bind on network probes (DeepSeek/OpenRouter/Z.AI/Command Code/Kimi/OpenCode Go).
    def _bg() -> None:
        try:
            refresh_once(force_quota=True)
        except Exception as e:
            with _lock:
                _state["errors"] = list(_state.get("errors") or []) + [f"startup-refresh: {e}"]
                _state["updated_at"] = now_iso()
    threading.Thread(target=_bg, name="usage-startup-refresh", daemon=True).start()
    threading.Thread(target=poller, name="usage-poller", daemon=True).start()


def _pace_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_pace_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    parsed = parse_snapshot_ts(value)
    if parsed is None:
        return None
    return datetime.fromtimestamp(parsed[0], timezone.utc)


def compute_pace_norm_percent(
    next_reset_at: datetime | str,
    window_minutes: float,
    now: datetime,
) -> float:
    """Elapsed fraction of the window from next_reset_at, clamped 0..100."""
    reset_dt = parse_pace_datetime(next_reset_at)
    now_dt = parse_pace_datetime(now)
    if reset_dt is None or now_dt is None or window_minutes <= 0:
        return 0.0
    remaining_minutes = (reset_dt - now_dt).total_seconds() / 60.0
    elapsed_minutes = window_minutes - remaining_minutes
    pct = (elapsed_minutes / window_minutes) * 100.0
    return max(0.0, min(100.0, pct))


def classify_pace(delta_pp: float) -> str:
    if delta_pp <= PACE_OK_DELTA_PP:
        return "ok"
    if delta_pp <= PACE_WARN_DELTA_PP:
        return "warn"
    return "danger"


def compute_pace_cooldown_minutes(delta_pp: float, window_minutes: float) -> float:
    if delta_pp > PACE_OK_DELTA_PP:
        return delta_pp * window_minutes / 100.0
    return 0.0


def compute_pace_data_age_seconds(probed_at: Any, now: datetime) -> int | None:
    probed_dt = parse_pace_datetime(probed_at)
    now_dt = parse_pace_datetime(now)
    if probed_dt is None or now_dt is None:
        return None
    return max(0, int(round((now_dt - probed_dt).total_seconds())))


def compute_pace_lane(
    window: str,
    window_minutes: int,
    window_data: Any,
    now: datetime,
    probed_at: Any = None,
) -> dict[str, Any] | None:
    if not isinstance(window_data, dict):
        return None
    used_percent = _as_float(window_data.get("used_percent"))
    reset_dt = parse_pace_datetime(window_data.get("next_reset_at"))
    if used_percent is None or reset_dt is None:
        return None
    now_dt = parse_pace_datetime(now)
    if now_dt is None:
        return None
    norm_percent = compute_pace_norm_percent(reset_dt, window_minutes, now_dt)
    delta_pp = used_percent - norm_percent
    return {
        "window": window,
        "window_minutes": window_minutes,
        "used_percent": used_percent,
        "norm_percent": round(norm_percent, 4),
        "delta_pp": round(delta_pp, 4),
        "pace": classify_pace(delta_pp),
        "cooldown_minutes": round(
            compute_pace_cooldown_minutes(delta_pp, window_minutes), 4
        ),
        "reset_at": _pace_iso(reset_dt),
        "data_age_seconds": compute_pace_data_age_seconds(probed_at, now_dt),
    }


def build_pace_payload(
    quota_cache: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_dt = parse_pace_datetime(now) if now is not None else datetime.now(timezone.utc)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    accounts_raw = quota_cache.get("accounts") if isinstance(quota_cache, dict) else {}
    if not isinstance(accounts_raw, dict):
        accounts_raw = {}
    ordered_keys: list[str] = []
    for key in WALLET_PROBE_KEYS:
        if key in accounts_raw:
            ordered_keys.append(key)
    for key in accounts_raw:
        if key not in ordered_keys:
            ordered_keys.append(str(key))

    accounts_out: list[dict[str, Any]] = []
    no_window: list[str] = []
    for key in ordered_keys:
        acc = accounts_raw.get(key)
        if not isinstance(acc, dict):
            no_window.append(str(key))
            continue
        probed_at = acc.get("probed_at")
        lanes: list[dict[str, Any]] = []
        for cache_key, window_label, minutes in PACE_WINDOW_SPECS:
            lane = compute_pace_lane(
                window_label,
                minutes,
                acc.get(cache_key),
                now_dt,
                probed_at,
            )
            if lane is not None:
                lanes.append(lane)
        if lanes:
            accounts_out.append({"provider": str(key), "lanes": lanes})
        else:
            no_window.append(str(key))
    return {
        "accounts": accounts_out,
        "no_window": no_window,
        "server_now": _pace_iso(now_dt),
    }


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
    enabled = get_enabled_providers()
    enabled_set = set(enabled)
    with _lock:
        data = json.loads(json.dumps(_state))
    data["site_title"] = get_site_title()
    data["enabled_providers"] = list(enabled)
    data["display_tz"] = get_display_tz()
    data["display_tz_label"] = display_tz_label()
    data["hide_partial_spend_chips"] = hide_partial_spend_chips()
    data["openrouter_key_only"] = openrouter_key_only()
    wallets = data.get("wallets") if isinstance(data.get("wallets"), dict) else {}
    data["wallets"] = {key: wallets[key] for key in enabled if key in wallets}
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    wallets_meta = providers.get("wallets") if isinstance(providers.get("wallets"), dict) else None
    if wallets_meta is not None:
        wallets_meta["keys"] = list(data["wallets"].keys())
        providers["wallets"] = wallets_meta
        data["providers"] = providers
    notes = data.get("notes")
    if isinstance(notes, list) and enabled_set != set(KNOWN_PROVIDERS):
        keep = {text for name, text in _PROVIDER_NOTES if name in enabled_set}
        data["notes"] = [
            note
            for note in notes
            if note in keep or str(note).startswith("Usage windows:")
        ]
    return data


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


@app.get("/api/pace")
def pace() -> dict[str, Any]:
    with _quota_lock:
        cache = json.loads(json.dumps(_quota_cache))
    return build_pace_payload(cache)


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    try:
        return refresh_once(force_quota=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def index() -> HTMLResponse:
    path = STATIC_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="index.html missing")
    text = path.read_text(encoding="utf-8")
    title = html_lib.escape(get_site_title(), quote=False)
    text = text.replace(
        "<title>Мои подписки · raclaw</title>",
        f"<title>{title} · raclaw</title>",
        1,
    )
    text = text.replace("<h1>Мои подписки</h1>", f"<h1>{title}</h1>", 1)
    return HTMLResponse(text)


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

