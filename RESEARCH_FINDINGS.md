# Research Assimilation — Kalshi Mechanics + External Playbooks (2026-08-06)

**⚠️ SECURITY — else24/kalshi-market-bot REJECTED (2026-08-06):** repo is
malware, not a trading bot. Deleted clone. IoCs: C2 `https://api.failproxy.space`
(byte-obfuscated in syslib/system.py), TLS verification disabled
(`check_hostname=False`, `CERT_NONE` in syslib/channel.py), reflective PE loader
(syslib/image.py: VirtualAlloc/copy-segments/relocate/import-resolve/CreateThread,
Windows-only), 14MB `base.pkg` ZIP that extracts `python.exe` and downloads
"signed strategy bundles" on startup (syslib/__init__.py). Fake Textual TUI +
strategy.py = cover. **Never clone/run third-party "Kalshi bots" without
syslib-level review; verify what a repo actually imports before executing.**

**UPDATE 2026-08-06 (live verification, OTM 1c test):** order mechanics
verified end-to-end on KXGOLDMON-26AUG3117-T3451.99 (deep OTM):
1. `place_order(side=NO, price=0.99)` → filled buy NO @ 0.01 (`no_px 0.0100`,
   `outcome_side: no`). The `1 - L` conversion in LiveExecutor is CORRECT.
2. Create body `side: "no"` → **400 `invalid_order: side must be bid or ask`**.
   API accepts only `bid|ask`; the mobile UI's "Buy No" label is display-only.
3. Extra `action`/`outcome_side` body fields accepted but IGNORED — exchange
   normalizes every order to `side: yes|no` + `action: buy|sell` from
   book_side + price.
4. V1 `POST /portfolio/orders` = 410 deprecated (Octagon bot's placeOrder
   uses it — stale, don't copy).

Sources (cloned to /data/workspace/research/):
- `prediction-market-alpha-playbook` (AKCodez) — 7 markdown files, production lessons
- `PolyKalshi_Client` (RohitDayanand) — Kalshi+Polymarket WS analytics, arb calculator, fee calc
- `kalshi-trading-bot-cli` (OctagonAI) — AI terminal, Kelly sizing, 5-gate risk, edge engine

This file captures what was assimilated into our predictor stack and what is
candidate for future work. Aligned with VJ rules; anything contradicting RULES.md
is noted explicitly.

---

## 1. Kalshi fee economics (STRUCTURAL, applies to every order)

Kalshi fee per contract: `fee = 0.07 × p × (1-p)`, rounded UP to next cent
(0.0175 for maker-fee tickers, see §4 list). At p=0.50 → 1.75%/contract.
At p=0.05 or 0.95 → 0.33%/contract (quadratic decay).

Consequences for VJ stack:
- **Cross-exchange arb needs ≥400bps raw edge** to survive round-trip fees
  (Kalshi ~1.75% + Polymarket ~2% taker at mid). Sub-200bps raw edges ALWAYS
  net-negative. Our current arb gate (PM-implied < Kalshi sell price) must add
  fee subtraction before declaring edge.
- **Extreme-p pairs (p≈0.05/0.95) are the only structurally cheap seeds** —
  fee drops to ~0.33%/side. Prefer these for sell-side arb.
- Fee math in code: `predictor/kalshi.py` does NOT model fees. Playbook formula:
  `fee = ceil(0.07 * contracts * p * (1-p) * 100)/100`. Maker-fee tickers use 0.0175.

## 2. NO-side price formulas (VALIDATES today's fix)

- **NO ask (cost to BUY NO) = 1 − yes_BID** — NOT 1 − yes_ask.
  Using `1 - yes_ask` underestimates true NO cost by the full spread and
  fabricates fake arbs (playbook: "fabricated false-positive arbs multiple
  times", "almost fired a losing trade").
- NO bid (what a NO seller receives) = 1 − yes_ask.
- Same rule as our 2026-08-06 NO-inversion fix: Kalshi quotes everything from
  YES side. Buy NO at L → send price 1−L. Confirmed by both our live hit and
  external playbook.

## 3. Structural arbs applicable to Kalshi (not just Polymarket)

| Edge | Mechanism | Fit for VJ |
|---|---|---|
| Within-market YES+NO<1.0 | buy both, redeem $1 | Tier S but rare; top-10 closest usually sum=1.001. Low cadence. |
| **Ladder monotonicity** | P(>lower) ≥ P(>upper) by definition; violation → buy lower YES + upper NO | **Tier A. Directly applies to KXGOLDMON/KXWTIMAX monthly ladders we trade.** Thin depth, real but small. |
| Sum-arb lock-in | buy NO on all N mutually-exclusive outcomes at Σ>1.025 | Polymarket NEG_RISK events only; Kalshi has no negRisk flag. Not applicable. |
| Clear-win convergence | decided outcome priced 90-95c → buy at discount | Tier B. Sports/weather clean; commodity/macro FAILED (oracle feed divergence). Our econ markets resolve on FRED/CPI — risky category. |
| Tail-fade | low-prob tail priced 5-10c over base rate → buy NO | Tier B. Matches our geo tail plays; size small, hold to resolution. |

**Gotcha from playbook §1 (partial-basket)**: sum-arb with ONE leg `ask=null`
is a trap — must verify every leg fillable before firing. Scanner must check
all legs, not assume.

## 4. Maker-fee tickers (from PolyKalshi fee calculator — fee = 0.0175)

KXAAAGASM, KXGDP, KXPAYROLLS, KXU3, KXEGGS, KXCPI, KXCPIYOY, KXFEDDECISION,
KXFED, KXNBA*, KXNHL*, KXINDY500, KXPGA, KXUSOPEN, KXPGARYDER, KXTHEOPEN,
KXPGASOLHEIM, KX*SINGLES (tennis GS), KXNFLGAME, KXUEFACL, KXNATHANSHD,
KXCLUBWC, KXTOURDEFRANCE, KXNASCARRACE, KXATPMATCH, KXWTAMATCH, KXMLBASGAME,
KXMLBHRDERBY.
→ Our tennis/crypto/fed order fees are HALF the general 0.07 rate.

## 5. Kalshi WebSocket (from PolyKalshi_Client — real-time capability we lack)

- URL: `wss://api.elections.kalshi.com/trade-api/ws/v2` (prod), demo:
  `wss://demo-api.kalshi.co/trade-api/ws/v2`
- Auth headers: KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP (RSA-PSS, same as REST,
  sign `ts + METHOD + path`).
- Subscribe: `{"id":1,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_tickers":["KX..."]}}`
- Message types: `error`, `ok`, `orderbook_snapshot`, `orderbook_delta`.
  Delta messages carry `seq` for ordering; gaps detected via seq validation.
- Channels: `orderbook_delta`, `ticker`, `trade`, `fill`.
- Use case for us: live orderbook deltas for fast TTL plays (30m flips) instead
  of polling REST every scan. Candidate future upgrade; our current 30m cron
  cadence doesn't need it yet.

## 6. Kelly sizing + 5-gate risk (from Octagon kalshi-trading-bot-cli)

**Kelly formulas** (with executable quote, not mid):
- YES: `f* = edge / (1 - pricingProb)` where pricingProb = yes_ask
- NO: `f* = |edge| / pricingProb` where pricingProb = 1 - no_ask
- multiplier 0.5 (half-Kelly default), maxPositionPct 0.10, minEdgeThreshold 0.05
- liquidity haircut: if spread > 5c OR 24h vol < 500 → multiply fraction by
  haircut (e.g. 0.5).
- contracts floored to tick (fractional markets) or integer.

**5-gate pre-trade** (all must pass):
1. Kelly — contracts > 0 AND dollar ≤ maxPositionPct × bankroll
2. Liquidity — spread < 5c AND vol24h ≥ 500
3. Correlation — ≤ 3 open positions per event category
4. Concentration — total open positions < 10
5. Drawdown — current DD < 20% (from risk snapshots vs high-water mark)

**Circuit breaker**: daily loss limit $50, max drawdown 20%, auto-snapshot
portfolio every cycle, no auto-re-enable same day.

→ Our stack already has: win floor ≥50% (independent source), YES ≤40c band,
≤10% raise, wall gate, $1/trade cap, no-margin, no stop-loss. The 5-gate
adds spread/volume/drawdown checks we lack. Kelly sizing conflicts with VJ's
flat $1.20/order rule — VJ rule wins, but Kelly math is useful for sizing
recommendations in proposals.

## 7. Retry + DLQ pattern (Octagon api.ts)

- Exponential backoff 1s→120s, jitter ±20%, 5 retries, retry only on 429/5xx.
- Dead-letter queue on exhaustion + audit trail. We have retry in
  `predictor/kalshi.py` (5x backoff) — DLQ would improve visibility of
  persistent failures (currently logs and moves on).

## 8. PnL honesty patterns (playbook ARCHITECTURE/METHODOLOGY)

- **Data API > journal** — never trust in-process PnL; reconcile via exchange
  activity/positions. We already treat exchange fills/positions as truth (live-ops).
- **Exit-stamping guard**: only stamp PnL when `actual_fill_price` present;
  NULL fill → flag suspect, wait for reconciliation. Add to weekly review.
- **Wilson lower bound (95%)** not point WR for small N: N=5 100% WR = lb48%
  (random); N=30 80% = lb62%; N=100 70% = lb60%. Weekly review should quote
  Wilson lb, not raw WR.
- **Exhaustive cohort search BEFORE killing a strategy**: aggregate WR hides
  sub-cohort alpha (price bucket, side, day-of-week, category, elapsed fraction,
  FADE variant). 4/4 "killed" strategies had hidden alpha. VJ weekly review:
  only MARGIN OF PROFIT metric stays, but cohort split explains WHERE margin
  came from/lost.
- **Paper-live divergence budget**: 20-40% WR degradation normal.
- **Fat-tail rule**: never kill on N<30 for cheap tail bets; mean ROI/shape
  matters more than WR.

## 9. Antipatterns catalog worth remembering (playbook ANTIPATTERNS.md)

- Side/token alignment — use outcomeIndex, never string match. (We use ticker
  suffixes, safe; PM.us needs care.)
- `1 - yes_ask` ≠ NO ask (see §2) — fake arb trap.
- Thin-book exit trap — exit cost = walking the bid ladder, not mid. 17pp+
  spread = abandoned market fingerprint.
- Thin-book positions are capital-locked — size like hold-to-resolution.
- JS float precision — round thresholds to 3dp (we saw `0.44-0.02=0.41999`).
- Binance US blocked (451) — use Coinbase/Binance.US data for crypto refs.
- CoinGecko demo 429s silently — don't route all traffic through it.

## 10. Octagon edge engine (candidate future)

- Edge = modelProb − marketProb; confidence tiers: ≥10% very_high, ≥5% high,
  ≥2% moderate. Edge ≥2% logged as EDGE_DETECTED.
- Deep research per market: drivers, catalysts, sources; cached with
  refresh-on-price-move (shouldRefresh by prob delta).
- Basket builder: cluster/correlation caps, fractional Kelly sizing, backtest.
- NOT adopted: depends on Octagon paid API; our stack uses independent sources
  (PM cross-venue, DeItaone, research). Pattern worth noting: cache research
  reports and refresh on price move, not every scan.

## 11. Fit-for-use summary — what to adopt NOW

1. Fee-aware arb gate: subtract Kalshi fee (0.07×p×(1-p) or 0.0175 for
   maker-fee tickers) from arb edge before declaring. (risk.py / arb scan)
2. NO ask = 1 − yes_BID formula in arb calc (never 1 − yes_ask).
3. Ladder monotonicity scanner for KXGOLDMON/KXWTI/KXBTCMON series — cheap
   structural check per ladder pair.
4. Maker-fee ticker list → correct fee modeling for tennis/crypto/fed markets.
5. Weekly review: Wilson lb95 + cohort split (price bucket/side/category/day)
   before any strategy verdict; keep MARGIN OF PROFIT as the only go/no-go.
6. Spread/volume gates: skip markets with spread ≥5c or vol24h < $500 for
   new entries (thin-book trap).
7. Kalshi WS client — future upgrade for live orderbook deltas (30m flip plays).

## 12. Explicitly NOT adopted (reasons)

- Whale following / insider cluster copy: needs Polymarket Data API + The Graph
  subgraph, wallet profiling — outside Kalshi+PM.us scope, $1 size.
- NEG_RISK sum-arb: Polymarket-only flag (enableNegRisk); no Kalshi equivalent.
- Full Kelly sizing: conflicts with flat $1.20/order VJ rule.
- Octagon paid API edge reports: cost + external dependency; our research gate
  uses free independent sources.
- UMA dispute arb: playbook documents as FAILED (category bias).
- Crypto up/down FADE: needs 5-min oracle divergence; Kalshi doesn't run
  those; PM.us catalog sports/macro only.
