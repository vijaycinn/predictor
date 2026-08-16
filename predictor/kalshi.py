"""Kalshi ingestion: public market data + RSA-PSS signed auth.

Credential env vars (read at call time, never logged):
  KALSHI_API_KEY       — API key ID (UUID, from Kalshi Account & security > API Keys)
  KALSHI_PRIVATE_KEY   — RSA private key PEM (downloaded .key file content)

Public market data endpoints work without credentials. Authenticated endpoints
(portfolio, orders) require both vars and are only used by the live executor.
"""
from __future__ import annotations

import base64
import json
import math
import os
import time
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://external-api.kalshi.com/trade-api/v2"
TIMEOUT = 15


class KalshiError(Exception):
    pass


class _NotFound(Exception):
    """Internal marker for 404 (permanent, no retry)."""


class KalshiAuthError(KalshiError):
    pass


# Kalshi human category labels -> predictor canonical categories
CATEGORY_MAP: dict[str, list[str]] = {
    "crypto": ["crypto", "digital assets", "cryptocurrency"],
    "politics": ["politics", "elections", "world", "congress", "judicial",
                 "international affairs", "governance", "supreme court", "diplomacy"],
    "sports": ["sports", "football", "basketball", "baseball", "hockey", "soccer",
               "golf", "tennis", "mma", "boxing", "racing", "cricket", "olympics"],
    "economics": ["economics", "financials", "markets", "climate and weather",
                  "climate", "weather", "inflation", "fed", "rates", "macro",
                  "unemployment", "gdp", "interest rate"],
}


def _env_key() -> str | None:
    return os.environ.get("KALSHI_API_KEY") or None


def _env_priv() -> str | None:
    return os.environ.get("KALSHI_PRIVATE_KEY") or None


def auth_ready() -> dict:
    """Report which Kalshi credential vars are present (names only)."""
    return {
        "KALSHI_API_KEY": bool(_env_key()),
        "KALSHI_PRIVATE_KEY": bool(_env_priv()),
    }


def _load_private_key():
    pem = _env_priv()
    if not pem:
        raise KalshiAuthError("KALSHI_PRIVATE_KEY env var missing (RSA PEM). Add it in Railway.")
    pem = pem.replace("\\n", "\n").strip()
    if "BEGIN" not in pem:
        raise KalshiAuthError("KALSHI_PRIVATE_KEY does not look like PEM (missing BEGIN header).")
    try:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception as e:
        raise KalshiAuthError(f"KALSHI_PRIVATE_KEY unparseable: {e}") from e


def auth_headers(method: str, path: str) -> dict:
    """Kalshi auth headers: KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP.

    Signature: RSA-PSS/SHA256 over timestamp + METHOD + path (no query string).
    """
    key = _env_key()
    priv = _load_private_key()
    if not key:
        raise KalshiAuthError("KALSHI_API_KEY env var missing. Add it in Railway.")
    ts = str(int(time.time() * 1000))
    message = f"{ts}{method}{path}".encode("utf-8")
    sig = priv.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def get_json(path: str, params: dict | None = None, auth: bool = False, retries: int = 5) -> Any:
    # Kalshi requires signing the FULL path from API root incl /trade-api/v2
    sign_path = f"/trade-api/v2{path}" if auth and not path.startswith("/trade-api") else path
    headers = auth_headers("GET", sign_path) if auth else {}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=headers, timeout=TIMEOUT)
            if r.status_code in (401, 429, 500, 502, 503):
                # Kalshi edge intermittently rejects valid signatures in bursts;
                # retry with backoff before declaring auth failure.
                raise requests.RequestException(f"HTTP {r.status_code}")
            if r.status_code == 404:
                # permanent — bad ticker/path. HTTPError subclasses
                # RequestException so must raise OUTSIDE the retry except.
                raise _NotFound(path)
            r.raise_for_status()
            return r.json()
        except _NotFound as e:
            raise KalshiError(f"Kalshi {path} not found (404)") from e
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * (2 ** attempt))
    if isinstance(last_err, requests.RequestException) and "401" in str(last_err):
        raise KalshiAuthError("Kalshi auth rejected (401) after retries. Check KALSHI_API_KEY / KALSHI_PRIVATE_KEY.")
    raise KalshiError(f"Kalshi {path} failed after {retries} attempts: {last_err}") from last_err


def _auth_request(method: str, path: str, json_body: dict | None = None, retries: int = 5) -> Any:
    """Signed authenticated request (order placement, cancellation, portfolio)."""
    sign_path = f"/trade-api/v2{path}" if not path.startswith("/trade-api") else path
    headers = auth_headers(method, sign_path)
    headers["Content-Type"] = "application/json"
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.request(method, f"{BASE}{path}", json=json_body, headers=headers, timeout=TIMEOUT)
            if r.status_code in (401, 429, 500, 502, 503):
                raise requests.RequestException(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                raise KalshiError(f"Kalshi {method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.text else {}
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * (2 ** attempt))
    if isinstance(last_err, requests.RequestException) and "401" in str(last_err):
        raise KalshiAuthError("Kalshi auth rejected (401) after retries. Check KALSHI_API_KEY / KALSHI_PRIVATE_KEY.")
    raise KalshiError(f"Kalshi {method} {path} failed after {retries} attempts: {last_err}") from last_err


def place_order(ticker: str, side: str, count: float, price: float, reduce_only: bool = False,
                hours_to_expiry: float = 0.0, max_lifetime_hours: float = 1.0) -> dict:
    """Place a limit order. side: 'YES' -> bid, 'NO' -> ask.
    V2 endpoint: POST /portfolio/events/orders (legacy /portfolio/orders
    deprecated 2026-05-06). Prices are fixed-point dollar strings.

    reduce_only sells (position exits) use IOC — Kalshi rejects reduce_only
    with GTC ('reduce_only can only be used with IoC orders', hit live
    2026-08-02). Exits fill at or better than price immediately; no TTL needed.

    Order lifetime (VJ rules):
      - DEFAULT 1 HOUR (VJ 2026-08-02): resting orders default to 1h expiry
        unless VJ explicitly overrides — stale resting orders are dead weight
      - max 24h absolute cap, never longer
      - leave >= 20% of the event's remaining time: lifetime <= 0.8 * hours_to_expiry
        (critical for short-timed events — a 24h order on a 5h event is invalid)
    """
    import uuid
    from datetime import datetime, timezone
    # HARD RULE (VJ 2026-08-02): LIMIT ORDERS ONLY. This function places a limit
    # order and refuses to construct a market order. price must be a valid
    # 0-1 tick; None/out-of-range raises instead of degrading to market.
    if price is None or not (0 < float(price) < 1):
        raise ValueError(f"LIMIT-ONLY enforcement: place_order requires a limit price, got {price!r}")
    # Normalize side so lowercase/aliases can never invert the order (2026-08-03 incident:
    # side="yes" failed `== "YES"` and built a SELL. Valid: YES/NO, buy/sell, bid/ask.)
    side_map = {"YES": "YES", "NO": "NO", "BUY": "YES", "SELL": "NO", "BID": "YES", "ASK": "NO"}
    try:
        side = side_map[side.upper().strip()]
    except (AttributeError, KeyError):
        raise ValueError(f"place_order: invalid side {side!r}, expected YES/NO/buy/sell/bid/ask")
    # Kalshi tick size is 1c for these markets; off-tick prices are rejected
    price_tick = round(price * 100) / 100.0
    lifetime_h = max_lifetime_hours
    if hours_to_expiry and hours_to_expiry > 0:
        # at least 20% of the event's remaining time must survive the order
        lifetime_h = min(lifetime_h, 0.8 * hours_to_expiry)
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": "bid" if side == "YES" else "ask",
        "count": f"{count:.2f}",
        "price": f"{price_tick:.4f}",
        "time_in_force": "immediate_or_cancel" if reduce_only else "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "reduce_only": reduce_only,
    }
    if not reduce_only:
        # IOC rejects expiration timestamp (Kalshi: Cannot_specify_both_IoC_and_expiration_timestamp, hit 2026-08-02)
        body["expiration_time"] = int(datetime.now(timezone.utc).timestamp() + lifetime_h * 3600)
    return _auth_request("POST", "/portfolio/events/orders", json_body=body)


def get_orderbook_full(ticker: str) -> dict:
    """FULL orderbook_fp for a market: {'yes_dollars': [[price,size],...],
    'no_dollars': [[price,size],...]} both ASCENDING, all levels.
    CRITICAL (VJ 2026-08-05): top-10 snapshots truncate the ladder and hide
    the real wall (Ribecai: top-10 showed 0.76, full ladder wall at 0.65).
    Always use this for wall/density computations."""
    d = get_json(f"/markets/{ticker}/orderbook")
    return (d or {}).get("orderbook_fp") or {}


def get_orders(status: str | None = None, ticker: str | None = None, limit: int = 200) -> list[dict]:
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    if ticker:
        params["ticker"] = ticker
    d = get_json("/portfolio/orders", params, auth=True)
    return d.get("orders") or []


def get_order(order_id: str) -> dict:
    d = get_json(f"/portfolio/orders/{order_id}", auth=True)
    return (d or {}).get("order") or {}


def cancel_order(order_id: str) -> dict:
    return _auth_request("DELETE", f"/portfolio/events/orders/{order_id}")


def get_positions(limit: int = 200) -> list[dict]:
    d = get_json("/portfolio/positions", {"limit": limit}, auth=True)
    return d.get("market_positions") or d.get("positions") or []


def get_fills(limit: int = 200) -> list[dict]:
    d = get_json("/portfolio/fills", {"limit": limit}, auth=True)
    return d.get("fills") or []


def get_balance() -> dict:
    return get_json("/portfolio/balance", auth=True)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _canonical_category(label: str | None) -> str:
    label = (label or "").lower()
    for canon, keywords in CATEGORY_MAP.items():
        if any(k in label for k in keywords):
            return canon
    return "other"


def _event_category_map() -> dict[str, str]:
    """event_ticker -> canonical category. Cached 1h (event categories are stable;
    paginated /events is rate-limit heavy)."""
    from pathlib import Path
    cache_path = Path(__file__).resolve().parent.parent / "data" / "kalshi_events_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        if cache_path.exists() and now - cache_path.stat().st_mtime < 3600:
            return json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        pass

    out: dict[str, str] = {}
    cursor = None
    while True:
        params = {"limit": 200, "status": "open"}  # /events caps at 200/page
        if cursor:
            params["cursor"] = cursor
        d = get_json("/events", params)
        for e in d.get("events") or []:
            out[e.get("event_ticker")] = _canonical_category(e.get("category"))
        cursor = d.get("cursor")
        if not cursor:
            break
    try:
        cache_path.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def discover_markets(cfg: dict, limit: int | None = None) -> list[dict]:
    """Open binary Kalshi markets, MVE combo junk excluded, volume-gated.

    Scan gates: cfg.kalshi.scan overrides cfg.scan (Kalshi volumes are ~10x
    smaller than Polymarket, so Polymarket-tuned gates would starve it).
    """
    base_scan = dict(cfg.get("scan", {}))
    base_scan.update(cfg.get("kalshi", {}).get("scan") or {})
    scan = base_scan
    limit = limit or scan.get("max_markets", 40)
    cats = set(scan.get("categories", []))
    min_vol = scan.get("min_volume_usd", 0)
    min_24h = scan.get("min_24h_volume", 0)

    ev_cats = _event_category_map()
    out: list[dict] = []
    cursor = None
    while len(out) < limit:
        params = {"limit": 1000, "status": "open", "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        d = get_json("/markets", params)
        ms = d.get("markets") or []
        if not ms:
            break
        for m in ms:
            if m.get("market_type") != "binary":
                continue
            vol = _to_float(m.get("volume_fp"))
            price = _to_float(m.get("last_price_dollars"))
            if price <= 0:
                price = _to_float(m.get("yes_bid_dollars"))
            vol_usd = vol * max(price, 0.001)
            vol_24h_usd = _to_float(m.get("volume_24h_fp")) * max(price, 0.001)
            if vol_usd < min_vol or vol_24h_usd < min_24h:
                continue
            canon = ev_cats.get(m.get("event_ticker"), "other")
            if cats and canon not in cats:
                continue
            nm = normalize_market(m)
            nm["category"] = canon
            out.append(nm)
            if len(out) >= limit:
                break
        cursor = d.get("cursor")
        if not cursor:
            break
    return out[:limit]


def normalize_market(m: dict) -> dict:
    """Kalshi market -> predictor market dict. condition_id = ticker."""
    yes_bid = _to_float(m.get("yes_bid_dollars"))
    no_bid = _to_float(m.get("no_bid_dollars"))
    yes_ask = _to_float(m.get("yes_ask_dollars"))
    ticker = m.get("ticker")
    return {
        "condition_id": ticker,
        "question": m.get("title") or m.get("yes_sub_title") or ticker,
        "slug": ticker,
        "category": _canonical_category(m.get("series_ticker")),
        "event_id": m.get("event_ticker"),
        "end_date": m.get("close_time") or m.get("expiration_time"),
        "created_at": m.get("created_time"),
        "volume": _to_float(m.get("volume_fp")),
        "liquidity": _to_float(m.get("liquidity_dollars")),
        "open_interest": _to_float(m.get("open_interest_fp")),
        "outcomes": ["Yes", "No"],
        "outcome_prices": [yes_bid, 1.0 - yes_bid],
        "clob_token_ids": [ticker, ticker],  # Kalshi has no token ids; ticker doubles
        "active": m.get("status") == "open",
        "closed": m.get("status") in ("closed", "settled", "finalized"),
        "status": m.get("status"),
        "result": m.get("result"),  # "yes"/"no" once settled/finalized (weekly_review relies on it)
        "market_type": "binary",
        "fees_enabled": False,  # Kalshi currently zero trading fees
        "taker_base_fee": 0.0,
        "maker_base_fee": 0.0,
        "last_price_dollars": _to_float(m.get("last_price_dollars")),
    }


def fetch_orderbook(ticker: str) -> dict:
    """Orderbook: yes/no bids only (binary equivalence derives asks).
    Full ladders included (bid_ladder/ask_ladder) for maker depth-aware
    limit pricing (VJ 2026-08-02)."""
    if not ticker:
        return {}
    d = get_json(f"/markets/{ticker}/orderbook")
    fp = (d or {}).get("orderbook_fp") or {}
    yes_bids = fp.get("yes_dollars") or []   # [[price, size], ...] ascending
    no_bids = fp.get("no_dollars") or []
    best_bid = _to_float(yes_bids[-1][0]) if yes_bids else None
    best_no_bid = _to_float(no_bids[-1][0]) if no_bids else None
    best_ask = (1.0 - best_no_bid) if best_no_bid is not None else None
    def depth(levels, n=5):
        return sum(_to_float(l[1]) for l in levels[-n:])
    def ladder(levels):
        return [[_to_float(l[0]), _to_float(l[1])] for l in levels]
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_depth": depth(yes_bids),
        "ask_depth": depth(no_bids),
        "top_bid_size": _to_float(yes_bids[-1][1]) if yes_bids else 0.0,
        "top_ask_size": _to_float(no_bids[-1][1]) if no_bids else 0.0,
        "bid_ladder": ladder(yes_bids),
        "ask_ladder": ladder(no_bids),
        "last_trade_price": None,
        "min_order_size": 1.0,
        "tick_size": 0.01,
    }


def fetch_price_history(ticker: str, interval: str = "1w", fidelity: int = 168) -> list[dict]:
    """Hourly candlesticks -> [{t, p}]. interval ignored (hourly granularity)."""
    if not ticker:
        return []
    series = ticker.split("-")[0] if ticker else ""
    now = int(time.time())
    start = now - fidelity * 3600
    try:
        d = get_json(f"/series/{series}/markets/{ticker}/candlesticks",
                     {"period_interval": 60, "start_ts": start, "end_ts": now})
    except requests.RequestException as e:
        raise KalshiError(f"Kalshi candlesticks failed: {e}") from e
    out = []
    for c in (d.get("candlesticks") or []):
        p = (c.get("price") or {}).get("close_dollars")
        if p is None:
            continue
        out.append({"t": c.get("end_period_ts"), "p": _to_float(p)})
    return out


def fetch_recent_trades(ticker: str, limit: int = 25) -> list[dict]:
    if not ticker:
        return []
    try:
        d = get_json("/markets/trades", {"ticker": ticker, "limit": limit})
    except requests.RequestException as e:
        raise KalshiError(f"Kalshi trades failed: {e}") from e
    out = []
    for t in (d.get("trades") or []):
        # taker_book_side: ask = aggressor bought, bid = aggressor sold
        side = "BUY" if t.get("taker_book_side") == "ask" else "SELL"
        out.append({
            "side": side,
            "size": _to_float(t.get("count_fp")),
            "price": _to_float(t.get("yes_price_dollars")),
            "timestamp": int(time.mktime(time.strptime(t["created_time"][:19], "%Y-%m-%dT%H:%M:%S"))),
        })
    return out


def fetch_open_interest(ticker: str) -> float:
    """OI is in market list fields; hit single-market endpoint as fallback."""
    try:
        d = get_json(f"/markets/{ticker}")
        return _to_float(((d or {}).get("market") or {}).get("open_interest_fp"))
    except Exception:
        return 0.0


def fetch_market_by_id(ticker: str) -> dict:
    """Fresh single market record (approval re-check path)."""
    d = get_json(f"/markets/{ticker}")
    m = (d or {}).get("market") or {}
    nm = normalize_market(m)
    try:
        ev = get_json(f"/events/{m.get('event_ticker')}")
        nm["category"] = _canonical_category(((ev or {}).get("event") or {}).get("category"))
    except Exception:
        pass
    return nm
