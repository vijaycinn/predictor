"""Mechanical filters, position sizing (Kelly), and portfolio risk limits."""
from __future__ import annotations

import math
import time

from . import db


class MarginTradingError(Exception):
    """Raised if margin trading is ever enabled. NON-NEGOTIABLE: never borrow,
    never lever, never touch perps/futures/margin endpoints."""


def assert_no_margin(cfg: dict) -> None:
    """Hard guard: NO MARGIN TRADING EVER. Config cannot enable it — raising
    here is the only behavior if the flag is ever set true."""
    if cfg.get("risk", {}).get("margin_trading", False):
        raise MarginTradingError(
            "margin_trading must remain false. NO MARGIN TRADING EVER — "
            "all orders are fully cash-collateralized event contracts only."
        )


def wall_check(limit: float, side: str, ladder: list, cfg: dict) -> None:
    """WALL CHECK (VJ 2026-08-05, Ribecai lesson): limit must rest at the
    volume-weighted wall of the FULL ladder, never above it.

    Failure mode: bid placed at 0.76 (top-cluster bait in a moved snapshot)
    when the full-ladder wall sat at 0.64-0.65 — overpaid ~11c. Root cause:
    placement used a stale/moved top-10 snapshot instead of the FULL ladder
    density peak at instruction time.

    Rule:
      1. Pull the FULL ladder (all levels, not top-10).
      2. Trash-floor filter (drop < max(0.05, 0.25*ref)) + density mode
         (max neighborhood volume within ±3c) = the WALL. Wall can be AT
         top of book — that IS the money.
      3. For BUY YES: limit must be <= wall + wall_tolerance_cents.
         For BUY NO: symmetric on the NO ladder.
      4. Bidding ABOVE the wall = overpay = refused. Below wall = fine
         (maker edge, may not fill).
    Raises RuntimeError with wall + limit; caller must NOT place.
    """
    exec_cfg = cfg.get("execution", {})
    tol = float(exec_cfg.get("wall_tolerance_cents", 2))
    if not ladder:
        return
    ref = max(float(p) for p, _ in ladder)
    floor = max(0.05, 0.25 * float(ref))
    levels = []
    for p, s in ladder:
        try:
            price = float(p)
            size = float(s)
        except (TypeError, ValueError):
            continue
        if price >= floor:
            levels.append((price, size))
    if not levels:
        return  # no qualifying levels — skip (can't compute wall)
    # density mode: level with max neighborhood volume within +-0.03; tie -> cheaper
    band = 0.03
    wall = None
    best_vol = -1.0
    for p, s in levels:
        vol_nb = sum(ss for pp, ss in levels if abs(pp - p) <= band)
        if vol_nb > best_vol or (vol_nb == best_vol and (wall is None or p < wall)):
            best_vol = vol_nb
            wall = p
    if wall is None:
        return
    cap = round(wall + tol / 100.0, 3)
    if float(limit) > cap:
        raise RuntimeError(
            f"WALL CHECK: limit {float(limit):.3f} > full-ladder wall {wall:.3f} "
            f"+ {tol:.0f}c tolerance (cap {cap:.3f}). Money sits at the wall; "
            f"bidding above it overpays. Rest at wall or below."
        )


def pre_flight_check(sig: dict, limit: float, cfg: dict) -> None:
    """CONSOLIDATED pre-execution gate (VJ 2026-08-02, post-loss retrospective).

    Every execution path (scan approve, direct user pick, cron) MUST run this
    before placing. Single consistent rule set — no path can skip a rule:
      1. LIMIT ONLY: limit must be a valid 0<p<1 price. No market orders ever.
      2. WIN FLOOR (all bets): independent outcome prob >= min_win_prob (0.50),
         sourced from Polymarket cross-venue or verifiable research, carried in
         sig.approved_price / ev_calc.price_side. Kalshi's own book is NOT valid.
      3. PRICE BAND: YES buys <= max_buy_price_cents (40c).
      4. RAISE GUARD: limit <= approved * (1 + max_price_raise_pct/100).
      5. NO MARGIN: margin_trading must be false.
    Raises RuntimeError with the failing rule; caller must NOT place the order.
    """
    assert_no_margin(cfg)
    exec_cfg = cfg.get("execution", {})
    if limit is None or not (0 < float(limit) < 1):
        raise RuntimeError(f"LIMIT-ONLY: no valid limit price (got {limit!r}). No market orders ever.")
    if not sig.get("override_win_floor"):
        min_win = float(exec_cfg.get("min_win_prob", 0.50))
        if sig.get("side") == "YES":
            win_ref = sig.get("approved_price") or sig.get("ev_calc", {}).get("price_side")
            if win_ref is None:
                raise RuntimeError(
                    f"WIN FLOOR: no independent probability provided (need >= {min_win:.0%} from "
                    f"Polymarket/verifiable research). Kalshi's own book is NOT a valid source."
                )
            if float(win_ref) < min_win:
                raise RuntimeError(
                    f"WIN FLOOR: outcome prob {float(win_ref):.3f} < {min_win:.0%}. "
                    f"VJ rule: NEVER bet if outcome probability < 50%."
                )
        elif sig.get("side") == "NO":
            # NO side: independent prob of the NO outcome must be >= min_win.
            # sig.approved_price carries the independent NO prob (1 - indep YES).
            no_ref = sig.get("approved_price")
            if no_ref is None:
                raise RuntimeError(
                    f"WIN FLOOR (NO side): no independent NO probability provided "
                    f"(need >= {min_win:.0%} from Polymarket/verifiable research)."
                )
            if float(no_ref) < min_win:
                raise RuntimeError(
                    f"WIN FLOOR (NO side): NO outcome prob {float(no_ref):.3f} < {min_win:.0%}. "
                    f"VJ rule: NEVER bet if outcome probability < 50%."
                )
    if sig.get("side") == "YES" and not sig.get("override_price_band"):
        max_band = float(exec_cfg.get("max_buy_price_cents", 40))
        if float(limit) > max_band / 100.0:
            raise RuntimeError(
                f"PRICE BAND: YES limit {float(limit):.3f} > {max_band:.0f}c cap."
            )
    ref = sig.get("ev_calc", {}).get("price_side") or sig.get("approved_price")
    if ref is not None:
        max_raise_pct = float(exec_cfg.get("max_price_raise_pct", 10))
        cap = float(ref) * (1.0 + max_raise_pct / 100.0)
        if float(limit) > cap:
            raise RuntimeError(
                f"PRICE RAISE: limit {float(limit):.3f} > {max_raise_pct:.0f}% above approved "
                f"{float(ref):.3f} (cap {cap:.3f}). Refusing to overpay."
            )


def check_filters(features: dict, sig: dict, cfg: dict) -> tuple[bool, str]:
    """Return (pass, reason_if_blocked)."""
    exec_cfg = cfg.get("execution", {})
    max_spread = exec_cfg.get("max_spread", 0.04)
    min_hte = exec_cfg.get("min_hours_to_expiry", 2)
    max_days = exec_cfg.get("max_days_to_expiry", 120)

    spread = features.get("spread")
    if spread is not None and spread > max_spread:
        return False, f"spread {spread:.3f} > max {max_spread}"

    hte = features.get("hours_to_expiry")
    if hte is None:
        return False, "no expiry date"
    if hte < min_hte:
        return False, f"expires in {hte:.1f}h < {min_hte}h"
    if hte > max_days * 24:
        return False, f"expires in {hte/24:.0f}d > {max_days}d"

    hrs = features.get("hours_since_last_trade")
    if hrs is not None and hrs > 24:
        return False, f"no trades in {hrs:.1f}h"

    if sig.get("action") != "BUY":
        return False, f"action {sig.get('action')} not tradable"

    conf = sig.get("confidence", 0)
    if conf < 0.35:
        return False, f"confidence {conf:.2f} too low"

    return True, ""


def kelly_size(sig: dict, cfg: dict) -> float:
    """Fraction of capital per trade via capped Kelly, scaled by confidence."""
    risk = cfg.get("risk", {})
    kelly_frac = risk.get("kelly_fraction", 0.25)
    max_frac = risk.get("max_per_trade_frac", 0.20)

    ev_calc = sig.get("ev_calc", {})
    prob_side = ev_calc.get("prob_side", 0.5)
    price_side = ev_calc.get("price_side", 0.5)
    if price_side <= 0 or prob_side <= price_side:
        return 0.0
    # Kelly f* = (p*b - q) / b where b = payoff/loss ratio
    payoff = 1.0 - price_side
    loss = price_side
    if payoff <= 0 or loss <= 0:
        return 0.0
    b = payoff / loss
    p = prob_side
    q = 1.0 - p
    kelly = (p * b - q) / b
    kelly = max(0.0, min(kelly, 1.0))
    conf = sig.get("confidence", 0.5)
    frac = kelly * kelly_frac * conf
    frac = min(frac, max_frac)
    return max(frac, 0.0)


def capital_available(cfg: dict, positions: list[dict]) -> float:
    risk = cfg.get("risk", {})
    capital = risk.get("capital_usd", 1000)
    used = sum(p["fill_price"] * p["size"] for p in positions if p.get("fill_price"))
    return capital - used


def check_risk_limits(conn, sig: dict, size_dollars: float, cfg: dict) -> tuple[bool, str]:
    """Portfolio hard limits. LIVE ONLY — paper mode is an unrestricted thesis
    lab (virtual capital, Kelly sizing only). Real trades get all the rules."""
    if cfg.get("mode") != "live":
        return True, ""
    risk = cfg.get("risk", {})
    capital = risk.get("capital_usd", 1000)
    max_trade = risk.get("max_trade_usd", 2.0)
    max_notional = risk.get("max_notional_frac", 0.60) * capital
    max_daily_loss = risk.get("max_daily_loss_usd", 50)
    max_concurrent = risk.get("max_concurrent_positions", 12)
    max_event = risk.get("max_per_event_frac", 0.30) * capital
    max_cat = risk.get("max_same_category_frac", 0.40) * capital

    positions = db.open_positions(conn)

    # daily realized P&L (paper): losses count against daily loss cap
    day_start = time.time() - 86400
    pnl_rows = conn.execute(
        "SELECT pnl FROM trades WHERE status='CLOSED' AND created_at >= ? AND pnl IS NOT NULL",
        (day_start,),
    ).fetchall()
    daily_pnl = sum(r["pnl"] for r in pnl_rows)
    if daily_pnl < -max_daily_loss:
        return False, f"daily loss {-daily_pnl:.2f} exceeds cap {max_daily_loss}"

    if len(positions) >= max_concurrent:
        return False, f"position count {len(positions)} >= max {max_concurrent}"

    notional = size_dollars
    if notional > max_trade:
        return False, f"notional {notional:.2f} > max_trade_usd {max_trade:.2f}"
    if notional > max_notional:
        return False, f"notional {notional:.2f} > max {max_notional:.2f}"

    # per-event (same condition/event) exposure
    event_exposure = sum(p["fill_price"] * p["size"] for p in positions if p["condition_id"] == sig["condition_id"])
    if event_exposure + notional > max_event:
        return False, f"event exposure {event_exposure + notional:.2f} > max {max_event:.2f}"

    # category concentration
    cat = sig.get("metrics_snapshot", {}).get("category")
    if cat:
        cat_exposure = sum(p["fill_price"] * p["size"] for p in positions if p.get("category") == cat)
        if cat_exposure + notional > max_cat:
            return False, f"category {cat} exposure {cat_exposure + notional:.2f} > max {max_cat:.2f}"

    return True, ""


def limit_price(sig: dict, features: dict, cfg: dict) -> float:
    """Pick limit price: maker-friendly by default, nudge inside book by aggressiveness.
    NO side trades at 1 - YES book (Kalshi/Polymarket binary equivalence).

    Maker depth strategy (VJ 2026-08-02): when prefer_maker, look for a bid level
    >= maker_depth_cents below last trade (fallback: best ask) with size >=
    maker_min_volume in the full ladder. Rest there and collect a better fill if
    price comes to us. Falls back to old 50% nudge when no qualifying level."""
    ev_calc = sig.get("ev_calc", {})
    side = sig.get("side")
    mid = features.get("mid") or ev_calc.get("price_side")
    exec_cfg = cfg.get("execution", {})
    prefer_maker = exec_cfg.get("prefer_maker", True)

    if side == "YES":
        best_ask = features.get("best_ask")
        if prefer_maker and best_ask is not None:
            maker = _maker_level(features.get("bid_ladder") or [], best_ask,
                                 exec_cfg.get("maker_depth_cents", 2),
                                 exec_cfg.get("maker_min_volume", 100))
            if maker is not None:
                return round(maker, 3)
            return round(min(mid + (best_ask - mid) * 0.5, best_ask), 3)
        return round(best_ask if best_ask is not None else mid, 3)
    else:  # NO — buy NO, so price = 1 - YES book
        best_bid = features.get("best_bid")
        no_ask = (1.0 - best_bid) if best_bid is not None else None
        no_mid = 1.0 - mid
        if prefer_maker and no_ask is not None:
            # ask_ladder == no_dollars == resting NO bids directly
            no_ladder = features.get("ask_ladder") or []
            maker = _maker_level(no_ladder, no_ask,
                                 exec_cfg.get("maker_depth_cents", 2),
                                 exec_cfg.get("maker_min_volume", 100))
            if maker is not None:
                return round(maker, 3)
            return round(min(no_mid + (no_ask - no_mid) * 0.5, no_ask), 3)
        return round(no_ask if no_ask is not None else no_mid, 3)


def _maker_level(ladder: list, ref_price: float, depth_cents: int, min_vol: float) -> float | None:
    """Best resting level >= depth_cents below ref_price with size >= min_vol.
    Ladder is [[price, size], ...] ascending; scan from top of book down.

    VOLUME-PEAK RULE (VJ 2026-08-02): ALWAYS follow the volume — the market
    leans where the money sits, not where market makers bait. Choose the
    level where VOLUME CONCENTRATES (density mode), NOT the highest fillable
    level and NOT the size-weighted mean. A thin bid at the top of the book
    is bait; the wall of size is the real lean. Bimodal books: a deep tail
    (e.g. 0.01 x 2018) drags the arithmetic mean away from the money —
    use the density peak (level with max neighborhood volume) instead.

    TRASH-FLOOR FILTER (VJ 2026-08-03, AFFO lesson): before density mode,
    drop levels below `max(0.05, 0.25 × ref_price)`. Deep near-zero bids
    (0.01 x 533 on a 0.25 book) are lottery/floor liquidity, NOT directional
    lean — they out-volume the real wall and corrupt the density peak.
    AFFO: floor 0.0625 drops 0.01-0.05, wall 0.13 x 104 wins (VJ filled
    13c; a naive density peak picked 0.01). COMM: floor 0.10 keeps the
    0.10-0.14 wall. Brent: floor 0.12 drops the 0.01 tail, wall 0.45 wins.

    Implementation: for each qualifying level, sum sizes of all levels within
    ±3c (the cluster), pick the level with the maximum neighborhood volume
    (the collective intelligence). Ties -> cheaper level (more edge as maker).
    """
    if not ladder or ref_price is None:
        return None
    thresh = round(ref_price - depth_cents / 100.0, 3)
    floor = max(0.05, 0.25 * float(ref_price))
    # qualifying levels (>= threshold, above trash floor, enough size)
    levels = []
    for p, s in ladder:
        try:
            price = float(p)
            size = float(s)
        except (TypeError, ValueError):
            continue
        if price <= thresh and price >= floor and size >= min_vol:
            levels.append((price, size))
    if not levels:
        return None

    # density mode: max neighborhood volume within +-0.03 of each level
    band = 0.03
    best = None
    best_vol = -1.0
    for p, s in levels:
        vol_nb = sum(ss for pp, ss in levels if abs(pp - p) <= band)
        # prefer bigger neighborhood volume; tie -> cheaper price
        if vol_nb > best_vol or (vol_nb == best_vol and (best is None or p < best)):
            best_vol = vol_nb
            best = p
    return best
