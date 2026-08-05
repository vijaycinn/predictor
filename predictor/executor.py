"""Trade execution: paper fills (deterministic) + live Kalshi orders.

Order lifecycle (both modes): BUY -> RESTING (maker, at limit) or OPEN
(crossed); reconcile pass re-checks RESTING orders each scan -> fills when the
market comes to the limit, cancels after TTL. Positions close at resolution or
manual `close` (no stop-loss: high-risk/high-reward events, per VJ).
"""
from __future__ import annotations

import os
import time

from . import db


def _order_ttl(cfg: dict) -> float:
    # VJ rule: max 24h order lifetime — never longer (exchange + DB aligned)
    return min(cfg.get("execution", {}).get("order_ttl_hours", 24.0), 24.0) * 3600


def _event_aware_ttl(cfg: dict, features: dict) -> float:
    """TTL respecting event life: min(24h cap, 0.8 * hours_to_expiry) so at
    least 20% of the event's remaining time survives the order (VJ rule)."""
    base = _order_ttl(cfg)
    hte = float(features.get("hours_to_expiry") or 0)
    if hte > 0:
        return min(base, 0.8 * hte * 3600)
    return base


class PaperExecutor:
    """Deterministic paper fills. BUY at limit: fills at limit if limit >= ask
    (crossed), partial by depth; otherwise rests unfilled (maker)."""

    def __init__(self, conn, cfg: dict):
        self.conn = conn
        self.cfg = cfg

    def execute(self, sig: dict, size: float, limit: float, features: dict) -> dict:
        side = sig["side"]
        best_ask = None
        no_ask = None
        if side == "YES":
            best_ask = features.get("best_ask")
            ask_depth = features.get("ask_depth", 0.0)
            crossed = best_ask is not None and limit >= best_ask
        else:
            # NO: equivalent price = 1 - YES book; NO ask = 1 - best YES bid
            best_bid = features.get("best_bid")
            bid_depth = features.get("bid_depth", 0.0)
            no_ask = (1.0 - best_bid) if best_bid is not None else None
            crossed = no_ask is not None and limit >= no_ask

        if crossed:
            fill_price = best_ask if side == "YES" else no_ask
            depth = ask_depth if side == "YES" else bid_depth
            fill_size = min(size, max(depth, 0.0))
            status = "OPEN" if fill_size >= size else "PARTIAL"
        else:
            fill_price = None
            fill_size = 0.0
            status = "RESTING"

        mid = features.get("mid")
        slippage = (fill_price - mid) if (fill_price is not None and mid is not None) else None

        trade = {
            "signal_id": sig.get("signal_id"),
            "condition_id": sig["condition_id"],
            "side": side,
            "action": "BUY",
            "size": fill_size,
            "requested_size": size,
            "filled_size": fill_size,
            "limit_price": limit,
            "fill_price": fill_price,
            "slippage": slippage,
            "status": status,
            "order_status": "LIVE" if status == "RESTING" else "FILLED",
            "ttl_expires_at": time.time() + _event_aware_ttl(self.cfg, features),
            "created_at": time.time(),
        }
        trade["id"] = db.insert_trade(self.conn, trade)
        return trade


class LiveExecutor:
    """Live execution. Kalshi only for now (internal wallet — no external
    wallet/gas needed). Polymarket live requires POLYMARKET_PRIVATE_KEY wiring.

    HARD RULES:
    - NO MARGIN TRADING EVER. Only fully cash-collateralized binary event
      contracts. Never place margin/leveraged orders, never touch perps/futures.
    - Every order sized <= risk.max_trade_usd ($2) by the scanner.
    - Limit orders only (GTC), reconciled each scan; cancelled on TTL expiry.
    - No stop-loss (per VJ): prediction markets = high risk/reward events.
    """

    def __init__(self, conn, cfg: dict):
        from .risk import assert_no_margin
        assert_no_margin(cfg)  # duplicate guard: config cannot enable margin
        venue = cfg.get("venue", "polymarket")
        if venue != "kalshi":
            raise RuntimeError(
                "LiveExecutor: only Kalshi live is wired (internal wallet). "
                "Polymarket live needs POLYMARKET_PRIVATE_KEY + gas wallet."
            )
        from . import kalshi
        if not (kalshi.auth_ready()["KALSHI_API_KEY"] and kalshi.auth_ready()["KALSHI_PRIVATE_KEY"]):
            raise RuntimeError("LiveExecutor (kalshi) requires KALSHI_API_KEY + KALSHI_PRIVATE_KEY env vars.")
        self.conn = conn
        self.cfg = cfg
        self.kalshi = kalshi

    def execute(self, sig: dict, size: float, limit: float, features: dict) -> dict:
        """Place real GTC limit order on Kalshi. Returns local trade record.

        HARD RULES (VJ 2026-08-02):
        - LIMIT ORDERS ONLY. No market orders, ever. limit must be a positive
          finite price; missing/None limit raises (never converts to market).
        - PRICE BAND: never buy YES above max_buy_price_cents (40c) unless
          override_price_band set (Donski incident: approved 0.34 underdog,
          stale book repriced to 0.93, order filled at 0.90).
        - RAISE GUARD: never pay more than max_price_raise_pct (10%) above the
          approved/reference price (sig.ev_calc.price_side or approved_price).
          Resting BELOW approved is always fine — that's the maker edge.
        - LIVE FLOOR: NEVER bet if outcome probability < min_win_prob (50%).
          Applies to ALL YES buys. Probability must be independently established
          (Polymarket cross-venue = arb, or verifiable research), carried in
          sig.approved_price / ev_calc.price_side. Kalshi's own book is NOT a
          valid source. Missing or <50% ref = refused (override_win_floor only
          with explicit user confirmation).
        """
        from .risk import MarginTradingError  # noqa: F401 (margin guard asserted inside pre_flight)
        from . import risk as risk_mod
        # CONSOLIDATED GATE (VJ 2026-08-02): every execution path runs ALL rules.
        risk_mod.pre_flight_check(sig, limit, self.cfg)
        ticker = sig["condition_id"]
        # WALL CHECK (VJ 2026-08-05, Ribecai lesson): limit must rest at the
        # volume-weighted wall of the FULL ladder — never above it. Top-10
        # snapshots lie; the money sits at the full-ladder density peak.
        # VJ override via sig['override_wall_check'] (explicit bypass only).
        if not sig.get("override_wall_check"):
            full_book = self.kalshi.get_orderbook_full(ticker)
            if sig.get("side") == "YES":
                ladder = full_book.get("yes_dollars") or []
            else:
                ladder = full_book.get("no_dollars") or []
            if ladder:
                risk_mod.wall_check(limit, sig.get("side") or "YES", ladder, self.cfg)
        hours_to_expiry = float(features.get("hours_to_expiry") or 0)
        resp = self.kalshi.place_order(ticker, sig["side"], size, limit, hours_to_expiry=hours_to_expiry)
        order = resp.get("order") or resp
        order_id = order.get("order_id") or resp.get("order_id")
        if not order_id:
            raise RuntimeError(f"Kalshi order placement returned no order_id: {resp}")
        order_status = str(order.get("status", "resting")).lower()

        if order_status == "filled":
            status = "OPEN"
            fill_price = float(order.get("average_fill_price") or order.get("price") or limit)
        elif order_status in ("canceled", "cancelled", "expired"):
            status = "CANCELED"
            fill_price = None
        else:  # resting
            status = "RESTING"
            fill_price = None

        trade = {
            "signal_id": sig.get("signal_id"),
            "condition_id": ticker,
            "side": sig["side"],
            "action": "BUY",
            "size": float(order.get("filled_count") or 0) if status in ("OPEN", "PARTIAL") else 0.0,
            "requested_size": size,
            "filled_size": float(order.get("filled_count") or 0),
            "limit_price": limit,
            "fill_price": fill_price,
            "slippage": None,
            "status": status,
            "order_status": order_status,
            "exchange_order_id": order_id,
            "ttl_expires_at": time.time() + _event_aware_ttl(self.cfg, features),
            "created_at": time.time(),
        }
        trade["id"] = db.insert_trade(self.conn, trade)
        return trade

    def cancel(self, trade_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row or not row["exchange_order_id"]:
            return {"ok": False, "error": f"trade #{trade_id} has no exchange order id"}
        resp = self.kalshi.cancel_order(row["exchange_order_id"])
        db.update_trade(self.conn, trade_id, {"status": "CANCELED", "order_status": "canceled"})
        return {"ok": True, "cancel_response": resp}


class PolymarketUSExecutor:
    """Live execution on Polymarket US (US-regulated venue, Ed25519 API keys).

    SAME approval gates as Kalshi (VJ 2026-08-05): every placement runs
    risk.pre_flight_check (limit-only, win floor >= 50% from independent
    source, YES <= 40c band, <= 10% raise above approved, no margin) +
    risk.wall_check (full-ladder volume wall) + risk.check_risk_limits
    (position caps). pmxt is ANALYSIS ONLY for this venue — its PolymarketUS
    class signs EIP-712 with an ETH private key, incompatible with Polymarket
    US Ed25519 API keys. Transport: polymarket_us.py.

    TTL: default 1h (event-aware), mapped to TIME_IN_FORCE_GOOD_TILL_DATE.
    Maker-only (participateDontInitiate) to match VJ's maker-entry pattern.
    """

    def __init__(self, conn, cfg: dict):
        from .risk import assert_no_margin
        assert_no_margin(cfg)  # duplicate guard: config cannot enable margin
        from . import polymarket_us
        if not (polymarket_us.get_key_id() and polymarket_us.get_secret()):
            raise RuntimeError(
                "PolymarketUSExecutor requires POLYMARKET_API_KEY + "
                "POLYMARKET_SECRET_KEY env vars (Ed25519 key ID + base64 secret)."
            )
        self.conn = conn
        self.cfg = cfg
        self.pmus = polymarket_us

    def _ladder(self, slug: str, side: str):
        """Full YES/NO ladders from the gateway book.

        Book bids = resting YES bid levels; offers = resting YES ask levels.
        NO bid levels = 1 - offer px (binary equivalence, same as Kalshi's
        no_dollars = ask_ladder convention). Returns [[price, size], ...].
        px entries are {value, currency} objects; qty is a number/string."""
        book = self.pmus.get_book(slug)
        md = book.get("marketData", {})

        def _px(x):
            p = x.get("px")
            if isinstance(p, dict):
                p = p.get("value")
            return float(p)

        bids = [[_px(x), float(x.get("qty") or 0)] for x in md.get("bids", [])
                if x.get("px") is not None]
        offers = [[1.0 - _px(x), float(x.get("qty") or 0)] for x in md.get("offers", [])
                  if x.get("px") is not None]
        return (bids if side == "YES" else offers), md

    def execute(self, sig: dict, size: float, limit: float, features: dict) -> dict:
        """Place real limit order on Polymarket US after ALL Kalshi gates."""
        from . import risk as risk_mod
        # CONSOLIDATED GATE (VJ 2026-08-02): same rules as Kalshi, no path skips.
        risk_mod.pre_flight_check(sig, limit, self.cfg)
        slug = sig["condition_id"]
        side = sig["side"] or "YES"

        # WALL CHECK (VJ 2026-08-05): full-ladder volume wall, never above.
        if not sig.get("override_wall_check"):
            ladder, md = self._ladder(slug, side)
            if ladder:
                risk_mod.wall_check(limit, side, ladder, self.cfg)

        # portfolio caps (live)
        price_side = sig.get("ev_calc", {}).get("price_side") or limit
        ok, reason = risk_mod.check_risk_limits(self.conn, sig, price_side * size, self.cfg)
        if not ok:
            raise RuntimeError(f"RISK LIMITS: {reason}")

        # TTL: 1h default / event-aware, cap 24h -> GOOD_TILL_DATE
        ttl = _event_aware_ttl(self.cfg, features)
        good_till = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl))

        payload = self.pmus.place_limit(
            slug, side, "BUY", size, limit,
            tif="TIME_IN_FORCE_GOOD_TILL_DATE",
            good_till_time=good_till,
            maker_only=True,
        )
        resp = self.pmus.place_order(payload)
        order_id = resp.get("id")
        if not order_id:
            raise RuntimeError(f"Polymarket US order placement returned no id: {resp}")

        executions = resp.get("executions") or []
        if executions:
            last = executions[-1]
            filled = float(last.get("lastShares") or size)
            fill_px = float(last.get("lastPx", {}).get("value") or limit)
            status = "OPEN" if filled >= size else "PARTIAL"
        else:
            filled = 0.0
            fill_px = None
            status = "RESTING"

        trade = {
            "signal_id": sig.get("signal_id"),
            "condition_id": slug,
            "side": side,
            "action": "BUY",
            "size": filled,
            "requested_size": size,
            "filled_size": filled,
            "limit_price": limit,
            "fill_price": fill_px,
            "slippage": None,
            "status": status,
            "order_status": "filled" if executions else "resting",
            "exchange_order_id": order_id,
            "ttl_expires_at": time.time() + ttl,
            "created_at": time.time(),
        }
        trade["id"] = db.insert_trade(self.conn, trade)
        return trade

    def cancel(self, trade_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row or not row["exchange_order_id"]:
            return {"ok": False, "error": f"trade #{trade_id} has no exchange order id"}
        resp = self.pmus.cancel_order(row["exchange_order_id"], row["condition_id"])
        db.update_trade(self.conn, trade_id, {"status": "CANCELED", "order_status": "canceled"})
        return {"ok": True, "cancel_response": resp}


def make_executor(conn, cfg: dict):
    mode = cfg.get("mode", "paper")
    if mode != "live":
        return PaperExecutor(conn, cfg)
    venue = cfg.get("venue", "polymarket")
    if venue == "kalshi":
        return LiveExecutor(conn, cfg)
    if venue == "polymarket_us":
        return PolymarketUSExecutor(conn, cfg)
    raise RuntimeError(f"live venue '{venue}' not wired (kalshi, polymarket_us)")



def reconcile_orders(conn, cfg: dict) -> list[dict]:
    """Order lifecycle pass: fill/cancel RESTING orders.

    Paper: re-fetch book; fill if limit crossed, cancel after TTL.
    Live (kalshi): query exchange order status; update accordingly, cancel on TTL.
    Returns list of lifecycle events for reporting.
    """
    from . import risk as risk_mod
    risk_mod.assert_no_margin(cfg)
    from .scanner import get_venue
    ing = get_venue(cfg)
    events = []
    now = time.time()

    if cfg.get("mode") == "live":
        if cfg.get("venue") == "polymarket_us":
            from . import polymarket_us as pmus
            open_orders = pmus.get_open_orders().get("orders") or []
            by_id = {o["id"]: o for o in open_orders}
            for t in db.resting_orders(conn):
                oid = t.get("exchange_order_id")
                if not oid:
                    continue
                remote = by_id.get(oid)
                if remote is None:
                    try:
                        remote = pmus.get_order(oid)
                    except Exception:
                        remote = None
                if remote:
                    cum = float(remote.get("cumQuantity") or 0)
                    leaves = float(remote.get("leavesQuantity") or 0)
                    avg = remote.get("avgPx", {}).get("value")
                    if cum > 0:
                        fill = float(avg) if avg else float(t["limit_price"])
                        db.update_trade(conn, t["id"], {
                            "status": "OPEN" if leaves <= 0 else "PARTIAL",
                            "order_status": "filled",
                            "fill_price": fill,
                            "filled_size": cum,
                            "size": cum,
                        })
                        events.append({"trade_id": t["id"], "event": "filled", "fill_price": fill})
                        continue
                    # still resting with leaves -> not terminal
                    continue
                # not on exchange anymore: check order detail
                try:
                    det = pmus.get_order(oid)
                    cum = float(det.get("cumQuantity") or 0)
                    state = str(det.get("state") or "")
                    if cum > 0:
                        avg = det.get("avgPx", {}).get("value")
                        fill = float(avg) if avg else float(t["limit_price"])
                        db.update_trade(conn, t["id"], {
                            "status": "OPEN", "order_status": "filled",
                            "fill_price": fill, "filled_size": cum, "size": cum,
                        })
                        events.append({"trade_id": t["id"], "event": "filled", "fill_price": fill})
                    elif "CANCEL" in state.upper() or "EXPIR" in state.upper() or "REJECT" in state.upper():
                        db.update_trade(conn, t["id"], {"status": "CANCELED", "order_status": "canceled_remote"})
                        events.append({"trade_id": t["id"], "event": "canceled_remote"})
                    continue
                except Exception:
                    pass
                # TTL expiry -> cancel
                ttl = t.get("ttl_expires_at") or (now + 3600)
                if ttl < now:
                    try:
                        pmus.cancel_order(oid, t["condition_id"])
                    except Exception:
                        pass
                    db.update_trade(conn, t["id"], {"status": "CANCELED", "order_status": "canceled_ttl"})
                    events.append({"trade_id": t["id"], "event": "canceled_ttl"})
            return events
        from . import kalshi

        orders = kalshi.get_orders(status="resting")
        by_id = {o["order_id"]: o for o in orders}
        for t in db.resting_orders(conn):
            oid = t.get("exchange_order_id")
            if not oid:
                continue
            remote = by_id.get(oid)
            if remote is None:
                # order no longer resting remotely — refetch single
                try:
                    remote = kalshi.get_order(oid)
                except Exception:
                    remote = None
            if remote:
                rstatus = str(remote.get("status", "")).lower()
                # Kalshi V2 returns "executed" for filled orders (observed live)
                if rstatus in ("filled", "executed"):
                    fill = float(remote.get("average_fill_price") or remote.get("price") or t["limit_price"])
                    filled = float(remote.get("filled_count") or t["requested_size"] or 0)
                    db.update_trade(conn, t["id"], {
                        "status": "OPEN", "order_status": "filled", "fill_price": fill,
                        "filled_size": filled, "size": filled,
                    })
                    events.append({"trade_id": t["id"], "event": "filled", "fill_price": fill})
                elif rstatus in ("canceled", "cancelled", "expired"):
                    db.update_trade(conn, t["id"], {"status": "CANCELED", "order_status": rstatus})
                    events.append({"trade_id": t["id"], "event": "canceled_remote"})
                if rstatus in ("filled", "executed", "canceled", "cancelled", "expired"):
                    # terminal state — never TTL-cancel a settled order
                    continue
            # TTL expiry → cancel (only for orders still resting remotely or unknown)
            ttl = t.get("ttl_expires_at")
            ttl = ttl if ttl is not None else (now + 3600)
            if ttl < now:
                try:
                    kalshi.cancel_order(oid)
                except Exception:
                    pass
                db.update_trade(conn, t["id"], {"status": "CANCELED", "order_status": "canceled_ttl"})
                events.append({"trade_id": t["id"], "event": "canceled_ttl"})
    else:
        # paper: re-check books
        for t in db.resting_orders(conn):
            ttl = t.get("ttl_expires_at")
            ttl = ttl if ttl is not None else (now + 3600)
            if ttl < now:
                db.update_trade(conn, t["id"], {"status": "CANCELED", "order_status": "canceled_ttl"})
                events.append({"trade_id": t["id"], "event": "canceled_ttl"})
                continue
            try:
                book = ing.fetch_orderbook(t["condition_id"] if cfg.get("venue") == "kalshi" else t["condition_id"])
                if book.get("best_bid") is None:
                    continue
                limit = t["limit_price"]
                side = t["side"]
                if side == "YES":
                    ask = book.get("best_ask")
                    if ask is not None and limit >= ask:
                        fill = ask
                    else:
                        continue
                else:
                    bid = book.get("best_bid")
                    no_ask = (1.0 - bid) if bid is not None else None
                    if no_ask is not None and limit >= no_ask:
                        fill = no_ask
                    else:
                        continue
                db.update_trade(conn, t["id"], {
                    "status": "OPEN", "order_status": "filled", "fill_price": fill,
                    "filled_size": t["requested_size"] or t["size"], "size": t["requested_size"] or t["size"],
                    "slippage": fill - (book.get("mid") or fill),
                })
                events.append({"trade_id": t["id"], "event": "filled", "fill_price": fill})
            except Exception:
                continue
    return events
