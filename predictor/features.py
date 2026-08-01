"""Feature construction: price, orderbook, sentiment, time vectors per market."""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timezone


def _pct(a: float, b: float) -> float:
    if b is None or b == 0:
        return 0.0
    return (a - b) / b


def hours_to_expiry(end_date: str | None, now: float | None = None) -> float | None:
    if not end_date:
        return None
    try:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = now or time.time()
        return (dt.timestamp() - now) / 3600.0
    except (ValueError, TypeError):
        return None


def build_features(
    market: dict,
    book: dict,
    history: list[dict],
    recent_trades: list[dict],
    oi: float,
    cfg: dict,
) -> dict:
    prob = cfg.get("prob", {})
    now = time.time()

    # --- price features ---
    best_bid = book.get("best_bid")
    best_ask = book.get("best_ask")
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0
    elif best_bid is not None:
        mid = best_bid
    elif best_ask is not None:
        mid = best_ask
    spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None

    prices = [float(h["p"]) for h in history if h.get("p") is not None]
    prices = [p for p in prices if 0.0 <= p <= 1.0]

    momentum = 0.0
    vol_hist = 0.0
    if len(prices) >= 3:
        lookback = int(prob.get("momentum_lookback", 24))
        recent = prices[-lookback:]
        ref = recent[0]
        last = recent[-1]
        momentum = last - ref
        vol_hist = statistics.pstdev(recent) if len(recent) > 2 else 0.0

    # --- orderbook features ---
    bid_depth = book.get("bid_depth", 0.0)
    ask_depth = book.get("ask_depth", 0.0)
    depth_total = bid_depth + ask_depth
    imbalance = 0.0
    if depth_total > 0:
        imbalance = (bid_depth - ask_depth) / depth_total

    # --- sentiment (market-internal proxies) ---
    recent_trades = recent_trades or []
    buy_vol = sum(float(t.get("size", 0)) for t in recent_trades if str(t.get("side", "")).upper() == "BUY")
    sell_vol = sum(float(t.get("size", 0)) for t in recent_trades if str(t.get("side", "")).upper() == "SELL")
    flow_total = buy_vol + sell_vol
    trade_flow = 0.0
    if flow_total > 0:
        trade_flow = (buy_vol - sell_vol) / flow_total  # +1 all buys, -1 all sells

    newest_ts = max((float(t.get("timestamp", 0)) for t in recent_trades), default=0)
    hours_since_last_trade = (now - newest_ts) / 3600.0 if newest_ts else None

    # --- time features ---
    hte = hours_to_expiry(market.get("end_date"), now)

    return {
        "mid": mid,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_pct": _pct(spread, mid) if spread is not None and mid else None,
        "last_trade_price": book.get("last_trade_price"),
        "momentum": momentum,
        "momentum_pct": _pct(prices[-1], prices[0]) if len(prices) >= 3 else None,
        "price_volatility": vol_hist,
        "price_samples": len(prices),
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "depth_total": depth_total,
        "imbalance": imbalance,
        "top_bid_size": book.get("top_bid_size", 0.0),
        "top_ask_size": book.get("top_ask_size", 0.0),
        "trade_flow": trade_flow,
        "recent_buy_vol": buy_vol,
        "recent_sell_vol": sell_vol,
        "recent_trade_count": len(recent_trades),
        "hours_since_last_trade": hours_since_last_trade,
        "hours_to_expiry": hte,
        "days_to_expiry": (hte / 24.0) if hte is not None else None,
        "close_to_expiry": hte is not None and hte < 24,
        "volume": market.get("volume"),
        "liquidity": market.get("liquidity"),
        "open_interest": oi,
        "category": market.get("category"),
        "question": market.get("question"),
    }
