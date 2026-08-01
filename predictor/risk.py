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
    NO side trades at 1 - YES book (Kalshi/Polymarket binary equivalence)."""
    ev_calc = sig.get("ev_calc", {})
    side = sig.get("side")
    mid = features.get("mid") or ev_calc.get("price_side")
    exec_cfg = cfg.get("execution", {})
    prefer_maker = exec_cfg.get("prefer_maker", True)

    if side == "YES":
        best_ask = features.get("best_ask")
        if prefer_maker and best_ask is not None:
            return round(min(mid + (best_ask - mid) * 0.5, best_ask), 3)
        return round(best_ask if best_ask is not None else mid, 3)
    else:  # NO — buy NO, so price = 1 - YES book
        best_bid = features.get("best_bid")
        no_ask = (1.0 - best_bid) if best_bid is not None else None
        no_mid = 1.0 - mid
        if prefer_maker and no_ask is not None:
            return round(min(no_mid + (no_ask - no_mid) * 0.5, no_ask), 3)
        return round(no_ask if no_ask is not None else no_mid, 3)
