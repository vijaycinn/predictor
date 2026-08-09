#!/usr/bin/env python3
"""exit_watcher.py — take-profit exit watcher via Kalshi WS fill callbacks.

Watches open positions in BOTH directions (YES longs qty>0, NO shorts qty<0).
Subscribes WS `fill` channel for all open tickers. On fill event:
  - match order to position, classify direction
  - log + optional Telegram alert

Usage:
  exit_watcher.py --once --seconds 30        # connect, subscribe, watch, report, exit
  exit_watcher.py --daemon                   # run forever (background / cron)
  exit_watcher.py --test                     # self-test: tiny buy+sell round trip, verify fill events
  exit_watcher.py --alert                    # send Telegram alerts on fills (with --daemon/--once)
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time

import websockets

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

def _repo_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here.endswith("scripts") and os.path.basename(os.path.dirname(here)) == ".hermes":
        repo = "/data/workspace/predictor"
        return repo if os.path.isdir(os.path.join(repo, "predictor")) else None
    return os.path.dirname(here)

REPO = _repo_path()
if REPO:
    sys.path.insert(0, REPO)

from predictor import kalshi  # noqa: E402


def load_env():
    for line in open("/data/.hermes/.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def auth_headers():
    """Kalshi WS auth = same RSA-PSS as REST: sign ts + METHOD + path."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = os.environ.get("KALSHI_API_KEY", "")
    priv = os.environ.get("KALSHI_PRIVATE_KEY", "")
    if not key or not priv:
        raise RuntimeError("KALSHI_API_KEY / KALSHI_PRIVATE_KEY missing")
    ts = str(int(time.time() * 1000))
    msg = f"{ts}GET/trade-api/ws/v2".encode()
    pk = serialization.load_pem_private_key(priv.encode(), password=None)
    sig = pk.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                  hashes.SHA256())
    return {
        "KALSHI-ACCESS-KEY": key,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def get_open_positions():
    """Open positions with direction. qty>0 = YES long (buy side),
    qty<0 = NO long / short YES (sell side)."""
    out = []
    for p in kalshi.get_positions():
        ticker = p.get("ticker", "")
        qty = float(p.get("position_fp") or 0)
        if qty == 0:
            continue
        entry_cost = float(p.get("total_traded_dollars") or 0)
        out.append({
            "ticker": ticker,
            "qty": qty,
            "side": "BUY" if qty > 0 else "SELL",
            "entry_cost": entry_cost,
        })
    return out


def fmt_pnl(pos, fill):
    """Approx P&L from fill vs position cost. Kalshi fills report per-contract
    yes/no price; position cost = total_traded_dollars."""
    try:
        qty = pos["qty"]
        cost = pos["entry_cost"]
        if qty == 0:
            return "n/a"
        # average entry per contract
        avg = cost / abs(qty)
        px = float(fill.get("yes_price") or fill.get("no_price") or 0)
        if pos["side"] == "BUY":
            pnl = (px - avg) * abs(qty)
        else:
            pnl = (avg - px) * abs(qty)
        return f"${pnl:.2f} (avg entry {avg:.2f}, fill px {px:.2f})"
    except Exception:
        return "n/a"


def parse_fill(data):
    """Extract fill info from a WS fill event. Field names verified live
    2026-08-09 (KXGOLDMON T4811.99 buy+sell round trip):
    msg.market_ticker, msg.yes_price_dollars (string), msg.count_fp (string),
    msg.action (buy/sell), msg.post_position_fp (string, pos after fill),
    msg.fee_cost (string), msg.is_taker, msg.ts_ms."""
    msg = data.get("msg") or {}
    return {
        "ticker": msg.get("market_ticker") or msg.get("ticker") or "",
        "order_id": msg.get("order_id") or "",
        "yes_price": msg.get("yes_price_dollars"),
        "no_price": msg.get("no_price_dollars"),
        "count": msg.get("count_fp"),
        "side": msg.get("side") or "",
        "action": msg.get("action") or "",
        "post_position": msg.get("post_position_fp"),
        "fee": msg.get("fee_cost"),
        "ts_ms": msg.get("ts_ms"),
    }


async def watch(seconds, alert=False, daemon=False):
    positions = get_open_positions()
    if not positions:
        print("no open positions")
        return
    tickers = sorted({p["ticker"] for p in positions})
    pos_by_ticker = {p["ticker"]: p for p in positions}
    print(f"watching {len(positions)} positions across {len(tickers)} tickers:")
    for p in positions:
        print(f"  {p['side']:4} {p['qty']:>8.2f} {p['ticker']}")

    while True:
        try:
            async with websockets.connect(WS_URL, max_size=2**22,
                                          additional_headers=auth_headers()) as ws:
                await ws.send(json.dumps({"id": 1, "cmd": "subscribe", "params": {
                    "channels": ["fill"], "market_tickers": tickers}}))
                print(f"subscribed fill channel @ {time.strftime('%H:%M:%S')}")
                start = time.time()
                while daemon or time.time() - start < seconds:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    mtype = data.get("type")
                    if mtype in ("error",):
                        print("WS ERROR:", raw[:300])
                        break
                    if mtype == "fill":
                        f = parse_fill(data)
                        pos = pos_by_ticker.get(f["ticker"], {})
                        pnl = fmt_pnl(pos, f) if pos else "n/a"
                        line = (f"FILL {f['ticker']} | {f.get('action','?')} {f.get('side','?')} "
                                f"count={f.get('count')} yes_px={f.get('yes_price')} "
                                f"post_pos={f.get('post_position')} fee={f.get('fee')} | pnl {pnl}")
                        print(f"[{time.strftime('%H:%M:%S')}] {line}")
                        if alert:
                            try:
                                _tg_alert(line)
                            except Exception as e:
                                print("tg alert ERR:", str(e)[:80])
                if not daemon:
                    return
        except Exception as e:
            print("WS conn ERR:", str(e)[:150])
            if not daemon:
                return
            await asyncio.sleep(5)


def _tg_alert(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def find_test_market():
    """Cheap liquid market NOT currently held — for the self-test round trip.
    Scan the gold monthly ladder for OTM strikes (ask <= 10c, OI > 1000)."""
    held = {p["ticker"] for p in get_open_positions()}
    for series in ["KXGOLDMON", "KXBTCMINMON"]:
        try:
            d = kalshi.get_json("/markets", {"series_ticker": series, "status": "open", "limit": 100})
        except Exception:
            continue
        for m in (d.get("markets") or []):
            t = m.get("ticker")
            if t in held:
                continue
            bid = float(m.get("yes_bid_dollars") or 0)
            ask = float(m.get("yes_ask_dollars") or 0)
            oi = float(m.get("open_interest_fp") or 0)
            if ask > 0 and ask <= 0.10 and oi > 1000:
                return t, bid, ask
    return None, None, None


async def self_test():
    """Place 1x buy @ ask (fills), then reduce_only sell (fills). Verify both
    fill events arrive via WS. Total cost ~$0.02-0.05 + fees."""
    ticker, bid, ask = find_test_market()
    if not ticker:
        print("no cheap test market found")
        return
    print(f"test market: {ticker} bid={bid} ask={ask}")

    events = []
    async with websockets.connect(WS_URL, max_size=2**22,
                                  additional_headers=auth_headers()) as ws:
        await ws.send(json.dumps({"id": 1, "cmd": "subscribe", "params": {
            "channels": ["fill"], "market_tickers": [ticker]}}))

        # 1) buy 1x at ask (limit order, fills immediately as taker)
        buy_px = round(ask, 2)
        r1 = kalshi.place_order(ticker, "YES", 1, buy_px)
        oid1 = (r1.get("order") or r1).get("order_id")
        print(f"BUY placed {ticker} 1@{buy_px} id={oid1}")

        # 2) wait for fill event
        ev = await wait_fill(ws, ticker, 8)
        if ev:
            events.append(("BUY", ev))
        else:
            print("  (no fill event within 8s)")

        # 3) sell back reduce_only IOC at bid
        sell_px = max(bid, 0.01)
        r2 = kalshi.place_order(ticker, "NO", 1, sell_px, reduce_only=True)
        print(f"SELL placed {ticker} 1@{sell_px} reduce_only")

        ev = await wait_fill(ws, ticker, 8)
        if ev:
            events.append(("SELL", ev))
        else:
            print("  (no fill event within 8s)")

    print("\n=== RESULT ===")
    if events:
        for kind, ev in events:
            print(f"{kind} FILL EVENT RECEIVED: {json.dumps(ev)}")
    else:
        print("NO FILL EVENTS RECEIVED — callback broken")
    # cleanup: if sell didn't fill, cancel any resting
    try:
        for o in kalshi.get_orders(status="resting"):
            if o.get("ticker") == ticker:
                kalshi.cancel_order(o.get("order_id"))
                print(f"cancelled leftover resting {o.get('order_id')}")
    except Exception as e:
        print("cleanup ERR:", str(e)[:100])


async def wait_fill(ws, ticker, timeout_s):
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(4, max(1, end - time.time())))
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if data.get("type") == "fill":
            return parse_fill(data)
        if data.get("type") == "error":
            print("WS ERROR:", raw[:200])
            break
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="watch once for --seconds, then exit")
    ap.add_argument("--daemon", action="store_true", help="run forever with reconnect")
    ap.add_argument("--test", action="store_true", help="self-test with tiny buy+sell round trip")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--alert", action="store_true", help="send Telegram alerts on fills")
    args = ap.parse_args()

    load_env()
    if args.test:
        asyncio.run(self_test())
        return
    if args.daemon:
        asyncio.run(watch(0, alert=args.alert, daemon=True))
    else:
        asyncio.run(watch(args.seconds, alert=args.alert, daemon=False))


if __name__ == "__main__":
    main()
