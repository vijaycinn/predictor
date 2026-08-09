#!/usr/bin/env python3
"""Kalshi WebSocket probe — verify orderbook_delta + fill channels work (2026-08-09).

Usage: python3 scripts/ws_probe.py [--ticker KXFEDDECISION-26SEP-H0] [--seconds 12]
"""
import argparse
import asyncio
import json
import os
import sys
import time

import websockets

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


def load_env():
    for line in open("/data/.hermes/.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def auth_headers():
    """Kalshi WS auth = same RSA-PSS as REST: sign ts + METHOD + path."""
    import base64
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


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="KXFEDDECISION-26SEP-H0")
    ap.add_argument("--seconds", type=int, default=12)
    args = ap.parse_args()

    load_env()
    key = os.environ.get("KALSHI_API_KEY", "")
    priv = os.environ.get("KALSHI_PRIVATE_KEY", "")

    async with websockets.connect(WS_URL, max_size=2**22, additional_headers=auth_headers()) as ws:
        # subscribe to orderbook_delta + fill channels
        msg = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta", "fill"],
                "market_tickers": [args.ticker],
            },
        }
        await ws.send(json.dumps(msg))
        print(f"subscribed: {args.ticker} @ {time.strftime('%H:%M:%S')}")
        start = time.time()
        count = 0
        while time.time() - start < args.seconds:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=4)
            except asyncio.TimeoutError:
                print("  (4s silent)")
                continue
            try:
                data = json.loads(raw)
            except Exception:
                print("  raw:", raw[:120])
                continue
            mtype = data.get("type")
            if mtype == "error":
                print("  ERROR:", raw[:300])
                break
            if mtype in ("ok", "orderbook_snapshot"):
                print(f"  {mtype}: {raw[:200]}")
            elif mtype == "orderbook_delta":
                count += 1
                if count <= 3:
                    print(f"  orderbook_delta: {raw[:200]}")
            elif mtype == "fill":
                print(f"  FILL EVENT: {raw[:300]}")
            else:
                if count <= 5:
                    print(f"  {mtype}: {raw[:150]}")
        print(f"--- {count} orderbook_delta msgs in {args.seconds}s ---")


if __name__ == "__main__":
    asyncio.run(main())
