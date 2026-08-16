"""Combinatorial arbitrage scanner (intra-venue, cross-market logic).

Grounding: Oracle Boar thread + IMDEA/Oxford study (arxiv 2508.03474). Two
markets about the same event are logically welded: a narrow outcome can never
be priced above the broad outcome that contains it. Two shapes:

  1. Threshold ladders (monotonicity): P(>lower) >= P(>upper). A ladder series
     (KXGOLDMON, KXBTCMAXMON, KX...TOTAL, KX...SPREAD) has numeric strikes;
     when ask_yes(lower) < ask_yes(upper) the book contradicts itself.
     Buy lower YES + upper NO locks a spread.
  2. Winner vs margin: P("X wins") >= P("X wins by >N"). Same event, broad
     winner market vs narrow margin market. When the margin market prices
     above the winner market, buy winner-YES + margin-NO.

REPORT-ONLY. Never places orders. Reuses the fee model; execution stays on the
normal gate (pre_flight + wall + approval).
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import fees as fees_mod
from . import kalshi


def parse_strike(ticker: str) -> float | None:
    """Extract numeric strike from KXGOLDMON-26AUG3117-T4251.99 -> 4251.99."""
    parts = (ticker or "").split("-")
    for p in parts:
        if p.startswith("T") and p[1:].replace(".", "").isdigit():
            try:
                return float(p[1:])
            except ValueError:
                return None
    return None


def series_prefix(ticker: str) -> str:
    """Base series ticker (strip date + strike suffix)."""
    parts = (ticker or "").split("-")
    if len(parts) >= 3:
        return parts[0]
    return (ticker or "").split("-")[0]


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def discover_ladder_series(max_series: int = 60, min_strikes: int = 3) -> list[dict]:
    """Auto-discover ladder series (numeric strikes) across open markets.

    Returns list of {prefix, strikes: [(ticker, strike, yes_ask, yes_bid, volume)]}.
    Groups markets by series_prefix, keeps those with parseable numeric strikes.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    cursor = None
    fetched = 0
    while len(groups) < max_series * 2 and fetched < 20000:
        params = {"limit": 1000, "status": "open", "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        d = kalshi.get_json("/markets", params)
        ms = d.get("markets") or []
        if not ms:
            break
        for m in ms:
            if m.get("market_type") not in (None, "binary"):
                continue
            t = m.get("ticker", "")
            s = parse_strike(t)
            if s is None:
                continue
            groups[series_prefix(t)].append({
                "ticker": t,
                "strike": s,
                "yes_ask": _to_float(m.get("yes_ask_dollars")),
                "yes_bid": _to_float(m.get("yes_bid_dollars")),
                "volume": _to_float(m.get("volume_fp")),
                "close": m.get("close_time"),
            })
        fetched += len(ms)
        cursor = d.get("cursor")
        if not cursor:
            break

    out = []
    for prefix, mkts in groups.items():
        # group by close_time too — strikes in different expiry windows
        # (e.g. KXNASDAQ100U H1000 vs H1600) are different markets with
        # legitimately different probabilities; comparing across them
        # fabricates fake monotonicity violations.
        by_window: dict[str, list[dict]] = defaultdict(list)
        for m in mkts:
            by_window[str(m.get("close"))].append(m)
        for window_mkts in by_window.values():
            if len(window_mkts) < min_strikes:
                continue
            # dedupe by strike (keep highest volume)
            by_strike: dict[float, dict] = {}
            for m in window_mkts:
                s = m["strike"]
                if s not in by_strike or m["volume"] > by_strike[s]["volume"]:
                    by_strike[s] = m
            if len(by_strike) >= min_strikes:
                out.append({"prefix": prefix, "strikes": list(by_strike.values())})
    out.sort(key=lambda g: -len(g["strikes"]))
    return out


def monotonicity_violations(series: dict, min_volume: float = 0.0) -> list[dict]:
    """Find P(>lower) < P(>upper) violations in a discovered ladder series.

    NO-side cost rule (research): NO ask = 1 - yes_BID, NOT 1 - yes_ask.
    """
    strikes = sorted(series["strikes"], key=lambda m: m["strike"])
    viols = []
    for i in range(len(strikes) - 1):
        lower, upper = strikes[i], strikes[i + 1]
        if lower["yes_ask"] <= 0 or upper["yes_ask"] <= 0:
            continue
        if lower["yes_ask"] < upper["yes_ask"]:
            cost_yes = lower["yes_ask"]
            cost_no = 1.0 - upper["yes_bid"]
            combined = cost_yes + cost_no
            gross = 1.0 - combined
            fee = (fees_mod.kalshi_fee(cost_yes, 1.0, lower["ticker"])
                   + fees_mod.kalshi_fee(cost_no, 1.0, upper["ticker"]))
            slip = 0.01
            net = gross - fee - slip
            if min_volume and min(lower["volume"], upper["volume"]) < min_volume:
                continue
            viols.append({
                "series": series["prefix"],
                "lower_strike": lower["strike"], "upper_strike": upper["strike"],
                "lower_ticker": lower["ticker"], "upper_ticker": upper["ticker"],
                "lower_yes_ask": round(cost_yes, 3),
                "upper_yes_ask": upper["yes_ask"],
                "no_ask_upper": round(cost_no, 3),
                "gross_edge": round(gross, 4),
                "kalshi_fees": round(fee, 4),
                "net_edge": round(net, 4),
                "close": upper.get("close"),
            })
    viols.sort(key=lambda v: v["net_edge"], reverse=True)
    return viols


_MARGIN = re.compile(r"wins? by (?:more than|over)\s*(\d+(?:\.\d+)?)", re.I)
# tennis/esports spread template: "X wins at least 7.5 more games than Y"
_MARGIN_AT_LEAST = re.compile(r"wins? at least\s*(\d+(?:\.\d+)?)\s+more games?", re.I)
# winner template: "Will X win THE ...match?" -> subject is X. Requiring "the"
# after "win" excludes narrow set/map/leg markets ("win set 2", "win map 1",
# "win by ..."), which are NOT the broad match-winner leg.
_WINNER = re.compile(r"^will\s+(.+?)\s+win\s+the\b", re.I)
# winner REJECT: anything with a "by/at least/over/set score/straight sets"
# modifier is a NARROW market (spread, exact-set-score, margin), NOT the broad
# match-winner. "win the match by a set score of 2-1" is narrower than "win the
# match" — pairing it as the broad leg fabricates fake arbs.
_WINNER_REJECT = re.compile(
    r"set score|straight sets|by |at least|more than|over \d|in \d sets|"
    r"exactly|\bto \d|win (by|with)",
    re.I)


def _subject_norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
    s = re.sub(r"^(will )+", "", s.strip())  # strip leading "Will "
    return " ".join(sorted(s.split()))


def winner_margin_check(event_ticker: str, markets: list[dict], min_edge_cents: float = 2.0) -> list[dict]:
    """Winner vs margin dependency within one event (fallback shape).

    Kalshi usually splits winner and margin across separate events, so this
    returns [] for most events — the cross-event matcher below is the real
    path. Kept for completeness and events that DO bundle them.
    """
    winners: dict[str, dict] = {}   # subject -> winner market
    margins: list[dict] = []        # margin markets with parsed subject+threshold
    for m in markets:
        title = m.get("title") or ""
        sub = m.get("yes_sub_title") or ""
        mm = _MARGIN.search(title)
        if mm:
            subject = title[:mm.start()].strip()
            margins.append({**m, "subject": subject,
                            "threshold": float(mm.group(1))})
        else:
            winners[sub.lower()] = m
    out = []
    for mg in margins:
        w = winners.get(mg["subject"].lower())
        if w is None:
            continue
        w_yes = _to_float(w.get("yes_ask_dollars"))
        mg_yes = _to_float(mg.get("yes_ask_dollars"))
        mg_bid = _to_float(mg.get("yes_bid_dollars"))
        if mg_yes <= 0 or w_yes <= 0 or mg_yes <= w_yes:
            continue
        cost_winner = w_yes
        cost_margin_no = 1.0 - mg_bid
        gross = 1.0 - (cost_winner + cost_margin_no)
        fee = (fees_mod.kalshi_fee(cost_winner, 1.0, w.get("ticker", ""))
               + fees_mod.kalshi_fee(cost_margin_no, 1.0, mg.get("ticker", "")))
        slip = 0.01
        net = gross - fee - slip
        if net < min_edge_cents / 100.0:
            continue
        out.append({
            "event": event_ticker,
            "subject": mg["subject"],
            "winner_ticker": w.get("ticker"),
            "winner_yes_ask": round(w_yes, 3),
            "margin_ticker": mg.get("ticker"),
            "margin_threshold": mg["threshold"],
            "margin_yes_ask": round(mg_yes, 3),
            "margin_yes_bid": mg_bid,
            "gross_edge": round(gross, 4),
            "kalshi_fees": round(fee, 4),
            "net_edge": round(net, 4),
        })
    out.sort(key=lambda v: v["net_edge"], reverse=True)
    return out


def _close_ts(s: str | None) -> float | None:
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _close_within_hours(a: str | None, b: str | None, hours: float = 6.0) -> bool:
    """True if two close times are within `hours` (match-scoped, not
    tournament-scoped). A tournament-winner market closes days later than a
    match-spread market — those are DIFFERENT universes and must not be
    paired. Returns False when either side is missing (fail closed)."""
    ta, tb = _close_ts(a), _close_ts(b)
    if ta is None or tb is None:
        return False
    return abs(ta - tb) <= hours * 3600


def scan_winner_margin(min_edge_cents: float = 2.0, max_markets: int = 15000,
                       close_window_hours: float = 6.0,
                       limit: int = 20) -> dict:
    """Cross-event winner vs margin dependency check.

    Collects "X wins" winner markets and "X wins by more than N" margin markets
    across open Kalshi markets, matches subjects across the two groups (they
    live in different events), and checks P(margin) <= P(winner). Violation =
    margin YES ask > winner YES ask -> buy winner YES + margin NO.

    CLOSE-TIME GATE: winner and margin legs must close within
    `close_window_hours` of each other. "Will X win the ATP Cincinnati"
    (tournament, closes days later) vs "X wins at least 7.5 more games"
    (match spread, closes hours later) share a subject key but are NOT the
    same dependency — pairing them fabricates fake arbs.
    """
    winners: dict[str, list[dict]] = {}
    margins: list[dict] = []
    cursor = None
    fetched = 0
    while fetched < max_markets:
        params = {"limit": 1000, "status": "open", "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        d = kalshi.get_json("/markets", params)
        ms = d.get("markets") or []
        if not ms:
            break
        for m in ms:
            if m.get("market_type") not in (None, "binary"):
                continue
            title = m.get("title") or ""
            mm = _MARGIN.search(title)
            if not mm:
                mm = _MARGIN_AT_LEAST.search(title)
            wm = _WINNER.match(title.strip())
            if mm:
                # margin: "Washington wins by over 4.5 runs?" / "X wins at least 7.5 more games"
                subject = _subject_norm(title[:mm.start()])
                if subject:
                    margins.append({**m, "subject": subject,
                                    "threshold": float(mm.group(1))})
            elif wm and not _WINNER_REJECT.search(title):
                # winner: "Will Iga Swiatek win the ... match?" -> subject = Iga Swiatek.
                # _WINNER_REJECT drops narrow markets (set-score/spread/margin)
                # so only the broad match-winner reaches here.
                subject = _subject_norm(wm.group(1))
                if subject:
                    winners.setdefault(subject, []).append(m)
        fetched += len(ms)
        cursor = d.get("cursor")
        if not cursor:
            break

    out = []
    for mg in margins:
        # pick the winner leg whose close time matches the margin leg's window
        # (match-scoped). Tournament-winner markets close days later — skip them.
        w = None
        for cand in winners.get(mg["subject"], []):
            if _close_within_hours(cand.get("close_time"), mg.get("close_time"),
                                   close_window_hours):
                w = cand
                break
        if w is None:
            continue
        w_yes = _to_float(w.get("yes_ask_dollars"))
        mg_yes = _to_float(mg.get("yes_ask_dollars"))
        mg_bid = _to_float(mg.get("yes_bid_dollars"))
        if mg_yes <= 0 or w_yes <= 0 or mg_yes <= w_yes:
            continue
        cost_winner = w_yes
        cost_margin_no = 1.0 - mg_bid
        gross = 1.0 - (cost_winner + cost_margin_no)
        fee = (fees_mod.kalshi_fee(cost_winner, 1.0, w.get("ticker", ""))
               + fees_mod.kalshi_fee(cost_margin_no, 1.0, mg.get("ticker", "")))
        slip = 0.01
        net = gross - fee - slip
        if net < min_edge_cents / 100.0:
            continue
        out.append({
            "subject": mg["subject"],
            "winner_ticker": w.get("ticker"),
            "winner_yes_ask": round(w_yes, 3),
            "margin_ticker": mg.get("ticker"),
            "margin_threshold": mg["threshold"],
            "margin_yes_ask": round(mg_yes, 3),
            "margin_yes_bid": mg_bid,
            "gross_edge": round(gross, 4),
            "kalshi_fees": round(fee, 4),
            "net_edge": round(net, 4),
        })
    out.sort(key=lambda v: v["net_edge"], reverse=True)
    n_winner = sum(len(v) for v in winners.values())
    return {"markets_fetched": fetched, "winner_markets": n_winner,
            "margin_markets": len(margins), "violations": out[:limit]}
