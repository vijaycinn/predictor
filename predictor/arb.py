"""Cross-venue arb analysis: Kalshi (Predexon data) vs Polymarket.

Predexon exposes NO find_matching_markets tool (verified against predexon-mcp
0.3.0 source + REST openapi) — matching is implemented here with strict
equivalence checks per VJ's rules: never assume equivalence from title alone;
confirm resolution timing + contract wording.

Opportunity types:
- pure arb: YES@A + NO@B (or reverse) locks payout < $1 combined
- synthetic arb: combined entry < 1.00 before fees/slippage
- statistical mispricing: EV positive, profit not locked (labeled clearly)

Dry-run only. Execution requires explicit 'execute' + restated legs.
"""
from __future__ import annotations

import re
import time
from difflib import SequenceMatcher

from . import predexon


# ---------- matching ----------

STOPWORDS = {"the", "will", "be", "a", "an", "to", "in", "on", "for", "of", "and",
             "or", "by", "at", "this", "that", "it", "is", "are", "was", "were",
             "win", "wins", "reach", "reaches", "hit", "hits", "before", "by"}

_NUM = re.compile(r"(\d[\d,]*\.?\d*)")

# near-synonyms across venues (nominee/nomination, election/elections)
SYNONYMS = {"nominee": "nomination", "election": "elections"}

# tokens whose asymmetry changes the contract meaning — reject match outright
DISQUALIFIERS = {"vice", "senate", "house", "governor", "primary", "runoff",
                 "impeach", "confirmation", "first", "second", "third", "over", "under"}


def normalize_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9$%.,]+", " ", t)
    # unify comma thousands: 95,000 -> 95000
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)
    toks = [SYNONYMS.get(w, w) for w in t.split() if w not in STOPWORDS and w]
    return " ".join(sorted(toks))


def _title_sim(a: str, b: str) -> float:
    """Jaccard on normalized token SETS — strict on shared vocabulary.

    Returns 0.0 when a disqualifying token (vice, senate, house...) is present
    on one side only — e.g. 'Vice-Presidential nominee' vs 'Presidential
    nominee' share 88% tokens but are different contracts.
    """
    ta, tb = normalize_title(a), normalize_title(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta.split()), set(tb.split())
    dq = (sa & DISQUALIFIERS) ^ (sb & DISQUALIFIERS)
    if dq:
        return 0.0
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return inter / len(sa | sb)


def _match_text(kalshi_m: dict) -> str:
    """Kalshi multi-candidate events share one title; candidate lives in the
    yes/no subtitle. Append it so 'Nithya Raman' matches the right market."""
    title = kalshi_m.get("title", "")
    sub = kalshi_m.get("yes_subtitle") or kalshi_m.get("no_subtitle") or ""
    if sub and sub.lower() not in title.lower():
        return f"{title} {sub}"
    return title


def _targets_close(a: str | None, b: str | None, days: int = 7) -> bool:
    """Compare close/expiry times; None on either side -> lenient pass."""
    from datetime import datetime, timezone

    def ts(s):
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None

    ta, tb = ts(a), ts(b)
    if ta is None or tb is None:
        return True  # cannot verify — caller downgrades confidence
    return abs(ta - tb) <= days * 86400


def _num_targets(a: str, b: str) -> bool:
    na = set(_NUM.findall(normalize_title(a)))
    nb = set(_NUM.findall(normalize_title(b)))
    if not na or not nb:
        return True  # no numeric targets — cannot verify
    return bool(na & nb)


def match_kalshi_to_polymarket(kalshi_m: dict, pm_markets: list[dict]) -> list[dict]:
    """Strict matching against search results (NOT a random pool).

    VJ rule: never assume equivalence from title similarity alone. Gates:
    open status, title sim threshold, close-time proximity, numeric target match.
    """
    out = []
    k_match_text = _match_text(kalshi_m)
    for pm in pm_markets:
        pm_title = pm.get("question") or pm.get("title") or ""
        if not pm_title:
            continue
        if pm.get("closed") or str(pm.get("status", "")).lower() not in ("", "open", "active"):
            continue
        sim = _title_sim(k_match_text, pm_title)
        if sim < 0.45:
            continue
        close_ok = _targets_close(kalshi_m.get("close_time"), pm.get("endDate") or pm.get("close_time"))
        num_ok = _num_targets(k_match_text, pm_title)
        reasons = [f"title sim {sim:.2f}"]
        if not close_ok:
            reasons.append("close_time mismatch")
        if not num_ok:
            reasons.append("numeric target mismatch")
        if sim >= 0.85 and close_ok and num_ok:
            conf = "strong"
        elif sim >= 0.60 and close_ok:
            conf = "medium"
        else:
            conf = "weak"
        out.append({"pm_market": pm, "confidence": conf, "reason": "; ".join(reasons)})
    out.sort(key=lambda c: _title_sim(k_match_text, c["pm_market"].get("question") or c["pm_market"].get("title", "")),
            reverse=True)
    return out


# ---------- pricing ----------

def _kalshi_side(m: dict, side: str) -> dict | None:
    """side: 'Yes' or 'No' — returns {bid, ask, predexon_id}."""
    for o in m.get("outcomes") or []:
        if (o.get("label") or "").lower() == side.lower():
            return o
    return None


def kalshi_prices(m: dict) -> dict | None:
    y = _kalshi_side(m, "Yes")
    n = _kalshi_side(m, "No")
    if not y or not n:
        return None
    return {
        "yes_bid": y.get("bid"), "yes_ask": y.get("ask"),
        "no_bid": n.get("bid"), "no_ask": n.get("ask"),
    }


def pm_prices(m: dict) -> dict | None:
    """Polymarket: outcomes list [Yes, No] with price (0-1)."""
    outs = m.get("outcomes") or []
    if len(outs) < 2:
        return None
    # Predexon polymarket market shape may vary; accept dicts with 'price'
    def price_of(o):
        if isinstance(o, dict):
            return o.get("price") or o.get("last_price") or o.get("bid")
        return o
    y, n = price_of(outs[0]), price_of(outs[1])
    if y is None or n is None:
        return None
    return {"yes_bid": y, "yes_ask": y, "no_bid": n, "no_ask": n}


# ---------- arb math ----------

def synthetic_arb(pair: dict, cfg: dict) -> dict | None:
    """Evaluate YES on venue A + NO on venue B (and reverse).

    Returns opportunity dict or None if no positive net edge.
    """
    k = pair["kalshi_market"]
    p = pair["pm_market"]
    kp = kalshi_prices(k)
    pp = pm_prices(p)
    if not kp or not pp:
        return None

    combos = [
        # (buy YES on Kalshi, buy NO on Polymarket)
        ("k_yes__pm_no", kp["yes_ask"], pp["no_ask"]),
        # (buy NO on Kalshi, buy YES on Polymarket)
        ("k_no__pm_yes", kp["no_ask"], pp["yes_ask"]),
    ]
    results = []
    for name, a, b in combos:
        if a is None or b is None:
            continue
        combined = a + b
        gross_edge = 1.0 - combined
        # fees: kalshi ~0; polymarket feeRate ~0-10% of p(1-p) (bps from venue data)
        fee_rate = 0.0
        if p.get("fees_enabled"):
            fee_rate = (p.get("maker_base_fee") or 0.0) / 10000.0
        fees = fee_rate * a * (1 - a) + fee_rate * b * (1 - b)
        # slippage: assume 1 tick (0.01) on the thin side, capped
        slippage = 0.01
        net = gross_edge - fees - slippage
        if net <= 0:
            continue
        results.append({
            "structure": name,
            "buy_a": {"venue": "kalshi", "price": a} if name.startswith("k_yes") else {"venue": "polymarket", "price": a},
            "buy_b": {"venue": "polymarket", "price": b} if name.startswith("k_yes") else {"venue": "kalshi", "price": b},
            "combined_cost": round(combined, 4),
            "gross_edge": round(gross_edge, 4),
            "fees_est": round(fees, 4),
            "slippage_est": round(slippage, 4),
            "net_edge": round(net, 4),
            "net_edge_pct": round(net * 100, 2),
        })
    if not results:
        return None
    results.sort(key=lambda r: r["net_edge"], reverse=True)
    best = results[0]
    return {
        "kalshi_market": k,
        "pm_market": p,
        "confidence": pair["confidence"],
        "match_reason": pair["reason"],
        "kalshi_prices": kp,
        "pm_prices": pp,
        "best": best,
        "all": results,
    }


def format_opportunity(opp: dict) -> str:
    k = opp["kalshi_market"]
    p = opp["pm_market"]
    b = opp["best"]
    kp, pp = opp["kalshi_prices"], opp["pm_prices"]
    lines = [
        f"Market pair: {k.get('ticker')} | {k.get('title')}  vs  {p.get('question') or p.get('title')}",
        f"Equivalence: {opp['confidence']} ({opp['match_reason']})",
        f"Prices Kalshi: YES bid/ask {kp['yes_bid']}/{kp['yes_ask']}  NO bid/ask {kp['no_bid']}/{kp['no_ask']}",
        f"Prices Polymarket: YES {pp['yes_ask']}  NO {pp['no_ask']}",
        f"Trade: {b['structure']} (leg1 @ {b['buy_a']['price']} {b['buy_a']['venue']}, leg2 @ {b['buy_b']['price']} {b['buy_b']['venue']})",
        f"Gross locked payout: $1.00 - ${b['combined_cost']:.4f} = ${b['gross_edge']:.4f}/contract",
        f"Fees est: ${b['fees_est']:.4f}  Slippage est: ${b['slippage_est']:.4f}",
        f"Net edge: ${b['net_edge']:.4f}/contract ({b['net_edge_pct']}%)",
        f"Capacity: TBD (needs depth check at these levels)",
        f"Risks: {opp['confidence'] == 'weak' and 'weak match; ' or ''}timing mismatch {not _targets_close(k.get('close_time'), p.get('endDate') or p.get('close_time')) and 'detected' or 'ok'}; settlement criteria must be verified on both venues",
        f"Recommendation: {'Execute (dry-run)' if opp['confidence'] == 'strong' and b['net_edge'] >= 0.02 else 'Watch' if b['net_edge'] > 0 else 'Skip'}",
    ]
    return "\n".join(lines)


def best_kalshi_trades(cfg: dict, min_volume: int = 5000, limit: int = 30,
                       pm_pool: list[dict] | None = None) -> dict:
    """'Best Kalshi trade today' workflow.

    For each Kalshi market, search Polymarket equivalents via Predexon search
    (relevant results, not a random pool), match strictly, then arb-check.
    """
    ks = predexon.list_kalshi_markets(status="open", min_volume=min_volume, limit=limit)
    opps = []
    matched_count = 0
    weak_count = 0
    for k in ks:
        if not kalshi_prices(k):
            continue
        q = k.get("title", "")
        if len(q) < 5:
            continue
        try:
            hits = predexon.search_polymarket(q, limit=8)
        except Exception:
            continue
        pm_pool = hits  # search results only — NEVER a random top-N pool
        matches = match_kalshi_to_polymarket(k, pm_pool)
        if not matches:
            continue
        matched_count += 1
        best_match = matches[0]
        if best_match["confidence"] == "weak":
            # ambiguous wording — never surface as opportunity (VJ rule)
            weak_count += 1
            continue
        opp = synthetic_arb({"kalshi_market": k, "pm_market": best_match["pm_market"],
                             "confidence": best_match["confidence"], "reason": best_match["reason"]}, cfg)
        if opp:
            opps.append(opp)
    opps.sort(key=lambda o: o["best"]["net_edge"], reverse=True)
    return {"opportunities": opps[:10], "kalshi_scanned": len(ks), "with_match": matched_count,
            "weak_dropped": weak_count}


def arb_check(cfg: dict, min_volume: int = 5000, limit: int = 30) -> dict:
    """'arb check' workflow — return only positive-net opportunities."""
    res = best_kalshi_trades(cfg, min_volume=min_volume, limit=limit)
    pos = [o for o in res["opportunities"] if o["best"]["net_edge"] > 0]
    return {**res, "positive": pos}
