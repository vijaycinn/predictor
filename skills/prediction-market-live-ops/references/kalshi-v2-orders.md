# Kalshi V2 order API — verified transcript (2026-08-01)

Reverse-engineered during the first real Kalshi order. All responses captured
from production.

## Create order — POST /portfolio/events/orders

Success shape (order placed, then filled instantly):
```json
{
  "ok": true,
  "proposal_id": 1,
  "trade_id": 17,
  "status": "RESTING",
  "side": "YES",
  "limit": 0.588,
  "notional_usd": 0.58,
  "question": "Will Renata Zarazua win the Zarazua vs Korpatsch: Round Of 128 match?"
}
```
Note: local status said RESTING but exchange filled before reconcile — see
fill verification below.

## Error 1 — 410 deprecated endpoint (first attempt)

```
POST /portfolio/orders -> 410
{"error":{"code":"deprecated_v1_order_endpoint","message":"Please switch to the V2 endpoints","details":"https://docs.kalshi.com/api-reference/orders/create-order-v2"}}
```
Fix: POST `/portfolio/events/orders`.

## Error 2 — 400 invalid_price (second attempt)

```
POST /portfolio/events/orders -> 400
{"error":{"code":"invalid_price","message":"invalid price"}}
```
Cause: limit price 0.5880 off the 1c tick. Fix: `round(price*100)/100` -> 0.59.
Tick confirmed from book (bid 0.58 / ask 0.59 — both 2dp).

## Error 3 — expiration_time units (caught before sending)

Docs: `expiration_time integer<int64> Optional Unix timestamp in SECONDS`.
KALSHI-TIMESTAMP header is ms; expiration_time is seconds. Send `int(now + lifetime_h*3600)`,
NOT `*1000`.

## Verify fill — the RESTING-vs-executed race

- `GET /portfolio/orders?status=resting` -> `{"orders": []}` — empty!
- `GET /portfolio/orders` (all) -> our order `status: "executed"`, plus user's
  pre-existing orders (canceled Trump leave order, older World Cup / tennis fills).
- `GET /portfolio/fills` -> our ticker with `created_time` = placement time.
- `GET /portfolio/positions` -> our ticker listed alongside pre-existing user
  positions (crypto structure, Ukraine visit, Hormuz).

Lesson: local DB status is NOT ground truth for live orders. Reconcile must
check exchange fills, not assume RESTING persists.

## Balance

`GET /portfolio/balance` -> `{"balance": 6099}` = **$60.99** (cents).
Before order: $61.61. After $0.58 order: $60.99. Cents, divide by 100.

## Order lifetime math (VJ rule)

`lifetime_h = min(24.0, 0.8 * hours_to_expiry)` when hours_to_expiry > 0,
else 24.0. Verified:
- 5h event -> 4h order (20% decay remains)
- 10h event -> 8h order (20%)
- 30h event -> 24h cap (20%)
- 100h event -> 24h cap (76% remains)
- unknown -> 24h default
