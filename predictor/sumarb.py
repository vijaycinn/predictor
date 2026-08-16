"""Intra-market rebalancing arbitrage scanner (sum-to-1 rule).

Grounding: Oracle Boar thread + IMDEA/Oxford study (arxiv 2508.03474) —
in any market whose outcomes are exhaustive + mutually exclusive, the YES
prices must sum to $1.00. When they drift off $1 there is risk-free money:

  - sum(YES ask) < 1  -> buy every YES once (basket). Pays $1 guaranteed.
                         gross = 1 - sum_ask.
  - sum(YES bid) > 1  -> YES side overpriced, NO side cheap. Buy NO on every
                         outcome (cost sum(1 - yes_bid)), pays (n-1) guaranteed.
                         gross = sum_bid - 1.

Kalshi expresses a multi-outcome question as N binary markets under ONE
event_ticker (e.g. KXINDIANPM = "Who becomes PM" -> one binary per candidate,
yes_sub_title = candidate). Those are partitions. Player props, ladders
("over 5.5 goals"), and MVE combos ("yes X, yes Y") are NOT partitions and
must never be summed.

REPORT-ONLY. Never places orders. A flagged basket still needs manual
exhaustiveness verification (coverage guard) before any real trade — this
scanner surfaces candidates, it does not execute.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import fees as fees_mod
from . import kalshi

# events whose ticker marks them as multi-variable-event combo junk (not a
# partition — outcomes overlap, sum-to-1 does not apply)
_MVE_PREFIXES = ("KXMVE",)

# numeric-threshold markers: ladders and player props, never partitions
_NUMERIC_TITLE = re.compile(
    r"(:\s*\d+\+)|(\bover\s+\d)|(\bunder\s+\d)|(by more than \d)|"
    r"(by over \d)|(\bmore than \d)|(\+\d+)|(\babove\s+\d)|(\bat least\s+\d)|"
    r"(\bexceed\w*\s+\d)|(\breach\w*\s+\d)|(\bhit\w*\s+\d)|(\d+\s*(or more|or fewer|or less))",
    re.I)

# ANY digit in a title marks it as a threshold/ladder market, not a candidate
# partition. Kalshi puts dates in the TICKER (KX...-29APR30), never in the
# title — real partitions (elections, winner markets) have zero digits in the
# question text. This is the hard discriminator: "above 78.99°" (ladder) vs
# "become Prime Minister" (partition).
_ANY_DIGIT = re.compile(r"\d")

# catch-all outcomes that make a partition exhaustive
_CATCHALL = re.compile(
    r"^(other|field|none of the above|someone else|no candidate|any other|"
    r"independent|another (candidate|person|party)|nobody|not listed)",
    re.I)

DEFAULT_MIN_EDGE_CENTS = 3
DEFAULT_MIN_MARKETS = 3


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_partition_candidate(event_ticker: str, markets: list[dict]) -> bool:
    """True if `markets` (one event's binaries) look like a mutually-exclusive
    partition rather than ladders/player-props/MVE combos."""
    if not event_ticker or any(event_ticker.startswith(p) for p in _MVE_PREFIXES):
        return False
    if len(markets) < DEFAULT_MIN_MARKETS:
        return False
    subs = []
    for m in markets:
        title = (m.get("title") or "").strip()
        sub = (m.get("yes_sub_title") or "").strip()
        # hard discriminator: any digit in the question = threshold/ladder market
        if _ANY_DIGIT.search(title):
            return False
        # numeric thresholds / MVE conjunctions disqualify the whole event
        if _NUMERIC_TITLE.search(title):
            return False
        if not sub or _NUMERIC_TITLE.search(sub):
            return False
        subs.append(sub.lower())
    # distinct outcomes required (no dup candidate = not a clean partition)
    if len(set(subs)) != len(subs):
        return False
    return True


def coverage_gap(markets: list[dict]) -> dict:
    """Detect whether a partition has an explicit catch-all outcome.

    Returns {exhaustive: bool, catchall: str|None, note: str}. A partition
    WITHOUT a catch-all may be genuinely incomplete (an unlisted outcome can
    still win), so a sum<1 gap is NOT risk-free profit — it is the price of
    that unlisted risk. Agent must verify before any trade.
    """
    catchall = None
    for m in markets:
        sub = (m.get("yes_sub_title") or "").strip()
        if _CATCHALL.match(sub):
            catchall = sub
            break
    if catchall:
        return {"exhaustive": True, "catchall": catchall,
                "note": f"catch-all present: {catchall}"}
    return {"exhaustive": False, "catchall": None,
            "note": "no catch-all outcome listed — partition may be incomplete "
                    "(unlisted outcome could win); verify exhaustiveness before trading"}


def _slippage_cents(n_legs: int) -> float:
    """Assume ~1c crossing cost per leg, in dollars."""
    return 0.01 * n_legs


def _fees_for_basket(prices: list[float], tickers: list[str]) -> float:
    return sum(fees_mod.kalshi_fee(p, 1.0, t) for p, t in zip(prices, tickers))


def scan_basket(event_ticker: str, markets: list[dict], min_edge_cents: float = DEFAULT_MIN_EDGE_CENTS) -> dict | None:
    """Evaluate one partition event for sum-to-1 rebalancing arb.

    Returns a report dict (never executes), or None if no qualifying edge.
    """
    if not _is_partition_candidate(event_ticker, markets):
        return None

    cov = coverage_gap(markets)
    asks = [_to_float(m.get("yes_ask_dollars")) for m in markets]
    bids = [_to_float(m.get("yes_bid_dollars")) for m in markets]
    tickers = [m.get("ticker", "") for m in markets]
    n = len(markets)
    sum_ask = sum(asks)
    sum_bid = sum(bids)

    # Buy-side: sum_ask < 1 -> buy all YES, pays $1. Risk-free ONLY if the
    # partition is exhaustive (catch-all present or verified complete).
    buy = None
    if sum_ask > 0 and sum_ask < 1.0:
        gross = 1.0 - sum_ask
        fees = _fees_for_basket(asks, tickers)
        slip = _slippage_cents(n)
        net = gross - fees - slip
        buy = {
            "direction": "buy_yes_basket",
            "gross": gross, "fees": fees, "slippage": slip, "net": net,
            "cost": sum_ask, "payoff": 1.0,
        }
        # buy side is ONLY risk-free when exhaustive
        if not cov["exhaustive"]:
            buy["risk_free"] = False
            buy["reason"] = "sum_ask<1 but no catch-all: gap may be unlisted-outcome risk"
        else:
            buy["risk_free"] = True
            buy["reason"] = "buy all YES, lock $1"

    # Sell-side (buy NO basket): sum_bid > 1 -> NO side cheap.
    sell = None
    if sum_bid > 1.0 and n >= 2:
        gross = sum_bid - 1.0
        no_prices = [1.0 - b for b in bids]  # cost to buy NO on each outcome
        fees = _fees_for_basket(no_prices, tickers)
        slip = _slippage_cents(n)
        net = gross - fees - slip
        sell = {
            "direction": "buy_no_basket",
            "gross": gross, "fees": fees, "slippage": slip, "net": net,
            "cost": sum(no_prices), "payoff": float(n - 1),
            "risk_free": True,  # NO basket pays n-1 regardless of outcome, no coverage concern
            "reason": "YES overpriced; buy NO on all, lock n-1",
        }

    edges = [x for x in (buy, sell) if x and x["net"] >= min_edge_cents / 100.0]
    if not edges:
        return None

    best = max(edges, key=lambda e: e["net"])
    return {
        "event_ticker": event_ticker,
        "title": markets[0].get("title", "").split("?")[0][:70],
        "n_markets": n,
        "sum_yes_ask": round(sum_ask, 4),
        "sum_yes_bid": round(sum_bid, 4),
        "coverage": cov,
        "best": best,
        "all_edges": edges,
        "close_time": markets[0].get("close_time"),
        "legs": [{"ticker": m.get("ticker"), "candidate": m.get("yes_sub_title"),
                  "yes_ask": _to_float(m.get("yes_ask_dollars")),
                  "yes_bid": _to_float(m.get("yes_bid_dollars")),
                  "volume": _to_float(m.get("volume_fp"))} for m in markets],
    }


# STRICT single-winner partition event titles. Sum-to-1 (and the NO-basket
# n-1 payoff) requires EXACTLY ONE outcome resolves YES. Multi-winner questions
# ("which parties will be in government", "which artists announce a tour",
# "who will be one of the top 3") are NOT partitions — buying NO on all is a
# naked multi-leg directional bet, not a locked basket.
_PARTITION_EVENT = re.compile(
    r"who will be the next|who will become|who will win|who'll be|"
    r"who will (replace|succeed|be named)|which party will win|"
    r"next .* (winner|chair|pm|prime minister|president|secretary|ceo|pope|"
    r"speaker|successor)|will be the next",
    re.I)

# multi-winner / independent-outcome markers — REJECT even if title has a
# "who/which" shape (these bundle markets where several can resolve YES)
_MULTI_WINNER = re.compile(
    r"be a part of|be part of|be in the (next )?government|be in government|"
    r"be one of|be on the ballot|be on the|on the ballot|announce|"
    r"which parties|coalition|be among|top \d|be included",
    re.I)


def discover_partition_events(max_events: int = 300) -> list[str]:
    """Find partition-style event tickers via the /events title stream.

    Candidate-question events ("Who will be X") hold mutually-exclusive
    binary markets — the sum-to-1 shape. /markets pagination buries these
    (low-volume elections sort late), so /events is the correct discovery
    layer. Returns event_tickers.
    """
    out: list[str] = []
    cursor = None
    while len(out) < max_events:
        params = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        d = kalshi.get_json("/events", params)
        evs = d.get("events") or []
        if not evs:
            break
        for e in evs:
            t = e.get("title") or ""
            if _MULTI_WINNER.search(t):
                continue
            if _PARTITION_EVENT.search(t):
                out.append(e.get("event_ticker"))
        cursor = d.get("cursor")
        if not cursor:
            break
    # dedupe, keep order
    seen: set[str] = set()
    uniq = []
    for et in out:
        if et not in seen:
            seen.add(et)
            uniq.append(et)
    return uniq


def scan(min_edge_cents: float = DEFAULT_MIN_EDGE_CENTS,
         min_markets: int = DEFAULT_MIN_MARKETS,
         max_events: int = 300,
         limit: int = 20) -> dict:
    """Discover partition events and sum-to-1 check each.

    Returns {opportunities: [...], events_seen, partition_candidates, ...}.
    Purely additive read path — public /events + /markets, no auth, no writes.
    """
    events = discover_partition_events(max_events=max_events)

    opps: list[dict] = []
    partitions = 0
    fetched = 0
    for et in events:
        d = kalshi.get_json("/markets", {"event_ticker": et, "limit": 500, "status": "open"})
        mks = d.get("markets") or []
        fetched += len(mks)
        if len(mks) < min_markets:
            continue
        partitions += 1
        r = scan_basket(et, mks, min_edge_cents=min_edge_cents)
        if r:
            opps.append(r)

    opps.sort(key=lambda o: o["best"]["net"], reverse=True)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "events_seen": len(events),
        "markets_fetched": fetched,
        "partition_candidates": partitions,
        "opportunities": opps[:limit],
    }


def format_opportunity(o: dict) -> str:
    b = o["best"]
    cov = o["coverage"]
    lines = [
        f"{o['event_ticker']} — {o['title']}",
        f"  {o['n_markets']} outcomes | sum YES ask {o['sum_yes_ask']:.3f} | sum YES bid {o['sum_yes_bid']:.3f}",
        f"  coverage: {cov['note']}",
        f"  BEST: {b['direction']} | gross {b['gross']*100:.1f}c fees {b['fees']*100:.1f}c "
        f"slip {b['slippage']*100:.1f}c net {b['net']*100:.1f}c | risk-free={b['risk_free']}",
        f"  {b['reason']}",
    ]
    if not b["risk_free"]:
        lines.append("  !! NOT risk-free — verify exhaustiveness before any trade")
    return "\n".join(lines)
