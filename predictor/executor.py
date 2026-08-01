"""Trade execution: paper fills (deterministic) + live stub (needs wallet key)."""
from __future__ import annotations

import os
import time

from . import db


class PaperExecutor:
    """Deterministic paper fills. BUY at limit: fills at limit if limit >= ask (crossed),
    partial by ask depth; otherwise rests unfilled (maker, no fill this cycle)."""

    def __init__(self, conn, cfg: dict):
        self.conn = conn
        self.cfg = cfg

    def execute(self, sig: dict, size: float, limit: float, features: dict) -> dict:
        side = sig["side"]
        if side == "YES":
            best_ask = features.get("best_ask")
            ask_depth = features.get("ask_depth", 0.0)
            crossed = best_ask is not None and limit >= best_ask
        else:
            best_bid = features.get("best_bid")
            bid_depth = features.get("bid_depth", 0.0)
            crossed = best_bid is not None and limit <= best_bid

        if crossed:
            fill_price = best_ask if side == "YES" else best_bid
            depth = ask_depth if side == "YES" else bid_depth
            fill_size = min(size, max(depth, 0.0))
            status = "OPEN" if fill_size >= size else "PARTIAL"
        else:
            fill_price = None
            fill_size = 0.0
            status = "RESTING"  # maker order not filled this cycle

        mid = features.get("mid")
        slippage = (fill_price - mid) if (fill_price is not None and mid is not None) else None

        trade = {
            "signal_id": sig.get("signal_id"),
            "condition_id": sig["condition_id"],
            "side": side,
            "action": "BUY",
            "size": fill_size,
            "limit_price": limit,
            "fill_price": fill_price,
            "slippage": slippage,
            "status": status,
            "created_at": time.time(),
        }
        if status in ("OPEN", "PARTIAL"):
            trade["id"] = db.insert_trade(self.conn, trade)
        else:
            # RESTING orders: log as trade row for transparency but not an open position
            trade["status"] = "RESTING"
            trade["id"] = db.insert_trade(self.conn, trade)
        return trade


class LiveExecutor:
    """Live execution via py-clob-client. Requires POLYMARKET_PRIVATE_KEY + wallet env.
    Not installed/configured by default — paper mode is the safe default."""

    def __init__(self, conn, cfg: dict):
        key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        if not key:
            raise RuntimeError(
                "LiveExecutor requires POLYMARKET_PRIVATE_KEY env var. "
                "Stay in paper mode until configured."
            )
        self.conn = conn
        self.cfg = cfg
        # TODO: init py_clob_client here once wallet funded

    def execute(self, sig: dict, size: float, limit: float, features: dict) -> dict:
        raise NotImplementedError("Live execution not yet wired. Paper mode only.")


def make_executor(conn, cfg: dict):
    mode = cfg.get("mode", "paper")
    if mode == "live":
        return LiveExecutor(conn, cfg)
    return PaperExecutor(conn, cfg)
