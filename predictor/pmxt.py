"""PMXT Router integration — hosted cross-venue arb discovery.

PMXT Router (hosted) provides the cross-venue matching Predexon lacks:
fetch_arbitrage returns identity-relation pairs (confidence 1) with
buy/sell venue + price. We use it for DISCOVERY, then validate legs with
venue-native data (Predexon for Kalshi) before any recommendation.

Kalshi via PMXT = data only (their hosted writes cover Polymarket/Opinion/
Limitless; Kalshi needs venue-native path = our executor). Execution stays
native, approval-gated, $2 capped. Dry-run unless explicit execute.
"""
from __future__ import annotations

import os
import time

import pmxt


class PmxtError(Exception):
    pass


def _router():
    key = os.environ.get("PMXT_API_KEY")
    if not key:
        raise PmxtError("PMXT_API_KEY env var missing")
    return pmxt.Router(pmxt_api_key=key)


def native_ticker(market) -> str | None:
    """Map PMXT market to venue-native id. Kalshi slug IS the ticker."""
    ex = getattr(market, "source_exchange", "")
    slug = getattr(market, "slug", "") or ""
    if ex == "kalshi" and slug:
        return slug
    return None


def fetch_arbitrage(limit: int = 20, venues: list[str] | None = None) -> list[dict]:
    """PMXT cross-venue arb feed -> normalized dicts.

    Each: {market_a, market_b, spread, buy_venue, sell_venue, buy_price,
    sell_price, relation, confidence, kalshi_ticker (if a Kalshi leg)}.
    """
    try:
        arbs = _router().fetch_arbitrage()
    except Exception as e:
        raise PmxtError(f"fetch_arbitrage failed: {e}") from e
    if venues:
        arbs = [a for a in arbs
                if getattr(a, "buy_venue", None) in venues or getattr(a, "sell_venue", None) in venues]
    out = []
    for a in arbs[:limit]:
        ma, mb = a.market_a, a.market_b
        ka = native_ticker(ma)
        kb = native_ticker(mb)
        out.append({
            "market_a": ma, "market_b": mb,
            "spread": a.spread,
            "buy_venue": a.buy_venue, "sell_venue": a.sell_venue,
            "buy_price": a.buy_price, "sell_price": a.sell_price,
            "relation": a.relation, "confidence": a.confidence,
            "kalshi_ticker": ka or kb,
            "title_a": getattr(ma, "title", ""), "title_b": getattr(mb, "title", ""),
        })
    return out


def validate_kalshi_leg(ticker: str, title: str = "") -> dict | None:
    """Cross-validate a Kalshi leg against Predexon live data.

    Predexon search matches titles, not tickers — pass title for the lookup
    and ticker as exact-match check. Returns prices or None.
    """
    from . import predexon
    try:
        q = title[:80] if title else ticker[:80]
        for m in predexon.list_kalshi_markets(status="open", search=q, limit=50):
            if title and m.get("ticker") != ticker:
                continue
            if not title and m.get("ticker") != ticker:
                continue
            outs = {o.get("label", "").lower(): o for o in m.get("outcomes", [])}
            return {
                "yes_bid": outs.get("yes", {}).get("bid"),
                "yes_ask": outs.get("yes", {}).get("ask"),
                "no_bid": outs.get("no", {}).get("bid"),
                "no_ask": outs.get("no", {}).get("ask"),
            }
    except Exception:
        return None
    return None


def ranked_opportunities(min_net_edge: float = 0.02, limit: int = 20) -> dict:
    """Arb feed with Kalshi legs validated + net edge after fees/slippage.

    Fees: Kalshi 0, PMXT-listed venues assumed venue-native (0 here).
    Slippage: 1 tick (0.01) on the thin side, same model as arb.py.
    """
    arbs = fetch_arbitrage(limit=limit)
    validated = []
    for a in arbs:
        if a.get("kalshi_ticker"):
            kp = validate_kalshi_leg(a["kalshi_ticker"], str(a.get("title_a") or a.get("title_b") or ""))
            if kp is None:
                a["validation"] = "kalshi leg not found"
                continue
            # confirm PMXT buy/sell price lines up with live ask/bid
            if a["buy_venue"] == "kalshi":
                live = kp["yes_ask"] if a["market_a"].yes.label else kp["no_ask"]
                ok = live is not None and abs(a["buy_price"] - live) < 0.011
                a["validation"] = f"live ask {live}" if ok else f"price drift (live {live})"
            elif a["sell_venue"] == "kalshi":
                live = kp["yes_bid"] if a["market_a"].yes.label else kp["no_bid"]
                ok = live is not None and abs(a["sell_price"] - live) < 0.011
                a["validation"] = f"live bid {live}" if ok else f"price drift (live {live})"
            else:
                a["validation"] = "kalshi leg not traded this pair"
        else:
            a["validation"] = "no kalshi leg"
        fees = 0.0
        slippage = 0.01
        a["net_edge"] = round(a["spread"] - fees - slippage, 5)
        a["net_edge_pct"] = round(a["net_edge"] * 100, 2)
        if a["net_edge"] >= min_net_edge:
            validated.append(a)
    validated.sort(key=lambda x: x["net_edge"], reverse=True)
    return {"opportunities": validated, "total_arbs": len(arbs), "kalshi_legs": sum(1 for a in arbs if a.get("kalshi_ticker"))}
