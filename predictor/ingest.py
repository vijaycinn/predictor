"""Polymarket data ingestion: gamma (discovery) + CLOB (book/prices) + data API."""
from __future__ import annotations

import json
import math
import time
from typing import Any

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
TIMEOUT = 15


class IngestError(Exception):
    pass


def get_json(url: str, params: dict | None = None) -> Any:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_json_str(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def discover_markets(cfg: dict, limit: int | None = None) -> list[dict]:
    """Category-diverse active binary markets via /events?tag=<cat>.

    Fetches top-volume events per configured category so one dominant event
    family (e.g. 2028 nomination markets) can't monopolize the scan pool.
    Applies volume/liquidity gates; spread gate enforced at scan time from CLOB.
    """
    scan = cfg.get("scan", {})
    limit = limit or scan.get("max_markets", 40)
    cats = scan.get("categories", []) or []
    min_vol = scan.get("min_volume_usd", 0)
    min_liq = scan.get("min_liquidity", 0)
    min_24h = scan.get("min_24h_volume", 0)
    out = []
    if not cats:
        cats = [None]  # no category filter -> plain top-volume fetch
    per_cat = max(1, int(math.ceil(limit / len(cats)))) if cats else limit

    for cat in cats:
        offset = 0
        cat_seen = 0
        while cat_seen < per_cat and offset < per_cat * 20:
            params = {
                "limit": min(100, per_cat * 3),
                "offset": offset,
                "active": "true",
                "closed": "false",
                "order": "volume",
                "ascending": "false",
            }
            if cat:
                params["tag"] = cat
            try:
                events = get_json(f"{GAMMA}/events", params)
            except requests.RequestException as e:
                raise IngestError(f"gamma /events failed (tag={cat}): {e}") from e
            if not events:
                break
            for ev in events:
                ev_tags = [str(t.get("slug", "")).lower() for t in (ev.get("tags") or [])]
                if cat and cat not in ev_tags:
                    continue
                ev_24h = _to_float(ev.get("volume24hr"))
                if ev_24h < min_24h:
                    continue
                for m in ev.get("markets") or []:
                    outcomes = _parse_json_str(m.get("outcomes"), [])
                    if len(outcomes) != 2:
                        continue
                    if not (m.get("active") and not m.get("closed")):
                        continue
                    clob = _parse_json_str(m.get("clobTokenIds"), ["", ""])
                    if not clob or not clob[0]:
                        continue
                    try:
                        vol = float(m.get("volume") or 0)
                        liq = float(m.get("liquidityNum") or m.get("liquidity") or 0)
                    except (TypeError, ValueError):
                        continue
                    if vol < min_vol or liq < min_liq:
                        continue
                    nm = normalize_market(m)
                    nm["category"] = cat or nm["category"]
                    nm["event_id"] = ev.get("id")
                    nm["event_volume"] = _to_float(ev.get("volume"))
                    nm["event_volume24hr"] = ev_24h
                    out.append(nm)
                    cat_seen += 1
                    if cat_seen >= per_cat:
                        break
                if cat_seen >= per_cat:
                    break
            if len(events) < 100:
                break
            offset += len(events)
        if len(out) >= limit:
            break
    return out[:limit]


def normalize_market(m: dict) -> dict:
    clob = _parse_json_str(m.get("clobTokenIds"), ["", ""])
    prices = _parse_json_str(m.get("outcomePrices"), [])
    return {
        "condition_id": m.get("conditionId") or m.get("condition_id"),
        "question": m.get("question"),
        "slug": m.get("slug"),
        "category": (m.get("category") or "").lower(),
        "event_id": m.get("events_id") or m.get("event_id"),
        "end_date": m.get("endDate") or m.get("endDateIso"),
        "created_at": m.get("createdAt"),
        "volume": _to_float(m.get("volume")),
        "liquidity": _to_float(m.get("liquidityNum") or m.get("liquidity")),
        "open_interest": _to_float(m.get("openInterest")),
        "outcomes": _parse_json_str(m.get("outcomes"), []),
        "outcome_prices": [ _to_float(p) for p in prices ],
        "clob_token_ids": clob if len(clob) == 2 else ["", ""],
        "active": bool(m.get("active", True)),
        "closed": bool(m.get("closed", False)),
        "market_type": m.get("marketType", "binary"),
        "fees_enabled": bool(m.get("feesEnabled")),
        "taker_base_fee": _to_float(m.get("takerBaseFee")),
        "maker_base_fee": _to_float(m.get("makerBaseFee")),
    }


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_orderbook(token_id: str) -> dict:
    if not token_id:
        return {}
    try:
        book = get_json(f"{CLOB}/book", {"token_id": token_id})
    except requests.RequestException as e:
        raise IngestError(f"CLOB /book failed: {e}") from e
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    # NOTE: CLOB returns bids sorted ascending (best LAST) and asks sorted
    # descending (best LAST). Index 0 is the WORST level.
    best_bid = float(bids[-1]["price"]) if bids else None
    best_ask = float(asks[-1]["price"]) if asks else None
    def depth(levels, n=5):
        # best n levels are the tail of the array
        return sum(float(l["size"]) for l in levels[-n:])
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_depth": depth(bids),
        "ask_depth": depth(asks),
        "top_bid_size": float(bids[-1]["size"]) if bids else 0.0,
        "top_ask_size": float(asks[-1]["size"]) if asks else 0.0,
        "last_trade_price": _to_float(book.get("last_trade_price")),
        "min_order_size": _to_float(book.get("min_order_size")),
        "tick_size": _to_float(book.get("tick_size", 0.01)),
        "raw": book,
    }


def fetch_price_history(condition_id: str, interval: str = "1w", fidelity: int = 168) -> list[dict]:
    if not condition_id:
        return []
    try:
        d = get_json(f"{CLOB}/prices-history", {"market": condition_id, "interval": interval, "fidelity": fidelity})
    except requests.RequestException as e:
        raise IngestError(f"CLOB /prices-history failed: {e}") from e
    return d.get("history", []) or []


def fetch_recent_trades(condition_id: str, limit: int = 20) -> list[dict]:
    if not condition_id:
        return []
    try:
        d = get_json(f"{DATA}/trades", {"market": condition_id, "limit": limit})
    except requests.RequestException as e:
        raise IngestError(f"Data /trades failed: {e}") from e
    return d if isinstance(d, list) else []


def fetch_open_interest(condition_id: str) -> float:
    if not condition_id:
        return 0.0
    try:
        d = get_json(f"{DATA}/oi", {"market": condition_id})
        return _to_float(d.get("numShares") if isinstance(d, dict) else d)
    except (requests.RequestException, AttributeError):
        return 0.0


def fetch_market_by_id(condition_id: str) -> dict:
    """Single market by condition_id via gamma (fresh record for approval re-check).

    NOTE: gamma filter param is condition_ids (plural); singular is silently
    ignored and returns the default top-volume list — wrong market risk.
    """
    markets = get_json(f"{GAMMA}/markets", {"condition_ids": condition_id})
    if not markets:
        raise IngestError(f"gamma market not found: {condition_id}")
    m = normalize_market(markets[0])
    if m["condition_id"] != condition_id:
        raise IngestError(f"gamma returned wrong market {m['condition_id']} for {condition_id}")
    return m
