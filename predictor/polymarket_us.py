"""
polymarket_us.py — native Polymarket US (polymarket.us) client.

US-regulated venue. Auth = Ed25519 signature over `{ts}{method}{path}`,
headers X-PM-Access-Key / X-PM-Timestamp / X-PM-Signature. Keys from env
POLYMARKET_API_KEY (Key ID) + POLYMARKET_SECRET_KEY (base64 Ed25519 secret),
falling back to /data/.hermes/.env.

pmxt's PolymarketUS class does NOT work for this venue (it signs EIP-712 with
an ETH private key — Polymarket US uses Ed25519 API keys). Use this module.

Bases:
  auth API:   https://api.polymarket.us/v1
  public API: https://gateway.polymarket.us/v1

Docs: https://docs.polymarket.us/api-reference/introduction
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_BASE = "https://api.polymarket.us"
PUBLIC_BASE = "https://gateway.polymarket.us"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_ENV_LOADED = False


def _load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    for p in ("/data/.hermes/.env", os.path.expanduser("~/.hermes/.env")):
        if os.path.isfile(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    _ENV_LOADED = True


def get_key_id() -> str:
    _load_env()
    return os.environ.get("POLYMARKET_API_KEY", "")


def get_secret() -> str:
    _load_env()
    return os.environ.get("POLYMARKET_SECRET_KEY", "")


def auth_headers(method: str, path: str) -> dict:
    """X-PM-* headers. Sign `{ts_ms}{method}{path}` with Ed25519 secret."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    secret = get_secret()
    if not secret:
        raise RuntimeError("POLYMARKET_SECRET_KEY missing")
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(secret)[:32]
    )
    signature = base64.b64encode(private_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": get_key_id(),
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }


class ApiError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:300]}")


def _request(method: str, path: str, body=None, base: str = AUTH_BASE,
             auth: bool = True, timeout: int = 20):
    url = base + path
    headers = auth_headers(method, path) if auth else {"User-Agent": UA,
                                                       "Accept": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode()[:500]) from None
    except urllib.error.URLError as e:
        raise ApiError(0, f"network error: {e}") from None


# ---- authenticated (api.polymarket.us) ----

def get_balances():
    return _request("GET", "/v1/account/balances")


def get_positions(market: str | None = None):
    path = "/v1/portfolio/positions"
    if market:
        path += "?market=" + urllib.parse.quote(market)
    return _request("GET", path)


def get_open_orders(slugs: list[str] | None = None):
    path = "/v1/orders/open"
    if slugs:
        qs = "&".join("slugs=" + urllib.parse.quote(s) for s in slugs)
        path += "?" + qs
    return _request("GET", path)


def get_order(order_id: str):
    return _request("GET", f"/v1/orders/{order_id}")


def get_activities(limit: int = 50):
    return _request("GET", f"/v1/portfolio/activities?limit={limit}")


def preview_order(payload: dict):
    return _request("POST", "/v1/order/preview", body={"request": payload})


def place_order(payload: dict):
    return _request("POST", "/v1/orders", body=payload)


def cancel_order(order_id: str, market_slug: str):
    return _request("POST", f"/v1/order/{order_id}/cancel",
                    body={"marketSlug": market_slug})


def cancel_all(slugs: list[str] | None = None):
    body = {"marketSlugs": slugs} if slugs else {}
    return _request("POST", "/v1/orders/cancel-all", body=body)


def place_limit(slug: str, side: str, action: str, qty: float, price: float,
                tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                good_till_time: str | None = None,
                maker_only: bool = True) -> dict:
    """side = 'YES'|'NO', action = 'BUY'|'SELL'. price in $ (0.001 ticks)."""
    side = side.upper()
    action = action.upper()
    if side not in ("YES", "NO"):
        raise ValueError(f"side must be YES/NO, got {side}")
    if action not in ("BUY", "SELL"):
        raise ValueError(f"action must be BUY/SELL, got {action}")
    payload = {
        "marketSlug": slug,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": f"{price:.3f}", "currency": "USD"},
        "quantity": qty,
        "tif": tif,
        "outcomeSide": f"OUTCOME_SIDE_{side}",
        "action": f"ORDER_ACTION_{action}",
        "participateDontInitiate": maker_only,
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_MANUAL",
    }
    if tif == "TIME_IN_FORCE_GOOD_TILL_DATE" and good_till_time:
        payload["goodTillTime"] = good_till_time
    return payload


# ---- public reads (gateway.polymarket.us) ----

def get_markets(limit: int = 50, closed: bool = False, category: str | None = None,
                sort: str | None = None, cursor: str | None = None):
    params = {"limit": str(limit), "closed": str(closed).lower()}
    if category:
        params["category"] = category
    if sort:
        params["sort"] = sort
    if cursor:
        params["cursor"] = cursor
    path = "/v1/markets?" + urllib.parse.urlencode(params)
    return _request("GET", path, auth=False, base=PUBLIC_BASE)


def get_market(slug: str):
    return _request("GET", f"/v1/markets/{slug}", auth=False, base=PUBLIC_BASE)


def get_book(slug: str):
    return _request("GET", f"/v1/markets/{slug}/book", auth=False, base=PUBLIC_BASE)


def get_bbo(slug: str):
    return _request("GET", f"/v1/markets/{slug}/bbo", auth=False, base=PUBLIC_BASE)


def search(q: str, limit: int = 10):
    path = "/v1/search?" + urllib.parse.urlencode({"q": q, "limit": str(limit)})
    return _request("GET", path, auth=False, base=PUBLIC_BASE)


def get_events(limit: int = 50, closed: bool = False, category: str | None = None):
    params = {"limit": str(limit), "closed": str(closed).lower()}
    if category:
        params["category"] = category
    path = "/v1/events?" + urllib.parse.urlencode(params)
    return _request("GET", path, auth=False, base=PUBLIC_BASE)


def price_summary(slug: str) -> dict:
    """Compact pricing: book + bbo rolled into one dict for hunt/scan use."""
    out = {"slug": slug}
    try:
        bbo = get_bbo(slug)
        md = bbo.get("marketData", {})
        out.update({
            "currentPx": md.get("currentPx", {}).get("value"),
            "bestBid": md.get("bestBid"),
            "bestAsk": md.get("bestAsk"),
            "bidDepth": md.get("bidDepth"),
            "askDepth": md.get("askDepth"),
            "openInterest": md.get("openInterest"),
            "lastTradePx": md.get("lastTradePx", {}).get("value"),
        })
    except ApiError:
        pass
    try:
        book = get_book(slug)
        md = book.get("marketData", {})
        out["bids"] = md.get("bids", [])
        out["offers"] = md.get("offers", [])
        out["state"] = md.get("state")
    except ApiError:
        pass
    return out
