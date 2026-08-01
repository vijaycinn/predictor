"""Predexon REST client — same API key + data as the Predexon MCP server.

Used by the predictor CLI (cron/automation) where MCP tools aren't callable.
Endpoints mirror the MCP tool surface. Kalshi = data only (no trading via
Predexon); Polymarket = data; execution stays on native venue paths.

NOTE: Predexon has NO cross-venue matching tool (find_matching_markets does not
exist in predexon-mcp@0.3.0 nor the REST API). Matching is implemented locally
in arb.py with strict equivalence checks.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

BASE = "https://api.predexon.com"
TIMEOUT = 20


class PredexonError(Exception):
    pass


class PredexonRateLimit(PredexonError):
    pass


def _key() -> str:
    k = os.environ.get("PREDEXON_API_KEY")
    if not k:
        raise PredexonError("PREDEXON_API_KEY env var missing")
    return k


def get(path: str, params: dict | None = None, retries: int = 4) -> Any:
    """GET with rate-limit backoff (free tier is tight: ~200ms windows)."""
    headers = {"x-api-key": _key()}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=headers, timeout=TIMEOUT)
            if r.status_code == 429:
                try:
                    wait = r.json().get("retryAfterMs", 500) / 1000.0
                except Exception:
                    wait = 0.5
                raise PredexonRateLimit(f"rate_limited (retry in {wait:.2f}s)")
            r.raise_for_status()
            return r.json()
        except PredexonRateLimit as e:
            last_err = e
            try:
                wait = max(0.5, float(str(e).split("(")[-1].replace("s)","")) )
            except Exception:
                wait = 0.5 * (2 ** attempt)
            time.sleep(wait + 0.2 * (2 ** attempt))
        except requests.RequestException as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))
    raise PredexonError(f"Predexon {path} failed: {last_err}")


def list_kalshi_markets(status: str = "open", search: str | None = None,
                        min_volume: int = 0, min_open_interest: int = 0,
                        limit: int = 100) -> list[dict]:
    params: dict = {"status": status, "limit": limit}
    if search:
        params["search"] = search
    if min_volume:
        params["min_volume"] = min_volume
    if min_open_interest:
        params["min_open_interest"] = min_open_interest
    d = get("/v2/kalshi/markets", params)
    return d.get("markets") or []


def get_kalshi_trades(ticker: str, limit: int = 50) -> list[dict]:
    d = get("/v2/kalshi/trades", {"ticker": ticker, "limit": limit})
    return d.get("trades") or []


def get_kalshi_orderbooks(ticker: str, start_time: int | None = None,
                          end_time: int | None = None, limit: int = 1) -> list[dict]:
    """Historical orderbook snapshots. Returns snapshots in window (newest first
    typically). With no times, defaults to last 6 hours."""
    now = int(time.time())
    start_time = start_time or (now - 6 * 3600)
    end_time = end_time or now
    d = get("/v2/kalshi/orderbooks", {
        "ticker": ticker, "start_time": start_time, "end_time": end_time, "limit": limit,
    })
    return d.get("orderbooks") or d.get("detail") or []


def search_polymarket(q: str, limit: int = 10) -> list[dict]:
    d = get("/v2/polymarket/search", {"q": q, "limit": limit})
    return d.get("results") or d.get("markets") or []


def list_polymarket_markets(status: str = "open", search: str | None = None,
                            limit: int = 100) -> list[dict]:
    params: dict = {"limit": min(limit, 100)}
    if status:
        params["status"] = status
    if search:
        params["search"] = search
    d = get("/v2/polymarket/markets/keyset", params)
    return d.get("markets") or d.get("items") or []


def get_polymarket_price(token_id: str) -> dict | None:
    d = get("/v2/polymarket/market-price/" + token_id)
    return d or None


def get_polymarket_orderbooks(condition_id: str, start_time: int | None = None,
                              end_time: int | None = None, limit: int = 1) -> list[dict]:
    now = int(time.time())
    start_time = start_time or (now - 6 * 3600)
    end_time = end_time or now
    d = get("/v2/polymarket/orderbooks", {
        "condition_id": condition_id, "start_time": start_time,
        "end_time": end_time, "limit": limit,
    })
    return d.get("orderbooks") or d.get("detail") or []


def health() -> bool:
    try:
        d = get("/health")
        return bool(d.get("ok"))
    except Exception:
        return False
