"""Signal generation: calibrated probability blend, confidence tiers, fee-aware EV."""
from __future__ import annotations

import math


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def estimate_probability(features: dict, cfg: dict, llm_prob_yes: float | None = None) -> tuple[float, dict]:
    """Blend market price, orderbook, momentum, base rate, sentiment, optional LLM.

    Returns (prob_yes, component_dict) where component_dict tracks each input for
    transparency and disagreement-based confidence.
    """
    prob = cfg.get("prob", {})
    p_lo = prob.get("min_prob", 0.01)
    p_hi = prob.get("max_prob", 0.99)

    mid = features.get("mid")
    if mid is None:
        mid = 0.5  # degenerate market; caller should filter, but stay safe

    # 1. market price — efficient baseline
    p_market = _clip(mid, p_lo, p_hi)

    # 2. orderbook imbalance adjustment
    imb = features.get("imbalance", 0.0) or 0.0
    scale_imb = prob.get("book_imbalance_scale", 0.03)
    p_book = _clip(p_market + imb * scale_imb, p_lo, p_hi)

    # 3. momentum adjustment (trend following, capped)
    mom = features.get("momentum", 0.0) or 0.0
    scale_mom = prob.get("momentum_scale", 0.10)
    p_mom = _clip(p_market + mom * scale_mom, p_lo, p_hi)

    # 4. base rate: mean of historical prices over lookback
    hist_mean = None
    n = features.get("price_samples", 0)
    if n >= 3 and features.get("mid") is not None:
        # momentum_pct unavailable; recompute cheap proxy from features we kept
        hist_mean = _clip(p_market - (features.get("momentum") or 0.0) / 2.0, p_lo, p_hi)
    p_base = hist_mean if hist_mean is not None else p_market

    # 5. sentiment (trade flow tilt)
    flow = features.get("trade_flow", 0.0) or 0.0
    p_sent = _clip(p_market + flow * 0.02, p_lo, p_hi)

    # 6. LLM override
    p_llm = _clip(llm_prob_yes, p_lo, p_hi) if llm_prob_yes is not None else None

    w_market = prob.get("market_price_weight", 0.55)
    w_book = prob.get("orderbook_weight", 0.15)
    w_mom = prob.get("momentum_weight", 0.10)
    w_base = prob.get("base_rate_weight", 0.05)
    w_sent = prob.get("sentiment_weight", 0.05)
    w_llm = prob.get("llm_weight", 0.10)

    total_w = w_market + w_book + w_mom + w_base + w_sent
    if p_llm is not None:
        total_w += w_llm
    else:
        total_w += w_llm  # redistribute LLM weight to market price when absent
        w_market += w_llm

    prob_yes = (
        w_market * p_market + w_book * p_book + w_mom * p_mom
        + w_base * p_base + w_sent * p_sent
    )
    if p_llm is not None:
        prob_yes += w_llm * p_llm
    prob_yes = _clip(prob_yes / total_w, p_lo, p_hi)

    components = {
        "p_market": p_market,
        "p_book": p_book,
        "p_momentum": p_mom,
        "p_base_rate": p_base,
        "p_sentiment": p_sent,
        "p_llm": p_llm,
        "prob_yes": prob_yes,
    }
    return prob_yes, components


def confidence_score(features: dict, components: dict, prob_yes: float, cfg: dict) -> tuple[float, str]:
    """0-1 confidence + LOW/MEDIUM/HIGH tier from liquidity, agreement, freshness."""
    score = 0.5

    # liquidity bonus
    spread = features.get("spread")
    if spread is not None and spread > 0:
        if spread <= 0.01:
            score += 0.12
        elif spread <= 0.02:
            score += 0.07
        elif spread <= 0.035:
            score += 0.03

    depth = features.get("depth_total", 0.0) or 0.0
    if depth >= 5000:
        score += 0.08
    elif depth >= 1000:
        score += 0.05
    elif depth >= 200:
        score += 0.02

    # agreement among probability components (disagreement penalty)
    vals = [v for k, v in components.items() if k != "prob_yes" and v is not None]
    if len(vals) >= 3:
        spread_comp = max(vals) - min(vals)
        if spread_comp <= 0.02:
            score += 0.10
        elif spread_comp <= 0.05:
            score += 0.04
        elif spread_comp > 0.12:
            score -= 0.15

    # freshness penalty
    hrs = features.get("hours_since_last_trade")
    if hrs is not None:
        if hrs > 24:
            score -= 0.20
        elif hrs > 6:
            score -= 0.08

    # history depth penalty
    n = features.get("price_samples", 0)
    if n < 10:
        score -= 0.10

    # boundary penalty (degenerate near 0/1)
    if prob_yes <= 0.03 or prob_yes >= 0.97:
        score -= 0.15

    score = _clip(score, 0.05, 0.97)
    if score >= 0.7:
        tier = "HIGH"
    elif score >= 0.5:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return round(score, 3), tier


def compute_ev(features: dict, prob_yes: float, side: str, market_price: float, cfg: dict, market: dict | None = None) -> dict:
    """Fee-aware EV per share. side in {YES, NO}; action BUY assumed for new trades.

    EV_raw = estimated_prob - price for the side being bought.
    EV_net  = EV_raw - taker/maker fee - estimated slippage.
    Uses per-market fee schedule when market has feesEnabled; else config fees.
    """
    fees = cfg.get("fees", {})
    exec_cfg = cfg.get("execution", {})
    prob_side = prob_yes if side == "YES" else (1.0 - prob_yes)
    price_side = market_price if side == "YES" else (1.0 - market_price)

    ev_raw = prob_side - price_side

    prefer_maker = exec_cfg.get("prefer_maker", True)
    if market and market.get("fees_enabled"):
        # Polymarket fee: fee = shares x feeRate x p x (1-p); feeRate in bps
        rate_bps = (market.get("maker_base_fee") or 0.0) if prefer_maker else (market.get("taker_base_fee") or 0.0)
        fee_per_share = (rate_bps / 10000.0) * price_side * (1.0 - price_side)
    else:
        fee_per_share = fees.get("maker_fee_per_share", 0.0) if prefer_maker else fees.get("taker_fee_per_share", 0.0)

    spread = features.get("spread")
    agg = exec_cfg.get("aggressiveness", 0.5)
    # maker: fill at our limit, no spread cost (may not fill). taker: pay half spread * aggressiveness.
    if prefer_maker:
        slippage = 0.0
        est_fill = price_side  # at limit, assume maker fill at price
    else:
        half_spread = (spread / 2.0) if spread else 0.01
        slippage = half_spread * agg
        est_fill = price_side + slippage

    ev_net = ev_raw - fee_per_share - slippage
    payoff_if_correct = (1.0 - price_side) - fee_per_share - slippage
    loss_if_wrong = price_side + fee_per_share + slippage

    return {
        "prob_side": prob_side,
        "price_side": price_side,
        "ev_raw": round(ev_raw, 5),
        "ev_net": round(ev_net, 5),
        "fee_per_share": fee_per_share,
        "slippage_est": round(slippage, 5),
        "est_fill_price": round(est_fill, 4),
        "payoff_if_correct": round(payoff_if_correct, 5),
        "loss_if_wrong": round(loss_if_wrong, 5),
    }


def build_signal(
    market: dict,
    features: dict,
    llm_prob_yes: float | None,
    cfg: dict,
) -> dict:
    """Full structured signal for a market. action: BUY/SELL/HOLD/SKIP."""
    prob_yes, components = estimate_probability(features, cfg, llm_prob_yes)
    conf, tier = confidence_score(features, components, prob_yes, cfg)

    mid = features.get("mid")
    if mid is None:
        return {
            "condition_id": market["condition_id"], "side": None, "action": "SKIP",
            "prob_yes": prob_yes, "confidence": conf, "confidence_tier": tier,
            "ev_raw": None, "ev_net": None, "edge": 0.0, "market_price": None,
            "reasoning": "No midpoint (illiquid/degenerate book).", "metrics_snapshot": features,
        }

    best_side = None
    best_ev = 0.0
    best_ev_calc = None
    for side in ("YES", "NO"):
        ev = compute_ev(features, prob_yes, side, mid, cfg, market)
        if ev["ev_net"] > best_ev:
            best_ev = ev["ev_net"]
            best_side = side
            best_ev_calc = ev

    edge = abs(prob_yes - mid)
    min_edge = cfg.get("execution", {}).get("min_edge", 0.03)
    ev_min = cfg.get("execution", {}).get("ev_min_net", 0.02)

    drivers = []
    if features.get("imbalance") is not None and abs(features.get("imbalance", 0)) > 0.15:
        drivers.append(f"book imbalance {features['imbalance']:+.2f}")
    if abs(features.get("momentum", 0)) > 0.01:
        drivers.append(f"momentum {features['momentum']:+.3f}")
    if abs(features.get("trade_flow", 0)) > 0.2:
        drivers.append(f"flow {features['trade_flow']:+.2f}")
    if llm_prob_yes is not None:
        drivers.append(f"llm {llm_prob_yes:.2f}")

    if edge < min_edge or best_ev < ev_min:
        action = "HOLD" if edge >= min_edge * 0.5 else "SKIP"
        reasoning = (
            f"edge {edge:.3f} below min {min_edge:.2f}" if edge < min_edge
            else f"EV_net {best_ev:.4f} below min {ev_min:.2f}"
        )
    else:
        action = "BUY"

    if best_ev_calc is None:
        best_ev_calc = {"ev_net": 0.0, "ev_raw": 0.0, "slippage_est": 0.0, "fee_per_share": 0.0}

    if action == "BUY":
        reasoning = f"{best_side} at ~{best_ev_calc['est_fill_price']:.2f}: est P({best_side}) {best_ev_calc['prob_side']:.2f} vs price {best_ev_calc['price_side']:.2f}" + (f"; {'; '.join(drivers)}" if drivers else "")

    return {
        "condition_id": market["condition_id"],
        "side": best_side if action == "BUY" else None,
        "action": action,
        "prob_yes": round(prob_yes, 4),
        "confidence": conf,
        "confidence_tier": tier,
        "ev_raw": round(best_ev_calc["ev_raw"], 5),
        "ev_net": round(best_ev_calc["ev_net"], 5),
        "edge": round(edge, 4),
        "market_price": mid,
        "reasoning": reasoning,
        "metrics_snapshot": features,
        "components": components,
        "ev_calc": best_ev_calc,
    }
