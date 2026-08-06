# Polymarket US — API integration detail (2026-08-05)

US-regulated venue. Two APIs: **public** (gateway.polymarket.us, no auth) for
market data, **authenticated** (api.polymarket.us) for trading/portfolio.
Docs: https://docs.polymarket.us/api-reference/introduction (llms.txt index:
https://docs.polymarket.us/llms.txt).

## Credentials

- Env: `POLYMARKET_API_KEY` (Key ID = UUID, len 36) + `POLYMARKET_SECRET_KEY`
  (base64 Ed25519 secret, len 88) — stored in /data/.hermes/.env.
- Create at polymarket.us/developer (sign in with SAME method as app —
  switching Apple/Google/email breaks key access). Secret shown once.

## Auth — Ed25519 over `{ts}{method}{path}`

```python
timestamp = str(int(time.time() * 1000))
message = f"{timestamp}{method}{path}"            # NO query string
private_key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
signature = base64.b64encode(private_key.sign(message.encode())).decode()
headers = {"X-PM-Access-Key": key_id, "X-PM-Timestamp": timestamp,
           "X-PM-Signature": signature, "Content-Type": "application/json"}
```

- Timestamp must be within **30 seconds** of server time.
- **Cloudflare 403 `error code: 1010`** = bot block: urllib's default UA gets
  banned. Send a browser UA (`Mozilla/5.0 ... Chrome/126.0`). First raw test
  403'd; UA fix → 200.
- Sign the path WITHOUT query string (e.g. `GET /v1/portfolio/positions`).

## Endpoint map

Authenticated (api.polymarket.us/v1):
- `GET /account/balances` — per-currency balances (currentBalance, buyingPower,
  openOrders, unsettledFunds). NOTE: `/v1/account/balance` (singular) = 404.
- `GET /portfolio/positions` — `{positions: {slug: pos}, nextCursor, eof}`
- `GET /orders/open` — open orders (cumQuantity/leavesQuantity = fill truth)
- `GET /orders/{id}` — order detail incl. avgPx, state
- `POST /orders` — create (body below); returns `{id, executions[]}`
- `POST /order/preview` — VALIDATE WITHOUT PLACING. Body `{"request": {...}}`.
  THE diagnostic for 400s.
- `POST /order/{orderId}/cancel` — body `{marketSlug}` (required)
- `POST /orders/cancel-all` — `{marketSlugs: [...]}`
- `GET /portfolio/activities` — trades/resolutions/balance changes

Public (gateway.polymarket.us/v1, no auth):
- `GET /markets?closed=false&limit=N[&category=]`, `GET /markets/{slug}`
- `GET /markets/{slug}/book` — full ladder `{marketData: {bids, offers, state, stats}}`
- `GET /markets/{slug}/bbo` — `{marketData: {bestBid, bestAsk, currentPx, bidDepth, askDepth, openInterest}}`
- `GET /search?q=` — event search (good discovery; returns events w/ markets)
- `GET /events?closed=false[&category=]`

## Order payload (limit)

```json
{
  "marketSlug": "<slug>", "type": "ORDER_TYPE_LIMIT",
  "price": {"value": "0.350", "currency": "USD"}, "quantity": 2,
  "tif": "TIME_IN_FORCE_GOOD_TILL_DATE", "goodTillTime": "2026-08-05T23:30:00Z",
  "outcomeSide": "OUTCOME_SIDE_YES", "action": "ORDER_ACTION_BUY",
  "participateDontInitiate": true,
  "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_MANUAL"
}
```

- TIF: DAY / GOOD_TILL_CANCEL / GOOD_TILL_DATE (needs goodTillTime RFC3339) /
  IMMEDIATE_OR_CANCEL / FILL_OR_KILL. `outcomeSide`+`action` OR `intent`
  (ORDER_INTENT_BUY_LONG/SELL_LONG/BUY_SHORT/SELL_SHORT).
- Response: `{id, executions[]}` — executions only if synchronousExecution or
  immediate fill; otherwise RESTING with just id. Fill truth = cumQuantity /
  leavesQuantity on order objects + `/portfolio/positions` (exchange = truth).
- Tick size 0.001 (orderPriceMinTickSize); price string 3dp.

## Error semantics

- `400 {"code":3,"message":"The server was unable to process your request."}`
  = GENERIC exchange rejection (seen with $0 balance = insufficient funds).
  Use `/order/preview` to confirm the payload shape is valid first; if preview
  passes but place 400s → funding/account state, not wiring.
- `400 "Price is required for limit order"` — sent when slippageTolerance
  `{bips, ticks}` present; don't set both/extra fields that conflict.
- Rate limits: **20 rps per API key** (auth), 20 rps per IP (public).
- **5s latency stopgap on orders**: if an order isn't processed in 5s it's
  rejected with `Global Rate Limit Exceeded` — TRANSIENT, do NOT throttle.
  Pure cancels are never stopgap-rejected.

## Data-shape gotchas

- `px`, `bestBid`, `bestAsk`, `currentPx` are **`{value, currency}` objects**,
  not plain floats — unwrap `.value` before float(). Book rows: `{px, qty}`
  (qty is a plain number/string).
- Book `bids` = resting YES bid levels; `offers` = YES ask levels. NO bid
  ladder = `1 − offer px` (binary equivalence, same as Kalshi no_dollars).
- Market objects: `marketSides[]` with `long: true/false`, `price` (last/
  settlement), `identifier` (instrument symbol = slug for binaries).
- Catalog is sports-heavy (NFL/MLB/tennis); `search` returns events, not flat
  markets.

## pmxt = ANALYSIS ONLY (incompatible auth)

`pmxt.PolymarketUS(api_key=, private_key=)` signs EIP-712 typed data with an
**ETH private key** (EthAccountSigner → `Account.from_key` fails on base64
Ed25519 secret with `binascii.Error: Non-hexadecimal digit found`). Polymarket
US requires Ed25519 header signing — pmxt CANNOT trade this venue. Reads:
MCP `fetchMarkets/fetchEvents(exchange=polymarket_us)` return `[]` — pmxt
hosted catalog doesn't serve it. Use gateway directly for reads.

## Verification recipe (ad-hoc, network-free + guarded live)

Reusable pattern for a new venue integration (see session 2026-08-05):
1. Import sanity + venue dispatch (make_executor paper/live/unknown).
2. Gate matrix with SYNTHETIC sigs: valid passes; sub-50% blocked; missing
   approved blocked (must leave BOTH approved_price AND ev_calc.price_side
   None — sig helper that defaults price_side to 0.5 defeats the test);
   band breach; raise breach; overrides honored. Gate ORDER in pre_flight:
   limit-only → win floor → band → raise. Raise guard is UNREACHABLE for
   approved ≥ 0.50 within the 40c band (0.40 < 0.50×1.1) — test it with
   approved 0.45 + floor/band overrides, limit 0.50.
3. wall_check with synthetic ladder (density mode picks 0.45 over 0.55
   neighbor volumes).
4. Payload shape checks (no network).
5. Guarded live smoke (BBO + search), try/except so rate limits don't fail
   the run.
