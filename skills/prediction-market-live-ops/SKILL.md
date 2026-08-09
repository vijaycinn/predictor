---
name: prediction-market-live-ops
description: "Live order placement + lifecycle for prediction markets (Kalshi V2 API): order endpoints, tick rounding, expiration_time units, event-aware TTL, fill verification. Use for wiring/placing/verifying real-money orders."
version: 1.0.0
author: Mando
tags: [prediction-markets, kalshi, live-trading, orders, api]
---

# Prediction Market Live Order Operations

Live execution mechanics for binary prediction markets. Emerged from the first
real Kalshi order (2026-08-01) which hit THREE production blockers — all now
documented. Analysis/hunting side lives in skill `predict`; this skill is the
execution/lifecycle complement.

## When to use

- Placing, cancelling, or verifying live orders on Kalshi (or wiring Polymarket live later)
- Debugging order API errors (410/400/401)
- Setting order expiries, position sizing, or reconcile logic for live mode
- Reviewing/verifying that a "filled" order actually filled

## Kalshi V2 order API (verified live)

- **Create: POST `/portfolio/events/orders`** — legacy POST `/portfolio/orders`
  returns **410 `deprecated_v1_order_endpoint`** (deprecated May 2026). Any doc
  showing `/portfolio/orders` for CREATE is stale.
- **POST response is NOT self-describing** (verified 2026-08-08): returns
  `order_id` but `status/side/count/price` all null. ALWAYS follow up with GET
  to verify state — never report "placed/resting/filled" from the POST reply.
- **List: GET `/portfolio/orders`** — unchanged, still works. Detail:
  **GET `/portfolio/orders/{order_id}` WORKS; GET
  `/portfolio/events/orders/{order_id}` 404s** (verified live 2026-08-08) —
  even though CREATE is events-scoped, lookup uses the legacy GET path.
- **Cancel: DELETE `/portfolio/events/orders/{order_id}`**.
- Positions: GET `/portfolio/positions`; Fills: GET `/portfolio/fills`;
  Balance: GET `/portfolio/balance` — **returns CENTS** (6099 = $60.99).
- Body (all fixed-point dollar strings): `{ticker, client_order_id, side:
  bid|ask, count: "1.00", price: "0.5900", time_in_force, expiration_time,
  self_trade_prevention_type, post_only, reduce_only}`. bid = buy YES,
  ask = buy NO (sell YES).

## Three traps that block real orders (each hit live)

1. **Endpoint** — must be `/portfolio/events/orders`, not `/portfolio/orders`.
2. **Off-tick price** — 400 `invalid_price`. Kalshi trades on 1c ticks;
   0.5880 rejected. Round: `round(price*100)/100` → 0.59. Confirm tick from
   book (bid/ask both 2dp).
3. **expiration_time units** — docs: "Unix timestamp in **seconds**" (int64).
   NOT ms. KALSHI-TIMESTAMP header is ms but expiration_time is seconds — the
   same request mixes both units.

## Event-aware TTL (VJ rule, hard)

**DEFAULT = 1 HOUR (VJ 2026-08-02)** — resting orders default to **1 hour**
expiry (`config execution.order_ttl_hours: 1`, `place_order` default
`max_lifetime_hours: 1.0`) unless VJ explicitly overrides ("1h", "24h",
"until close"). Stale resting orders are dead weight — re-evaluate often.
Hit live 2026-08-02: a PLTR COMM order placed with 24h TTL was cancelled
and re-placed at 1h per VJ instruction.

**TIMED-EVENT DEFAULT = TTL TO EVENT START (VJ 2026-08-03, codified)** —
for markets tied to a timed event (earnings call, EO signing, match
kickoff, data release), the DEFAULT order TTL is **event start time** —
same as the Kalshi app's "until event starts" expiry option. Order rests
until the event begins, then expires (nothing left to trade once the
transcript/remarks flow). Applied when the event start is known and
> 1h out; the plain 1h default still applies to untimed/continuous
markets. Live example 2026-08-03: PLTR/GRAB/SNAP mention orders needed
8h TTL to survive to the 21:00Z call — a 5.2h (0.8×) TTL would have
expired them 1.5h BEFORE the event. Rule: `ttl = event_start − now`
(min 1h, cap 24h abs, no 0.8× decay for timed events — the event IS
the expiry).

Formula when VJ gives a duration: `lifetime = min(duration_cap, 24h abs,
0.8 × hours_to_expiry)`. Leaves ≥20% of event time surviving the order.
Critical for short events: 5h match → 4h order TTL; a 24h order on a 5h
event is invalid. Apply in THREE places, all aligned:
- exchange `expiration_time` (seconds)
- DB reconcile TTL (cancels resting orders at TTL)
- paper executor

**⚠️ EXCEPTION — mention/econ markets that resolve at a known future moment
(call time, print time): TTL must SURVIVE TO the event, not die before it.**
Hit live 2026-08-03: earnings-mention batch with 0.8×hours formula (5.2h)
expired 1.5h BEFORE the earnings call — all 10 cancelled and re-placed with
8h TTL. For these, bypass LiveExecutor (hardcodes 1h default):
`kalshi.place_order(..., hours_to_expiry=0, max_lifetime_hours=8.0)` and
keep `risk.pre_flight_check` as the gate. Detail: `references/earnings-mention-markets.md`.

## Exits — reduce_only sells (hit live 2026-08-02)

- **reduce_only requires IOC**: `time_in_force: immediate_or_cancel`, and
  **omit `expiration_time`** (IoC + expiry = `Cannot_specify_both_IoC_and_expiration_timestamp`).
  GTC + reduce_only = `reduce_only can only be used with IoC orders`.
- **Selling YES = side `NO`** (body `ask` = sell YES / buy NO). Passing side `YES`
  (bid) with reduce_only fills 0 on a long — wrong direction.
- **`place_order` side is CASE-SENSITIVE** (hit live 2026-08-03): pass `"YES"`/`"NO"`
  uppercase. Lowercase `"yes"` fails the `side == "YES"` check → constructs an ASK
  (sell) instead of BID → wrong-way fill. COMM: approved buy 3@0.13, filled sell
  3@0.40, position_fp -3. Always route through LiveExecutor (normalizes side); raw
  place_order calls must uppercase side.
- Exits fill at/better than price immediately; verify via `/portfolio/positions`
  (qty 0.00 = flat; zero-qty ghost entries can still appear, check `position_fp`).
- **NEVER exit a binary within ~2c of entry price — fees guarantee the loss.**
  Hit live 2026-08-01/02 (ZAR, first real order): bought YES 1@0.59, sold 1@0.58
  next day, market then resolved YES at 0.99. Realized −$0.0441 = −7.5% margin on
  the week's only trade; round-trip fees 0.017+0.0171 = 3.4c on $0.59 stake =
  5.8% drag. Exiting at par = pay fees for zero edge. Rule 6 (ride to
  resolution) is the default; rule 6b take-profit only ≥0.91. If an exit
  rationale exists, log it — DB has no exit-reason field, so "why did we sell
  a winner" is unanswerable afterwards.

## Cron jobs — verify existence before trusting docs (hit 2026-08-09)

Reference docs claimed `live-flip-scan` (id 60dc2f20624f) existed; `cronjob
action=list` showed 9 jobs, none of them it. Docs rot; the scheduler is
truth. When a recurring watchdog/scan is supposed to run, ALWAYS
`cronjob action=list` and confirm the job id + schedule BEFORE assuming it
fires — a missing cron means silent dead features (flip scan hadn't run for
days while docs said every 30m). Recreate with same name+schedule if gone.
Also: scripts referenced by crons live in `/data/.hermes/scripts/` — after
fixing a script, `cp` the repo copy there or the cron runs stale code.

## Exit tool scripts (2026-08-09)

- `scripts/take_profit.py` — dual-mode take-profit: IOC when wall≥91c, else
  resting limit at threshold; `--half` scale-out; `--ttl-h`.
- `scripts/exit_plan.py` — V1 poll-based exit manager (positions → missing
  exits → place, both directions, idempotent); `--place --quiet` = cron mode.
- `scripts/exit_plan_cron.sh` — cron wrapper (`--place --quiet`).
- `scripts/exit_watcher.py` — WS fill-channel watcher (V2 push upgrade;
  `--test` does a tiny buy+sell round trip to verify fill events).
- `scripts/ws_probe.py` — Kalshi WS auth + subscription probe.

## TAKE-PROFIT — 91c+ exit (VJ rule 6b, 2026-08-09, Sabalenka lesson, HARD)

**Live sports position whose market YES price reaches ≥0.91 → sell it, lock
profit. Do NOT ride a 91c+ winner to resolution.** Winner-side only — this is
NOT a stop-loss; losers still ride to resolution (rule 6).

- Rationale (EV): at ≥91c, sell EV ≈ ride EV minus variance. The 5-8% blowup
  tail turns +45c locked into −45c. Sabalenka case: 2×@0.46, decider lead at
  ~92c, rode, lost — $1.84 swing on one decision.
- Mechanics (all verified live): `reduce_only=True` + IOC (omit expiration_time,
  kalshi.place_order handles), selling YES = side NO. Exit price = FULL-LADDER
  bid wall via `kalshi.get_orderbook_full` (density mode, trash floor) — NEVER
  the stale quote endpoint (Sabalenka 08-09: quote showed prev-day 85c while
  in-play book was 38c).
- Scale-out optional: sell half @91c, ride half (matches the "ride to
  resolution" instinct on the other half).
- Threshold 91c = one-way; no re-entry below.
- **DUAL-MODE EXECUTION (VJ Q&A 2026-08-09):** Kalshi has NO native
  trigger/OCO orders — a resting limit IS the conditional order. Two cases:
  - Wall ALREADY ≥ threshold → reduce_only IOC at the wall (condition met,
    instant lock). IOC only fills if price ≥ limit at placement moment — NEVER
    fire IOC below threshold (instant cancel).
  - Wall BELOW threshold → RESTING limit sell AT the threshold (0.91, GTC/GTD
    with TTL). Fills only when market touches it. This is the "place 2x@0.91
    after fill and exit if limit hits" pattern VJ asked for — the limit order
    IS the conditional. No reduce_only (reduce_only requires IOC).
- **SCALABLE EXIT = RESTING LIMIT + FILL CALLBACK (VJ Q&A 2026-08-09, HARD):**
  IOC is NOT scalable — needs constant wall polling, price≥limit at placement,
  N orders = N polls. Correct design: resting limit per position + Kalshi
  WebSocket `fill` channel for order confirmation. One WS connection subscribes
  all tickers; fill events arrive as callbacks — no polling, parallel-safe.
  **WS VERIFIED LIVE 2026-08-09** (`scripts/ws_probe.py`): auth = same RSA-PSS
  headers as REST (sign `ts + GET + /trade-api/ws/v2`, KALSHI-ACCESS-KEY/
  SIGNATURE/TIMESTAMP), endpoint `wss://api.elections.kalshi.com/trade-api/ws/v2`,
  subscribe `{"id":1,"cmd":"subscribe","params":{"channels":["orderbook_delta","fill"],"market_tickers":[...]}}`
  → `subscribed` ack, `orderbook_snapshot`, `orderbook_delta` (seq-ordered),
  `fill` events. Order confirmation for take-profit exits comes from the WS
  `fill` message, not REST polling.
  **FILL EVENT FIELD NAMES (verified live 2026-08-09, KXGOLDMON T4811.99 buy+
  sell round trip):** `msg.market_ticker` (NOT `ticker`), `msg.yes_price_dollars`
  (STRING, NOT `yes_price`), `msg.count_fp` (STRING), `msg.action` (buy/sell),
  `msg.post_position_fp` (STRING — pos after fill; "0.00" = flat = exit
  confirmed), `msg.fee_cost` (STRING), `msg.is_taker`, `msg.ts_ms`,
  `msg.outcome_side`/`book_side`. Parser in `scripts/exit_watcher.py` uses
  these; naive field names return null.
- Tool: `scripts/take_profit.py` (repo + cron copy pattern). Dry-run default;
  `--place` executes dual-mode: IOC when wall≥min, resting limit otherwise;
  `--half` sells half; `--ttl-h` sets resting TTL. Run it during live sports
  windows — it scans open YES positions, computes each bid wall, flags ≥0.91.
- **AUTO-MAINTENANCE CRON (2026-08-09):** job `exit-plan-maintain`
  (`ac616c49eac6`), `no_agent=true`, every 12h, deliver origin. Runs
  `exit_plan_cron.sh` → `exit_plan.py --place --quiet` (repo script; wrapper in
  `/data/.hermes/scripts/`). `--quiet` = watchdog: SILENT when all exits
  resting, prints only placements/errors. Re-places expired (24h TTL) exits +
  covers new positions within 12h. Manual `run-exit-plan` skill still
  approval-gated; cron is the standing automation — idempotent so they never
  fight.
- Only YES longs (qty>0) qualify. NO positions ride per rule 6.

## Fill verification — trust exchange, not local DB

- `get_orders(status="resting")` can return empty while the order actually
  filled — the fill raced the local reconcile.
- Check all orders (no status filter) + `/portfolio/fills` + `/portfolio/positions`.
- A just-placed order shows `status: "executed"` exchange-side even when local
  DB recorded RESTING. Positions list is ground truth for holdings.

## STATUS TRAP (hit live 2026-08-01): `"executed"` ≠ `"filled"` in reconcile

- Kalshi V2 returns order status **`"executed"`** for filled orders — NOT
  `"filled"`. Reconcile code that checks only `"filled"` silently misses the
  fill, the order stays "resting" in local DB, then the TTL branch CANCELS a
  real open position locally while the exchange position is still live.
  Symptom: `canceled_ttl` alert for an order that actually filled.
- Fix: accept BOTH `executed` and `filled` as terminal-filled. And NEVER
  TTL-cancel an order whose remote status is terminal
  (executed/filled/canceled/cancelled/expired) — `continue` past the TTL
  branch for those.
- Order object from `GET /orders/{id}` returns status but **NOT fill
  price/count**. True fill data lives in `GET /portfolio/fills` with fields
  **`count_fp`** (string contracts) and **`yes_price_dollars`** /
  **`no_price_dollars`** (string dollars) — not `count`/`price`. Example:
  `count_fp=1.0, yes_price_dollars=0.59, fee_cost=0.017`.
- Repair recipe: fetch fills by `order_id`, update local trade to
  OPEN/filled with real price+qty, log fee.

## Maker order placement — bid below last trade (VJ pattern 2026-08-02)

VJ's preferred entry: rest limit orders on bid levels **≥2c below last trade**,
on levels with enough resting volume to matter. Improves entry vs crossing
the spread; fills only if price dips to the level. Works on any market, but
thin monthly books (BTC dip series) show real depth below the touch.

Workflow:
1. Pull full book: `GET /markets/{ticker}/orderbook` →
   `orderbook_fp.yes_dollars` = [[price, size], ...] ASCENDING (whole ladder,
   not just top-5 — the `fetch_orderbook` helper truncates to 5 levels).
2. Get last trade: `GET /markets/{ticker}` → `last_price_dollars`.
3. Find levels where `price <= last - 0.02` AND `size > ~50` contracts.
4. Place limit at that price, `post_only` semantics (limit below touch rests
   naturally), $1/trade cap, side YES. Expect RESTING; verify exchange-side
   and repair local DB if it reports `executed` (STATUS TRAP above).

Verified example 2026-08-02 (KXBTCMINMON-BTC-26AUG31 series, last trade /
usable bid level):
- 5500000 (dip $55k): last 0.19 → bid 0.16 @ 3,000 contracts (3c below)
- 5250000 (dip $52.5k): last 0.12 → bid 0.09 @ 1,279 (3c below)
- 5750000 (dip $57.5k): last 0.35 → bid 0.31 @ 401 (4c below, thinner)

## Kalshi share-URL → analysis card (VJ workflow, 2026-08-02)

VJ sends `kalshi.com/markets/...` links + phone screenshots frequently. Flow:
1. Parse the event ticker from URL path — the last path segment IS the event
   ticker (e.g. `KXATPCHALLENGERMATCH-26AUG02RIBREJ`).
2. Fetch markets: `GET /markets?event_ticker=<ev>` (reliable filter; never
   `/events/{ev}/markets` = 404). Print bid/ask/vol both sides + orderbook.
3. Get live score (tennisstats/Robinhood work; ESPN misses challengers;
   Sofascore 403). Check format first: men's GS Bo5, men's non-GS Bo3, women
   Bo3 — same score ≠ same prob across formats.
   **PM anchor may NOT exist for WTA/ATP singles** (verified 2026-08-08
   Kostyuk/Swiatek Toronto): gamma public-search returned 500 then empty,
   pmxt fetchEvents(polymarket) → [], router fetchEventMatches → []. No
   cross-venue truth → label analysis research-only, default SKIP unless the
   research edge is solid. Don't block the hunt on gamma — it 500s on flaky
   days; try pmxt router, then move on.
4. Produce a CAVEMAN CARD (below) — NO markdown tables, VJ reads on phone.
5. Rule-check the pick: est ≥50% from independent source, YES ≤40c band,
   ≤10% raise — report which gate blocks if SKIP.

VJ trades on the Kalshi mobile app HIMSELF (won Ribero 2@0.40 +$1.20 while
Mando said SKIP). Always check `/portfolio/fills` + positions for HIS fills
too, not just Mando-placed orders. He spots markets the scanner misses —
double-check name searches via `scripts/search_market.py`.

## Output style — VJ hard preference (2026-08-02)

**CHARTS = OPT-IN ONLY (VJ 2026-08-06, HARD):** charts/plots are produced ONLY
when VJ explicitly asks ("chart it", "show me the ladder", "chart X"). NEVER
auto-attach charts to proposals, scans, or analysis by default. Text-only
default — always. Capability is ready (matplotlib+Agg installed, ladder/history
chart scripts work, PNG → Telegram native images via MEDIA:) but stays dormant
until requested. VJ said "Keep charts optional and only to be produced when I
explicitly ask. No — by default."

**RESEARCH SYNC = DISTILLED ONLY (VJ 2026-08-06):** when VJ says "sync research
to GitHub", push the DISTILLED findings (RESEARCH_FINDINGS.md, skill patches,
RULES updates) — NOT vendored raw third-party repos. VJ rejected vendoring
entire repos ("I don't want entire repo.. Only distilled findings that
predictor can leverage"). Raw clones stay in /data/workspace/research/ locally
(outside git) for depth; only the distilled layer goes to GH.

VJ reads on phone (Telegram). **Tables do NOT render legibly for him** — he
rejected the scanner table format explicitly ("Skip table as it doesn't render
in a way to make it easily to understand"). Present live/hunt results as
CAVEMAN CARDS:

- One match/market per block, terse lines, no prose filler
- **Trend icons for recent form**: ▲ = win, ▼ = loss, e.g. `Andreev: ▲▲▲▲ (4 straight)`
- Fields in order: MATCH / format / surface → TREND (icons) → SCORE (live state)
  → MARKET (bid/ask/vol) → EST + EDGE → ACTION (one word) → WHY (one line)
- ACTION-first bias: BUY / SKIP / CANCEL — never bury the decision
- **When VJ asks "which ones to trade"**: list the BUY candidates with
  price+edge, then a one-line SKIP group. He flagged "Too verbose" (2026-08-02)
  when given full per-market analysis — rank, don't narrate. A shortlist is
  BUY rows → WATCH → SKIP rows, nothing else.
- **CHOICE SCREENS = one-liners only (VJ re-flag 2026-08-03)**: when VJ must
  PICK between options (clarify tool, "which do you want"), each option is a
  single terse line — e.g. "Allow near-certain (≥90% indep prob) + resolves
  ≤24h to exceed 40c band, VWAP limit only". Analysis goes in the research
  pass; the choice screen shows options, not reasoning. "Too verbose on opty.
  Make succinct options for me to choose from."
- **NEVER dismiss a scan class on title price (VJ rebuke 2026-08-03)**: a flat
  "priced out, nothing worth looking" on earnings-mention markets was wrong —
  VJ found the PLTR series right after that dismissal, and the near-certain
  closeby class (REVE) came out of it. If a scan returns all-SKIP, expand the
  sub-questions/descriptions and check for a missed class BEFORE concluding
  nothing. Cheap "dismissed" ≠ "investigated".
- No markdown tables, no decorative borders, no long reason paragraphs
- Caveman mode (drop articles/filler) but keep exact prices/tickers

Example card (from Ribero WON case, 2026-08-02):
```
**RIBERO vs REJCHTMAN — Plovdiv 2 Q1 | Bo3 | Clay**
TREND: Ribero ▲▼▲▼▼▼ | Rejchtman ▼▼▼▼▲▲▼
SCORE: Set 1: Ribero 6-4 ✅ | Set 2: Ribero 1-4* (break down)
MARKET: Ribero 0.53/0.54 ($51k) | Rejchtman 0.46/0.47 ($37k)
EST: Ribero 0.56 | EDGE +2c
ACTION: SKIP — both gates block (band >40c, floor <50%)
```

`scripts/live_flip_scan.py` prints a COMPACT TABLE (VJ 2026-08-02): header
row + one line per candidate (`#  SIDE  LIMIT  TTL   MID   VOL  [B] MATCH`),
`[B]` = buyable (cheap side ≤40c, Ribero pattern). VJ explicitly asked for
table format for the SCANNER ("I want scanner output as table. Avoid verbose
reasons with bias on what I need to choose") — terse table for machine-ish
lists, CAVEMAN CARD for individual match analysis. Two formats, don't mix.

## Econ dailies — verify settlement source BEFORE trading (2026-08-02)

Daily econ series (e.g. `KXAAAGASD` US gas price) resolve on an external
source. Check BEFORE pricing:
- `GET /events/{ticker}` → `settlement_sources[].name` + `url` (e.g. AAA
  gasprices.aaa.com), `strike_date`, `sub_title` (which day the print is for).
- Market closes BEFORE the source publishes (gas: closes 03:59Z, AAA prints
  ~14:00Z) — the market is a prediction on the print, not a reaction.
- The arb: if the source's CURRENT value already clears the strike (AAA
  $4.0960 vs "$4.095" strike), a flat-day thesis prices YES ~99c while the
  market may sit at 6c. Buy the misprice with source as independent prob
  (verified 2026-08-02: "above $4.095" YES @ 0.06, flat-day thesis).
- Risk: the market may be pricing mean-reversion (spike fading) the source
  hasn't printed yet. State both sides, VJ decides.

### Index-level ladders (CPI/PPI): implied-index math (2026-08-02)

For index markets (e.g. `KXCPINDEX-26AUG12` = July CPI print Aug 12), map
forecasts to ladder strikes:
`next_index = base_index × (1 + m/m_forecast)`.
Example: June 2026 CPI index ~333.8. Cleveland Fed nowcast +0.09% m/m → 334.1;
FactSet consensus +0.2% → 334.5; Goldman +0.27% → 334.8. Then compare each
scenario's implied P(≥strike) against the ladder's bid/ask:
- 334.0 strike at 43c vs consensus math 85% = candidate; 334.2 at 21c = only
  if you trust the hot source.
- **Source divergence kills the edge**: Cleveland Fed (0.09%) vs FactSet (0.2%)
  disagree enough that the ≥50% floor cannot be met with confidence → SKIP.
  Never pick a side until one source wins; a 0.1% m/m gap is 0.3-0.4 index
  points = several ladder strikes.

## Binary-risk communication (VJ correction 2026-08-02)

When presenting a trade, ALWAYS state TOTAL STAKE at risk, never per-contract.
VJ: "You set order for $1? I will lose $1, not 6c if I lose." A 16-contract
order @ 0.06 is $0.96 at risk — the 6c is the buy price, not the loss.
Binary math: stake $1, lose ~$1, win (1/price − 1). Present as:
`LOSE: <condition fails> → −$<stake> | WIN: <condition hits> → +$<payout>`
whenever the number of contracts ≠ 1.


## Hard rules (VJ, 2026-08-02)

**THE ONLY SUCCESS METRIC IS MARGIN OF PROFIT.** Sole purpose: maximize
profits. Win rate is vanity — judge every decision by P&L/invested, not
wins. Apply Karpathy metric-vs-decision analysis: trace each decision to
its effect on profit margin, hypothesize the gap driver, propose smallest
fix, measure again. Losing trade that followed process = data. Winning
trade that broke process = luck. Both get analyzed.

- **NEVER BET IF OUTCOME PROB < 50%** (ALL bets, not just live). Prob must be individually established from INDEPENDENT source: Polymarket cross-venue price (arb) or verifiable research — Kalshi's own book alone is NOT valid. Carry it in `sig.approved_price`/`ev_calc.price_side`; guard `min_win_prob: 0.50` refuses missing/<50% (`override_win_floor` = explicit user confirm only). Sub-50% = lottery = never. Even SUGGESTING sub-50% markets is suppressed in scan shortlist (rule 16).
  - **NO-side semantics**: for a NO buy, `approved_price` carries the independent NO prob (1 − indep YES). pre_flight NO branch enforces it too. Example: FEDHIKE-26DEC31 NO @ 0.32 with indep NO prob 0.68 passes the guard — but VJ rejected it on the midterm cut-then-hike thesis (not a guard failure).
  - **Midterm Nov 3 2026**: Fed may CUT pre-election (political pressure), then HIKE by Dec — invalidates naive "no hike by Dec 31" bets. FOMC dates: Sept 16, Oct 28, Dec 9 (NO Nov meeting). Full calendar + market expressions: `references/us-macro-2026.md`.
- **CONSOLIDATED GATE**: `risk.pre_flight_check(sig, limit, cfg)` runs ALL rules (limit-only, win floor incl NO side, band, raise, no-margin) on EVERY execution path. Never add one-off guards in executors — patch pre_flight instead.
- **LIMIT ORDERS ONLY — NO MARKET ORDERS EVER.** `kalshi.place_order` hard-asserts a valid limit price (0<p<1); `LiveExecutor.execute` refuses None/invalid limits. Never convert to market.
- **Price raise guard**: `execution.max_price_raise_pct` (default 10). Never pay more than 10% ABOVE the approved/reference price (`sig.ev_calc.price_side` or `sig.approved_price`) — fails closed. Below approved is always fine (maker edge). Plus `max_buy_price_cents: 40` hard band on BUY YES (`override_price_band` to bypass). Triggered by the Donski incident: approved 0.34 underdog, stale scan book repriced to 0.93 in-play, order filled 0.90. Always pass the approved price into sig when placing user-picked trades so the guard has a reference.
- Live = `mode: live` + `venue: kalshi` only (Polymarket live needs wallet+gas).
- $1/trade cap, max open positions per config, per-buy approval (2h TTL, EV re-check, fails closed), NO MARGIN EVER (code asserts), NO stop-loss (ride to resolution).
- Auth: RSA-PSS, sign `{ts}{METHOD}{FULL path}` incl `/trade-api/v2` prefix
  (short-path fails strict endpoints). 401/429 transient — retry 5x backoff.

## Selection rules (VJ, 2026-08-02 — after underdog-lottery loss)

- **PRICE FILTER ≠ EDGE.** Listing markets below a price band (e.g. <35c) and
  letting VJ pick without research = losing pattern. One batch of 8 sub-35c
  tennis underdogs all resolved worthless — cheap YES = market already knows
  they lose ~95%. Research BEFORE presenting: no evidence = no override = no
  trade = SKIP. If nothing clears the research gate, say so and recommend skip.
- **Crypto: ≤1 month to expiry ONLY.** No 2-month+ price bets. Monthly strikes
  (Kalshi `KXBTCMAXMON-BTC-26AUG31`, Polymarket ≤31d windows).
- **Polymarket = TRUTH ANCHOR, ARB = SELL-ONLY ON KALSHI (VJ 2026-08-04,
  restated — supersedes all earlier sentiment/buy-side framing)**:
  PM is the better reflection of market truth (bigger, global, pioneer). Kalshi
  = execution venue only. When Kalshi price diverges from PM, evaluate ONLY
  options to SELL on Kalshi:
  - Kalshi RICH vs PM → SELL the Kalshi side (sell YES / buy NO at the rich
    level). Edge = overpricing capture. Win prob for the sell = 1 − PM-implied
    YES prob; sell only when PM-implied YES < Kalshi sell price.
  - **NO BUY-SIDE CAPTURE.** Buying Kalshi YES because it's "cheap vs PM" is a
    directional bet, NOT arb. If Kalshi is not rich on a side → SKIP.
  - Example 2026-08-04: Kalshi BTC 60K one-touch 0.49/0.50 vs PM dip-to-60K
    0.45/0.46 → SELL YES at 0.50 (buy NO), edge +4c.
  - Execution stays Kalshi (wallet+gas not wired). RULES.md rule 9.
- **Ranked numbered table** (most → least favorable): market, side, price,
  my est, edge. VJ picks by row number ("let's do 2,4,8").
- **Live tennis IS in scope when VJ asks** — granular vehicle = set-winner
  markets (`KXWTASETWINNER-26AUG02PEGEAL-1-PEG`): mid-range price (0.05-0.95)
  = set in play, 0.90+ = nearly decided. Skip in-play only in the automated
  2h scan loop (micro-edge lost); user-directed live picks are fine.

## Loss retrospective workflow (VJ 2026-08-02)

When a batch loses, run this BEFORE proposing anything new:
1. Pull all session trades: `SELECT id, condition_id, side, size, fill_price, status FROM trades WHERE created_at > <session_start>`.
2. Exchange truth: `fetch_market_by_id` current px + `get_positions` (resolved = gone from positions).
3. Classify each loser: lottery (<50% outcome, no research), stale-price execution (book repriced, guard bypassed), or thesis-wrong.
4. Find the pattern — 2026-08-02: every loser was <50% outcome prob OR stale-priced; no independent prob consulted; suggestions made on price filter alone.
5. Codify a guard that PREVENTS the pattern class (win floor → all bets; suppression → don't suggest; pre_flight → one gate), not just the one loss.
6. Log the retrospective in RULES.md incident log, push to repo.

## Delivery discipline (VJ, 2026-08-01)

- **Suppress non-actionable alerts.** Cron/fast-loop output only when
  actionable: executable Kalshi-leg arb, order fill/cancel, resolution/P&L,
  position cap breach, errors. Discovery-only arbs (Myriad/Limitless/Opinion
  legs — no keys = not tradeable) are NOISE — never deliver. Silent output
  is correct output for a watchdog.
- VJ-relatable hunt categories: T20/cricket, crypto (BTC/ETH targets),
  economic (Fed/CPI/jobs), politics. Skip in-play markets (live tennis/MLB
  mid-game) — the 2h loop loses micro-edges and prices move >10c between scans.

## Category-targeted discovery (Kalshi)

Scan pipeline starves non-sports categories: `discover_markets` caps at
`max_markets` (40) and `/markets` pagination returns sports first, so the
40-slot fills with tennis/MLB before crypto/econ series are reached — even
though `categories: [crypto, politics, sports, economics]` is configured.
To actually surface crypto/econ/MLB markets:

1. Build series→category map: paginate `/events` (limit 200/page, ~45 pages
   for all open events), collect `series_ticker` + `category` per event.
   Cache 1h.
2. Pull per category: `GET /markets?series_ticker=<S>` for each series in
   the category (limit 500). Filter `market_type == binary`.
3. Evaluate top-N by `volume_fp × last_price_dollars` through the normal
   signal pipeline.

API quirks (verified 2026-08-02):
- `GET /markets?event_ticker=X` works — **this is the reliable event filter**.
- `GET /events/{event_ticker}/markets` returns **404** — do not use.
- `GET /events?category=Crypto` param is **ignored** — returns same events
  regardless of category value; category filter must be client-side.
- `GET /markets?series_ticker=` works; series names are `KXDOGE`, `KXETH`,
  `KXCPIYOY`, `KXMLB`, NOT guessed names like `KXBTCDEFAULT` (returns 0).
- **404 vs retry (fixed 2026-08-09):** `get_json` backoff-retried EVERY
  RequestException incl 404 — a bad ticker stalled 46s (1.5s×2^n). `HTTPError`
  subclasses `RequestException` so a bare `raise_for_status()` still retried.
  Fix: raise a custom `_NotFound` exception OUTSIDE the retry except — 404 now
  fails in 0.2s. When probing unknown tickers, expect fast 404, not hangs.

Re-runnable: `scripts/category_scan.py` (auth from env, args = category names).
Run it instead of hand-typing the auth boilerplate + pagination loop.

## Name search — use `scripts/search_market.py` (repo), NOT inline title search

Two bugs hid Tolev vs Cazacu (`KXATPCHALLENGERMATCH-26AUG02TOLCAZ`, 2026-08-02):
1. Inline title search capped at 10 matches — MVE parlay junk (player names in
   ticker) filled the cap before the real market was reached. Fix: full
   pagination (20 pages, `mve_filter=exclude`), NO early-exit cap.
2. Event filter used `KXATPMATCH` prefix — missed `KXATPCHALLENGERMATCH`.
   Fix: ticker-abbreviation matching against events cache (`TOLCAZ` =
   Tolev+Cazacu, ordered subsequence match) + title search both.

Usage:
`KALSHI_API_KEY=.. KALSHI_PRIVATE_KEY=.. python3 scripts/search_market.py tolev`
`python3 scripts/search_market.py cazacu --min-vol 1000`
Never hand-roll the search loop — the script is the fixed, verified path.

## Live-option flip scan (manual only, VJ 2026-08-09)

**MANUAL INVOCATION ONLY (VJ 2026-08-09): cron REMOVED** — VJ wants to run it
on demand ("scan live tennis"). No cron job. Run:
`python3 /data/workspace/predictor/scripts/live_flip_scan.py`
or ask Mando to scan. Surfaces LIVE markets where odds can flip for 30m/60m
TTL limit plays. Presents only 07:00-22:00 CT (VJ waking hours), silent
otherwise. Flip zone = mid 0.35-0.65, spread <=3c, depth >=200, vol >=$2k;
suggestion = cheap-side limit <=40c.

**2026-08-09 fix (was broken):** hardcoded `26AUG02` in the today-filter made
it silently scan LAST WEEK — returned "no flip-zone markets" while 100+ live.
Now dynamic `today_str = now_ct.strftime("%y%b%d").upper()` + live `/events`
fallback when cache empty. Verified: found live markets same-day.
Script: `~/.hermes/scripts/live_flip_scan.py` (repo copy is source of truth).

**BEFORE suggesting any live tennis: check format + live score.** Men's GS =
best-of-5 (3 sets to win), men's non-GS = best-of-3, women = best-of-3. Same
1-0 set lead means ~60-65% in Bo3 but far less in Bo5. Score sources, format
table, win-prob heuristic, and the live coin-flip structural SKIP are in
`references/live-tennis-scores.md` (VJ rule 2026-08-02: understand sport rules
before suggesting live bets).

**CROSS-VENUE LIVE FLIP — verify BOTH legs (VJ ask 2026-08-04):** when VJ
wants a "pmxt vs kalshi" live flip, a live-looking PMXT event is NOT proof of
a tradeable market. Hit live 2026-08-04: `fetchEvents(series=KXATPCHALLENGERMATCH,
exchange=kalshi)` returned Monteiro/Gentzsch ($576k vol) + Durasovic/Geerts
($464k) — both already FINALIZED on Kalshi (close 12:30Z). PMXT volume24h is
often the POLYMARKET-side volume, not Kalshi liquidity. Before presenting any
flip:
1. Resolve the Kalshi ticker native (`/markets?event_ticker=` or slug lookup)
   and check `status` + `close_time` — finalized/closed = drop.
2. Pull the native orderbook — Kalshi ATP markets with 0 volume show a
   placeholder 0.01/0.99 book. Empty book = no Kalshi leg = NO executable flip
   (can't hedge on air).
3. Live tennis volume mid-day US sits on Polymarket; Kalshi ATP trades in
   morning (EST starts) + evening (Europe/Asia) windows. Mid-day = Kalshi gap.
Full recipes, API field traps, and the 429 backoff pattern:
`references/cross-venue-live-flip.md`.

## Geopolitical updates — DeItaone feed (VJ rule 17, 2026-08-02)

For geopolitical/macro updates that move oil, gas, Fed, or election markets,
rely on the LATEST TWEETS from `https://x.com/DeItaone` (sorted newest) as
source of truth for breaking geo/macro news. Applies to all macro-news-driven
analysis (WTI spikes, gas, sanctions, Fed surprises, election shocks).

**DeItaone = *Walter Bloomberg** (id `2704294333`, 1.78M followers, Premium+,
verified, 192k tweets). Fetches that WORK (verified 2026-08-02, xurl 1.3.1
with OAuth1 creds from `~/.xurl`):
```bash
# install once, PERSISTENT drive (npm global = ephemeral container FS):
mkdir -p /data/.hermes/home/.local && cd /data/.hermes/home/.local
npm install @xdevplatform/xurl          # -> node_modules/@xdevplatform/xurl/cli.js
ln -sf /data/.hermes/home/.local/node_modules/@xdevplatform/xurl/cli.js \
       /data/.hermes/home/.local/bin/xurl
# run with HOME pointed at the dir holding .xurl auth:
HOME=/data/.hermes/home /data/.hermes/home/.local/bin/xurl user @DeItaone
HOME=/data/.hermes/home /data/.hermes/home/.local/bin/xurl \
  '/2/users/2704294333/tweets?max_results=10&tweet.fields=created_at,public_metrics,entities'
```
If xurl unavailable: `web_extract` on the profile URL (X may rate-limit).

- Codified in RULES.md rule 17 + memory `[GEOPOLITICS]` — both carry the
  same rule; repo is source of truth.
- **GEO FEED BEATS OPTIONS READ (2026-08-02 lesson)**: USO post-market showed
  +3.5% (bullish WTI read), but DeItaone feed simultaneously carried Hormuz
  deal-in-sight / Iran talks Monday → BEARISH oil. A WTI ≥84.49 spike-strike
  candidate was killed by the feed. Check the feed BEFORE deciding a
  daily-settle strike is mispriced — the market may already be pricing the
  headline, and the options/ETF read without geo context is directionally
  fragile. Sequence: DeItaone feed → then options/technicals → then ladder.

## Geo-trades — 7pm CST window ONLY (VJ rule 18, 2026-08-02)

Geopolitical choke-point incidents (Hormuz, Suez, Bab el-Mandeb, straits) →
**oil ▲, gold ▲, VIX ▲, risk-OFF**. De-escalation → inverse (risk-ON).

- **Window: 19:00-20:00 America/Chicago ONLY.** After-hours geo read (Sunday
  PM post-move sets the tone for the week). Unless VJ says otherwise, do NOT
  run geo analysis at other times.
- **Server clock is UTC.** 7pm CT = `0 0 * * *` UTC (00:00 next day) — NOT
  `0 19 * * *` (that fires 19:00 UTC = 14:00 CT, wrong). Cron `geo-trades-scan`
  uses the 00:00 UTC schedule.
- Script `scripts/geo_scan.py` (repo + `~/.hermes/scripts/` copy): pulls
  DeItaone latest 20 tweets → keyword-classify (ESCALATION / DE-ESCALATION /
  MIXED + choke-point flags) → direction score → Kalshi WTI/gold shortlist.
  Self-gates: emits NOTHING unless 19:00-20:00 CT (watchdog pattern, empty
  stdout = silent cron). Test recipe: monkeypatch `gs.datetime` to a fake
  19:30 CT datetime to force the window.
- **Shortlist 👍 marker (VJ 2026-08-05)**: geo shortlist rows carry ` 👍` when
  aligned with the geo direction AND in the tradable band — RISK-OFF → YES
  bid ≤0.40; RISK-ON → NO side (YES ask ≥0.60). NEUTRAL/unaligned = no
  marker. Same decision-marker convention as proposals (👍 = recommended).
- **TRUMP = BIGGEST MARKET MOVER (VJ 2026-08-02)**: market-moving tweets from
  the US president (via DeItaone) dominate direction. His ceasefire/deal/talks
  words COOL oil/commodities/commerce (risk-on); his strike/tariff/threat
  words SPIKE them (risk-off). Classification adds TRUMP-ESCALATION,
  TRUMP-DE-ESCALATION, TRUMP-MIXED, TRUMP-TRADE (★ marker in output).
  Direction score = (choke_dee − choke_esc)×2 + (recent6_dee − recent6_esc)
  + (t_dee − t_esc)×3 + (t_trade − t_mixed)×2 — Trump weighted 3×.
  Verified live 2026-08-02: "TRUMP: I THINK THERE IS A DEAL ON HORMUZ" →
  TRUMP-DE-ESCALATION → RISK-ON (oil ▼). Tariff tweets = commerce/commodity
  direction, not just oil.
- Kalshi series map: WTI `KXWTI` (daily settle 18:30Z; `KXWTIMAX`/`KXWTIMIN`
  monthly), Brent `KXBRENTD`, gold `KXGOLDD` (daily) / `KXGOLDMON` (monthly).
  **No VIX binary on Kalshi** — VIX is directional read only.
- Direction → shortlist: risk-ON (de-escalation) = oil/gold BELOW strikes (NO
  side or cheap low strikes); risk-OFF (escalation) = above strikes, cheap
  high strikes. Same gates as any hunt: limit-only, YES ≤40c, ≥50% win floor
  from independent source (here: the geo feed itself).
- Verified 2026-08-02: feed classified Hormuz deal-in-sight as DE-ESCALATION →
  RISK-ON (oil ▼). Correctly killed the USO post-market +3.5% → WTI-spike
  thesis.

## Maker bid — VOLUME-PEAK, follow the money (VJ 2026-08-02, supersedes peak rule)

`_maker_level` in `predictor/risk.py` chooses the resting bid. VJ rule:
**ALWAYS go by volume — the market leans where the money sits, not where
market makers bait. FOLLOW THE COLLECTIVE INTELLIGENCE, FOLLOW THE MONEY.**
Thin top-of-book bids are bait; the wall of size is the real lean. This
REVERSED the earlier "exclude tail outliers / normal-distribution peak"
version (2026-08-02 morning) — VJ explicitly rejected pricing away from
volume. Applies to YES and NO sides (NO uses `ask_ladder` = no_dollars
directly, never invert with 1-p).

**DENSITY MODE, not arithmetic mean** — the mean fails on bimodal books.
Verified failure (2026-08-02 Brent): wall 0.45×5000 + deep tail 0.01×2018
dragged size-weighted mean to 0.23 (wrong, bait level). Algorithm in
`_maker_level`: qualifying levels (≥2c below ref, ≥100 size) → for each
level sum sizes of all levels within ±3c (neighborhood) → pick the level
with MAX neighborhood volume (density peak = where money concentrates),
ties → cheaper level (more edge as maker). Verified: Brent 0.45 (wall),
WTI 0.36 (cluster), normal book 0.14.

**TRASH-FLOOR FILTER (VJ 2026-08-03, AFFO lesson, commit c5b8741)** —
density mode alone FAILS on books with deep lottery bids: AFFO
`0.01×533 + 0.13×104` — naive density peak picks 0.01 (the floor) while
the REAL wall is 0.13 (where VJ filled). Deep near-zero bids are lottery
liquidity, NOT directional lean. `_maker_level` now drops levels below
`max(0.05, 0.25 × ref_price)` BEFORE density mode. Verified after fix:
AFFO → 0.13, COMM → 0.13, Brent → 0.44-0.45. When quoting a candidate
level to VJ, ALWAYS read the FULL ladder (`orderbook_fp.yes_dollars`
ascending) and name the wall, not the top-cluster VWAP — top-3c cluster
can be thin bait (AFFO cluster VWAP 0.178, vol 28 vs wall 0.13×104).

**"buy wall" phrasing = wall level, NOT top-of-book (VJ 2026-08-05).**
When VJ says "buy 1x yes at buy wall limit", the limit = the volume-peak
wall level from density mode — even if best bid sits HIGHER (Ribecai:
top bid 0.80 vs wall 0.76×71K; order rested at 0.76 per instruction).
Top-of-book is the fast fill but costs more; wall is where the money
concentrates and where VJ wants the maker entry. Don't second-guess into
the tighter level.

## Batch order placement — VJ "buy all" pattern (2026-08-03)

When VJ directs a multi-market batch ("buy all", "max bid $X per order"):
1. Pull orderbooks for EVERY ticker first — never place from quotes alone.
2. Per order: limit = wall level (trash-floor + density peak above),
   count = floor(notional_cap / limit) — e.g. $1.20 cap → 5 @ 0.22 = $1.10.
3. Carry independent est in `sig.approved_price` + `ev_calc.price_side`
   (pre_flight floor/raise gates). `override_price_band: True` per VJ
   direction for the near-certain >40c class (NOT standing — per-batch).
4. TTL = timed-event start (rule 5a); for mention calls bypass LiveExecutor
   1h default via `kalshi.place_order(hours_to_expiry=0,
   max_lifetime_hours=8.0)` keeping `risk.pre_flight_check`.
5. Verify every order: `get_orders(status="resting")` → see field trap.

## NO-order price inversion (Kalshi V2, hit live 2026-08-06)

**Kalshi quotes EVERYTHING from the YES side** (docs: "`ask` means sell YES.
Selling YES is economically equivalent to buying NO at `1 - price`"). The
create-order `price` field is ALWAYS the YES-side price — even for a NO buy.

Bug hit live: `place_order(ticker, "NO", 1.0, 0.46)` sent body
`side: ask, price: 0.46` → exchange read it as sell-YES @ 0.46 = **buy NO @
0.54** → crossed the YES bid and FILLED at the wrong (worse) price. A second
order `NO@0.52` rested as buy-NO @ 0.48 — wrong level. Symptom in the order
object: `outcome_side: "no"` + `no_price_dollars` = `1 - sent` instead of the
intended NO limit.

Fix: **BUY NO at limit L → send `price = 1 - L`**. Applied in
`LiveExecutor.execute` (buy path only): `api_price = 1 - limit if side NO`.
`place_order` itself stays raw (YES-side); reduce_only exits pass YES price
directly (cli close). Verify after placement: resting order must show
`no_price_dollars == intended NO limit`, `expiration_time` = target TTL.

**FRESH SELL (non-exit) = YES price direct too** (verified live 2026-08-08):
`place_order(ticker, "SELL", 1, 0.44)` → body `{side: "ask", price: "0.4400"}`,
order object `action: sell, book_side: ask` — correct sell-YES @ 0.44. The 1−L
conversion applies ONLY to BUY NO; any sell (exit or fresh) quotes the YES side
directly. Resting sell confirmed via GET `/portfolio/orders/{id}`:
`initial_count_fp 1.00, fill_count_fp 0.00` = resting, TTL from
`expiration_time`.

**VERIFIED LIVE 2026-08-06 (OTM 1c test, T3451.99)**: sent
`place_order(NO, 0.99)` → filled buy NO @ 0.01 (`no_px 0.0100`,
`outcome_side: no`, `status: executed`). Mechanics confirmed end-to-end.
Also proven by test:
- `side: "no"` in create body → **400 `invalid_order: side must be bid or ask`**.
  API accepts ONLY `bid|ask`; "Buy No" in the mobile UI is a display label —
  wire format is always the YES-side ask.
- Extra body fields `action`/`outcome_side` are accepted but IGNORED —
  exchange normalizes every order to `side: yes|no` + `action: buy|sell`
  derived from book_side + price.
- V1 `POST /portfolio/orders` still returns 410 (deprecated) — the Octagon
  bot's `placeOrder` uses this stale endpoint; do not copy it.

**Local DB `limit_price` is NOT exchange truth.** It records the INTENDED
limit; the resting order object's `yes_price_dollars`/`no_price_dollars` is
what the exchange actually holds. The 2026-08-05 gold NO@0.46/0.52 orders had
the SAME inversion (yes_px 0.46/0.52 → NO 0.54/0.48) but expired unfilled, so
the wrong resting price never surfaced. Always check the exchange order object
before claiming a NO buy rests at the planned level.

**UI DISPLAY NOTE (VJ flagged 2026-08-06):** API-placed NO buys display in the
Kalshi app as **"Sell 1 Yes (P¢)"**, NOT "Buy No". Both are `book_side: ask`,
economically identical (sell YES @ P = buy NO @ 1-P), `outcome_side: no`.
VJ's own UI "Buy No" orders tag `side: no | action: buy`; API asks tag
`side: yes | action: sell`. When reporting NO orders, preempt the confusion —
state they will show as "Sell Yes" in the app and that it IS a NO buy, not a
sell. VJ questioned this exact display on 2026-08-06 ("why are we selling yes
on gold and not buying no?").

**EXPLICIT DATE TTL (VJ 2026-08-06):** "TTL 1 day before outcome date" =
`close_time − 24h` (gold monthly close Aug 31 21:00Z → expiry Aug 30 21:00Z).
Bypass the 24h cap with raw `kalshi.place_order(..., hours_to_expiry=0,
max_lifetime_hours=<hours to target>)` so `expiration_time` lands exactly on
the target; keep `risk.pre_flight_check` + `risk.wall_check` as gates. Also
recompute the wall from the live book at redo time — walls move between
sessions (Aug 5 NO walls 0.46/0.52 → Aug 6 0.48/0.54).

## Predictor stack — research-to-code additions (2026-08-06, VJ-ordered)

Research findings below are now CODED, not just documented. Verify these exist
before re-implementing; they run inside the normal gates:

- **`predictor/fees.py`** — Kalshi fee engine: `0.07 × p × (1−p)` per contract
  (0.0175 maker-fee tickers), rounded UP to cent; `net_edge_after_fees()`;
  `ARB_ALWAYS_LOSE_EDGE = 0.02` raw-edge floor. Use for ANY edge/arb math.
- **`predictor/arb.py` `synthetic_arb`** — now subtracts REAL Kalshi fee
  (was `$0` → fabricated fake arbs). Raw edge < 200bps never surfaces.
- **LIQUIDITY GATE** in `LiveExecutor.execute` (`override_liquidity` bypass):
  spread ≥ `max_spread_cents`(5) OR vol24h < `min_volume_24h`(500) blocks
  notional ≥ `liquidity_block_notional_usd`(5). VJ micro orders ($1-2,
  hold-to-resolution by design) WARN + proceed — exit trap doesn't apply.
- **DRAWDOWN CIRCUIT BREAKER** (`risk.check_drawdown_circuit_breaker`): blocks
  new live trades when drawdown from high-water ≥ `max_drawdown_pct`(0.20).
  Runs inside LiveExecutor.execute after pre_flight.
- **`scripts/monotonicity_scan.py`** — ladder monotonicity arb scanner
  (KXGOLDMON/KXWTIMAX/KXWTIMIN/KXBTCMAXMON/KXBTCMINMON). Live run found 32
  violations, ALL no-edge after fees — filters correctly. Run:
  `python3 scripts/monotonicity_scan.py [SERIES|--all] [--min-vol N] [--json]`.
- **Weekly review** (`scripts/weekly_review.py`) — prints WILSON lb95 (not
  point WR) + COHORT SPLIT (price bucket × side, N≥3, RETARGET flag when
  n≥5, lb95≥40%, margin>0). MARGIN OF PROFIT stays the only go/no-go.
- **Repo hygiene (VJ 2026-08-06)**: GH repo carries DISTILLED findings only
  (`RESEARCH_FINDINGS.md`) — never vendor raw third-party repos. Raw clones
  stay in `/data/workspace/research/` (outside git) for depth.

## Kalshi fee economics + structural arbs (from external research, 2026-08-06)

Source: `/data/workspace/predictor/RESEARCH_FINDINGS.md` (assimilated from
AKCodez playbook, PolyKalshi_Client, Octagon kalshi-trading-bot-cli — clones in
`/data/workspace/research/`).

- **Fee = 0.07 × p × (1−p) per contract** (rounded up to next cent); maker-fee
  tickers (KXFEDDECISION, KXATPMATCH, KXWTAMATCH, KXCPI, KXGDP, KXPAYROLLS,
  KXNFLGAME, tennis GS singles, MLB, NHL, NBA...) pay **0.0175 × p × (1−p)**.
  At p=0.50 general fee = 1.75%/contract; at extremes (0.05/0.95) = 0.33%.
  **Cross-venue arb needs ≥400bps raw edge to survive round-trip fees** —
  subtract fee from edge before declaring.
- **NO ask (cost to BUY NO) = 1 − yes_BID, NOT 1 − yes_ask.** Using
  `1 - yes_ask` underestimates by the full spread and fabricates fake arbs
  (playbook: "almost fired a losing trade"). NO bid (seller receives) = 1 − yes_ask.
- **Ladder monotonicity arb** (KXGOLDMON/KXWTIMAX/KXBTCMON): P(>lower) ≥
  P(>upper) by definition. If `ask_yes(lower) < ask_yes(upper)` → buy lower YES
  + upper NO. Thin depth, real but small. Check NO leg at `1 − yes_BID`.
- **Clear-win convergence FAILED on commodity/macro** (oracle-feed divergence)
  — only sports/weather are clean. Our econ markets resolve on FRED/CPI:
  don't buy "99c certainty" on macro.
- **Kalshi WebSocket** (future fast-tier upgrade): `wss://api.elections.kalshi.com/trade-api/ws/v2`,
  subscribe `{"id":1,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_tickers":[ticker]}}`,
  msg types: `error/ok/orderbook_snapshot/orderbook_delta` (delta carries `seq`).
  Channels: `orderbook_delta`, `ticker`, `trade`, `fill`.
- **Spread/volume entry gates**: skip new entries on spread ≥5c or vol24h <$500
  (thin-book trap; exit = walk bid ladder, 17pp+ spread = abandoned).
- **Weekly review**: quote Wilson lb95 (not point WR); run cohort split
  (price bucket/side/category/day) before any strategy verdict. MARGIN OF
  PROFIT stays the only go/no-go.

## ⚠️ Supply-chain vetting — third-party "Kalshi bot" repos (2026-08-06)

`else24/kalshi-market-bot` (GitHub) was MALWARE, not a bot: fake Textual TUI +
trivial strategy.py as cover, real payload in `syslib/` = C2 beacon
(`https://api.failproxy.space`, TLS verification DISABLED), reflective PE
loader (VirtualAlloc→segments→relocs→imports→CreateThread, Windows-only), and a
14MB `base.pkg` ZIP that extracts `python.exe` then downloads "signed strategy
bundles" on startup. Full IoCs in `RESEARCH_FINDINGS.md`.

Vetting protocol before integrating ANY external trading repo:
1. `find . -type f | grep -vE "__pycache__|\.git"` — map the whole tree, don't
   trust the README feature list.
2. Read every file that does network I/O or ctypes — check for obfuscated
   endpoints (byte-list encoded URLs), disabled TLS verification, hardcoded
   keys, `VirtualAlloc`/`CreateThread`/PE-parsing (MZ/0x5A4D).
3. Check bundled binaries: `base.pkg`/`.bin`/`.dat` — `file`, magic bytes,
   ZIP listing. A 14MB embedded "runtime" is a dropper smell.
4. `grep -rn "check_hostname = False\|CERT_NONE\|VirtualAlloc\|CreateThread"`
5. Never run `main.py`/`setup.py` from an unvetted clone. Clone only, inspect,
   integrate pieces manually. Our own predictor stack is the execution path —
   external repos are reference for IDEAS only.

## Resting-order field names (trap, hit 2026-08-03)

`get_orders` resting objects do NOT use `price`/`count`. Real fields:
`initial_count_fp` (ordered qty), `remaining_count_fp`, `no_price_dollars`
(YES limit = `1 − float(no_price_dollars)`), `expiration_time`,
`status: "resting"`, `side: "yes"` lowercase. Naive
`float(o.get("price"))*float(o.get("count"))` prints $0.00 for every order
and looks like placement failure. Verify notional:
`(1 − float(o["no_price_dollars"])) * float(o["initial_count_fp"])`.

## Weekly order review — Sun 1am CT (VJ rule 19, 2026-08-02)

Recurring self-improvement loop. Cron `weekly-order-review` fires `0 6 * * 0`
UTC = **Sun 1:00 AM CT** (server UTC; 1am CT = 06:00 UTC next-day mapping —
same UTC discipline as the geo 7pm cron). Agent-driven (needs report writing),
skills loaded, delivers to origin.

Flow (scripts/weekly_review.py, repo + ~/.hermes/scripts/):
1. Week bounds: review the week BEFORE the previous Sunday. Run on Sun Aug 9
   → covers Jul 26-Aug 1 (Sun-Sat). `week_bounds(now)` computes
   this_sun → prev_sun → target = prev_sun−7d .. prev_sun (end EXCLUSIVE =
   prev Sunday 00:00 CT). ⚠️ Docstring in the script says "Aug 2-Aug 8" —
   WRONG, stale. Code + this reference agree on [prev_sun−7d, prev_sun).
   Consequence: the first live day (Aug 2 batch: BTC one-touch, Fed,
   challengers, Ribero, WTI/Brent) lands in the NEXT review's window, not
   the one run on Sun Aug 9.
2. Pull fills: `kalshi.get_fills(limit=1000)` (exchange = source of truth),
   filter created_time to target week (UTC→CT conversion).
3. Success rate + P&L: resolve each market — **RAW `status`/`result` fields
   are truth, NOT the normalized market object** (verified 2026-08-09):
   `fetch_market_by_id` → normalized `outcome_prices` = `[0.0, 1.0]`
   placeholder for EVERY market (mangled by normalize_market) and `closed`
   always False even when `status=finalized` → script prints "NO RESOLVED
   TRADES" on a week with a finalized winner. Correct read:
   `kalshi.get_json(f"/markets/{ticker}")` → `market["status"]=="finalized"`
   + `market["result"]` ("yes"/"no"). win = qty×(1−price), loss = −qty×price.
4. ⚠️ **Exit fills fall outside the window**: an in-window BUY whose SELL
   lands next day (ZAR 08-09: buy Aug 1 18:18 CT in-window, exit Aug 2 12:36
   CT out-of-window) is dropped → realized −$0.0441 never counted. Match
   same-market opposite-side fills across the boundary to get true
   round-trip P&L; a lone buy treated as "resolved win" overstates margin.
5. Failure-mode split: mechanical markers = losses on high buy prices
   (>0.30) = price-risk/stale-execution class; otherwise thesis-driven.
6. If mechanical losses → produce CAVEMAN Karpathy-autoresearch-style report:
   STATE → ANALYZE → HYPOTHESIZE → FIX PROPOSAL (easy to follow, engineering
   tone). **Implementation changes ONLY on VJ approval** — the review
   proposes, VJ disposes. Never auto-patch code/config/orders from a review.
7. Codify any confirmed fix into RULES.md + config + code, push to repo
   (only after VJ says yes).

Karpathy autoresearch style = explicit state/observation → hypothesis →
experiment/fix proposal loop, self-contained, no vague "improve things"
phrases. VJ wants the FAILURE MECHANISM identified (which rule/guard was
missed), not just "we lost money".

## GH repo auto-sync — incremental backup (VJ 2026-08-06, HARD requirement)

**VJ requires skills + tool changes synced to github.com/vijaycinn/predictor by
DEFAULT for incremental backup.** Do not leave skill patches or code changes
local-only. Mechanism:

- `scripts/auto_sync.sh` (repo + `/data/.hermes/scripts/` copy): mirrors trading
  skills (`/data/.hermes/skills/research/{predict,prediction-market-live-ops}`)
  into `skills/`, `git add -A` (code/config/docs/skills), silent commit+push
  when changed, silent when clean. Watchdog pattern: empty stdout = no change.
- Cron `auto-sync-backup` (job 55b26aca885b): every 2h, `no_agent=true`,
  deliver local. Zero LLM dependency — immune to provider outages.
- Manual trigger anytime: `bash /data/.hermes/scripts/auto_sync.sh`.
- Push failure prints `PUSH FAILED` + non-zero exit → cron alerts (broken
  backup must not fail silently).
- After ANY `skill_manage` patch in a session, the next 2h tick captures it;
  for immediate backup run the script. GH repo is the durable copy — memory
  (per-turn store) stays outside git by design.
- Repo carries DISTILLED findings only (RESEARCH_FINDINGS.md, skills/, RULES) —
  never vendored raw third-party repos (VJ rejected that 2026-08-06).

## Cron script copies — repo-path detection (`_repo_path` pattern, 2026-08-02)

**CRON SCRIPT DIR = `/data/.hermes/scripts/` — NOT `~/.hermes/scripts/` (hit live 2026-08-03).**
With HOME=/data/.hermes/home, `~/.hermes/scripts/` expands to
`/data/.hermes/home/.hermes/scripts/` — a DIFFERENT directory. Cron resolves
relative script names against `/data/.hermes/scripts/`; copying there instead
produces `Script not found: /data/.hermes/scripts/x_news_pull.py` at run time
(even though manual runs from the other path work). Fix: `cp <repo>/scripts/<name>.py /data/.hermes/scripts/`
then verify with `cronjob action=run`. Every skill reference to "the cron copy"
(`live_flip_scan.py`, `geo_scan.py`, `fast_loop.py`, `x_news_pull.py`) means
`/data/.hermes/scripts/`.

**PURE-PULL JOBS → `no_agent=true` (VJ 2026-08-03, deepseek 503 lesson).**
Agent-driven cron jobs die when the LLM provider is down. Failure signatures:
`TimeoutError: idle for 600s ... waiting for non-streaming API response`, or
`HTTP 503: Service is too busy` after 3 retries. A `no_agent=true` job
delivers script stdout verbatim with ZERO LLM dependency — immune to provider
outages. Convert data-collection/news-feed/watchdog jobs to no_agent=true;
reserve agent-driven for jobs that genuinely need reasoning. When debugging a
failed cron, check the job's `no_agent` flag: a script that runs fine manually
can still fail as an agent job (LLM step, not script).

Any script copied to `~/.hermes/scripts/` for cron use BREAKS `sys.path`
assumptions built for the repo location. Hit live 2026-08-02:
`geo_scan.py` from cron dir failed with `No module named 'predictor'` —
its `sys.path.insert(0, dirname(dirname(__file__)))` resolved to
`~/.hermes/` (the cron dir's grandparent), not `/data/workspace/predictor`.

Durable pattern: a `_repo_path()` helper that detects the cron copy and
resolves the repo root explicitly:
```python
def _repo_path():
    here = os.path.dirname(os.path.abspath(__file__))
    # cron copy: ~/.hermes/scripts -> parent dir is ".hermes"
    if here.endswith("scripts") and os.path.basename(os.path.dirname(here)) == ".hermes":
        repo = "/data/workspace/predictor"
        return repo if os.path.isdir(os.path.join(repo, "predictor")) else None
    # repo copy: <repo>/scripts -> parent is repo
    return os.path.dirname(here)
```
Use it at EVERY `sys.path.insert(0, ...)` + `from predictor import ...` site
in a script (geo_scan had TWO — feed pull and shortlist block; the first
stayed silent via try/except while the second printed the failure). Always
verify from the cron dir: `cd ~/.hermes/scripts && python3 <script>` with a
forced window (monkeypatched clock) before trusting the cron run. Keep repo
copy as source of truth, `cp` to `~/.hermes/scripts/` after edits.

## Macro news feed — VJ forwards → MACRO_NEWS.md (2026-08-02)

VJ pastes/forwards macro-economic news batches (jobless claims, CPI, personal
income/spending, Fed chatter) to provide perspective for choosing Kalshi
markets. Workflow (avoid context bloat — memory holds a pointer only):

1. **Persist**: append each forwarded batch to `MACRO_NEWS.md` (repo,
   `/data/workspace/predictor/`) with: the raw numbers, per-item read
   (beat/miss/in-line vs consensus), and the Kalshi implication.
2. **Map data → markets** (2026-08-02 example):
   - Jobless claims beat + real spending beat = labor tight, consumer solid →
     **Fed HOLD bias strengthened** → check `KXFEDDECISION-26SEP-H0` (hold),
     `KXFEDDECISION-26OCT-C25` (cut), `KXRATECUT-26DEC31` (any cut by Dec).
   - Cut odds collapsing (KXRATECUT 0.14) = your Oct-cut YES position rides
     AGAINST the data — flag it, don't hide it.
   - Strong data = no recession signal → equity-downside markets weak.
   - Income miss = only soft spot → watch consumption follow-through.
3. **Cross-venue sanity** (VJ 2026-08-02): compare Kalshi position cost vs
   Polymarket gamma price for the same event (e.g. Hormuz normalization: our
   Kalshi 4@0.35 vs Polymarket 0.125 = underwater — surface the delta).
4. **Chain the read**: FOMC rates → economic data markets → equity → commodity
   → allied (oil/gas/gold/crypto). One macro batch re-prices the whole chain.
5. **PMXT/Predexon trending**: PMXT "feed down" (JSON parse fail) is usually
   a HIDDEN 429 `Rate exceeded.` (plain-text body, SDK shows
   `Expecting value: line 1 column 1`) — retry with backoff, batch in one
   script, don't conclude dead feed (see `references/pmxt-mcp.md`). Predexon
   v1 API deprecated (410, use /v2) with key tier blocking trending — when
   both fail, Polymarket gamma `/markets?order=volume24hr` is the working
   trending source.

## X news pull — DeItaone twice daily (VJ 2026-08-03)

Daily market-news briefs from DeItaone (Walter Bloomberg), separate from the
7pm CT geo-trades scan. Two cron jobs, both run `scripts/x_news_pull.py`
(repo + `/data/.hermes/scripts/` copy — the cron dir):
- `x-news-pull-morning`: 14:15 UTC = 9:15am CT (`15 14 * * *`)
- `x-news-pull-evening`: 02:15 UTC = 9:15pm CT (`15 2 * * *`)
Script fetches DeItaone latest 20 tweets via xurl (`XURL_BIN` env,
`HOME=/data/.hermes/home`, DEITAONE_ID 2704294333), prints `[HH:MMZ] text`.
**Both jobs are `no_agent=true` (changed 2026-08-03 after deepseek 503 killed
the agent step) — script stdout delivers verbatim, zero LLM dependency.**
No self-gate (cron controls timing) — unlike geo_scan's watchdog pattern.
Verified: `max_results` min is 5 (3 → invalid request). Geo-trades 7pm scan
untouched (rule 18).

## Kalshi live quotes — market object is TRUTH (2026-08-04, VJ correction)

`GET /markets/{ticker}` carries live quotes directly: `yes_bid_dollars`,
`yes_ask_dollars`, `last_price_dollars`, `open_interest_fp`,
`no_bid_dollars`/`no_ask_dollars`. **EMPTY `orderbook_fp` ≠ no liquidity.**
Hit live 2026-08-04: reported Kalshi BTC one-touch books "dead" because
`/orderbook` returned `{"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}`
while OI was 40k+ and live bid/ask existed on the market object. VJ corrected
with the market URL ("Not searching right?"). Orderbook gotchas: response key is
`orderbook_fp` (not `orderbook`); level entries are `[price, size]` STRINGS —
cast float everywhere (`float(x[1])>0`, never `>0` on str). Read market-object
quotes for liquidity truth; use orderbook only for level/wall analysis.

## HyperTracker (CoinMarketMan) — crypto perps research tool (2026-08-06)

Crypto market pricing/direction research source: `scripts/hypertracker.py`
(repo). Hyperliquid perps on-chain analytics — OI, funding, whale OI %,
24h whale bias per asset (BTC/ETH/GOLD/CL/BRENT + alts).

Two tiers:
- **FREE (no key)**: public perps dashboard is client-rendered — scrape via
  `web_extract` on `https://app.coinmarketman.com/hypertracker/perps` (raw curl
  returns a JS shell, no data). Parsed in-session, no script call.
- **API (HYPERTRACKER_API_KEY in /data/.hermes/.env, free 100 req/day)**:
  `scripts/hypertracker.py BTC,ETH --api` → liquidation heatmap export
  (price-bin liquidation VALUE + position counts — the REAL "62K pool" data),
  position heatmap (cohort long/short bias), liquidation fills. Base:
  `ht-api.coinmarketman.com/api/external/...`; docs docs.coinmarketman.com.
  Rate discipline: 100/day free — batch reads, don't poll.

Use for BTC one-touch thesis: verify liquidation-pool claims with on-chain
data instead of hearsay; map liq clusters → Kalshi strikes (round DOWN to
$2.5K ladder via `strike_map`). VJ set this up as the crypto research tool
for market pricing + direction (2026-08-06).

## BTC monthly one-touch — liquidation signals (2026-08-04)Series `KXBTCMINMON` ("How low will BTC get in <month>?", one-touch DOWN) and
`KXBTCMAXMON` ("How high...?", one-touch UP). Strikes every $2,500 (Aug 2026:
MIN 42.5k–60k, MAX 65k–82.5k), real OI (tens of thousands), early-close when
touched. For liquidation-pool signals ("longs clustered at $62K, likely swept"):
- nearest Kalshi strike = pool rounded DOWN to ladder (62K pool → $60K MINMON)
- pool level ≠ strike level — the gap is why the strike trades 49c, not 60c
- cross-check Polymarket "dip to $X"/"above $X" (gamma API) for independent prob
- VJ's down-ladder positions (57.5k/55k/52.5k MINMON) are the same thesis —
  a 62K sweep alone doesn't fill them
Detail + resolution rules + gamma quirks: `references/btc-one-touch-markets.md`.

## Polymarket US — live execution venue #2 (2026-08-05)

VJ's new US-regulated account. Ed25519 API keys (Key ID + base64 secret) in
`/data/.hermes/.env` as `POLYMARKET_API_KEY` / `POLYMARKET_SECRET_KEY`.
Auth = sign `{timestamp}{METHOD}{path}` (ms), headers X-PM-Access-Key /
X-PM-Timestamp / X-PM-Signature; timestamp within 30s of server time.

**pmxt PolymarketUS class is INCOMPATIBLE** — signs EIP-712 with an ETH
private key (EthAccountSigner), not Ed25519. pmxt = read-only/analysis for
polymarket_us. Native transport `predictor/polymarket_us.py` (verified live
2026-08-05: positions 200). Public reads need no auth:
gateway.polymarket.us `/v1/markets/{slug}/book` + `/bbo`; px/bestBid/bestAsk
are `{value, currency}` objects — unwrap before float().

**Placement = PolymarketUSExecutor** (`predictor/executor.py`): runs the SAME
gates as Kalshi — `risk.pre_flight_check` (limit-only, win floor ≥50% from
independent source, YES ≤40c band, ≤10% raise, no-margin) + `risk.wall_check`
(full-ladder volume wall) + `check_risk_limits` (position caps) + event-aware
TTL. Entry: `scripts/pmus_cli.py order --slug S --side YES --qty N --price P
--approved A --place` (dry-run default). TIF = GOOD_TILL_DATE (RFC3339
goodTillTime), maker-only participateDontInitiate. Order response `{id,
executions[]}`; fills = executions, resting = id only. Cancel:
`POST /v1/order/{orderId}/cancel` body `{marketSlug}`. Reconcile branch in
`reconcile_orders` reads `/v1/orders/open` (cumQuantity/leavesQuantity =
fill truth), detail via `/v1/orders/{id}`.

**Traps**: 400 code 3 = generic exchange rejection (account $0 → funding
blocker, not wiring). 20 rps/key rate limit; 5s latency stopgap on orders =
transient reject `Global Rate Limit Exceeded`, do NOT throttle (pure cancels
exempt). Sports-heavy catalog (NFL/MLB/tennis), tick 0.001. Verify fills via
`/v1/portfolio/positions` (exchange = truth, same discipline as Kalshi).
Full endpoint map, order payload schema, error semantics, data-shape gotchas
(`{value, currency}` px objects, Cloudflare 403 error 1010 without browser
UA), and the reusable venue-integration verification recipe (gate matrix
with synthetic ladders, live smoke):
`references/polymarket-us-api.md`. Quick auth sanity check (reads keys from
/data/.hermes/.env, never prints them):
`python3 <skill_dir>/scripts/pmus_auth_probe.py`.

## ITF event sourcing (2026-08-09, Huang/Cakarevic lesson)

- **ESPN misses ITF events entirely** — `espn_live --league wta` returns "no
  match found"; sports-hub scoreboard dump has no ITF rows. Do NOT burn time
  on ESPN for ITF.
- **Sofascore WORKS for ITF live scores** via web_extract on the match URL
  (point-by-point + set scores parseable). NOTE: the live-tennis-scores
  reference says "Sofascore 403" — that was a raw-curl block; web_extract with
  browser-grade fetch succeeds. Try web_extract before declaring Sofascore dead.
- **ITF official match page CACHES STALE** (itftennis.com/en/match?matchId=...):
  returned identical "2h 8m / In Progress" content on two fetches while the
  match was ~3h in. Cross-check elapsed time vs match start before trusting.
- **No PM.com listing for ITF singles** (gamma events scan empty) → no
  cross-venue truth → research-only, default SKIP unless edge is solid.
- **Robinhood prediction markets are KalshiEX-backed** — same underlying as
  Kalshi, NOT an independent source for rule-7 win floor. Robinhood page price
  (e.g. 37¢) IS the Kalshi book, just rendered. Sportsbook odds (FanDuel
  +100/-133) = sportsbook, not a prediction market — also not rule-7
  independent. Kalshi book alone stays invalid for ≥50% floor.
- **Market ticker ≠ event ticker**: URL path event `KXITFWMATCH-...HUACAK`
  404s as a market; real markets are `-HUA` / `-CAK` suffixes. Resolve via
  `/markets?event_ticker=<ev>` (never `/events/{ev}/markets` = 404).
- **Kalshi quote endpoint can lag the orderbook in-play** (Huang 08-09: quote
  0.41/0.44 vs live ladder top bid 0.35×9482, Robinhood 37¢). Read the
  full-ladder book for live win-prob, per Sabalenka lesson.

## References

- `references/hypertracker-perps.md` — HyperTracker (CoinMarketMan) crypto
  perps research: free dashboard scrape via web_extract, API endpoints
  (positions/heatmap, liquidation-heatmap export, liquidation fills), 100/day
  free quota, Kalshi strike mapping, script usage.
- `references/kalshi-research-findings.md` — condensed knowledge bank from
  external research (2026-08-06): fee economics, maker-fee tickers, NO-side
  formulas, structural arbs, Kelly/5-gate reference, Wilson lb95, antipatterns,
  Kalshi WebSocket, malware-vetting summary. Full narrative in repo
  `RESEARCH_FINDINGS.md`.
- `references/btc-one-touch-markets.md` — BTC monthly one-touch series map,
  resolution rules, liquidation-signal → strike mapping, Polymarket gamma
  cross-venue quirks (UA header, outcomes-as-JSON-string, bestBid/bestAsk).
- `references/kalshi-api.md` (in skill `predict`) — full auth + market data.
- `references/us-macro-2026.md` — midterm election Nov 3 2026, FOMC dates,
  cut-then-hike path, Fed market expressions (Kalshi + Polymarket).
- `references/live-flip-scan.md` — live flip-zone scan cron workflow.
- `references/live-tennis-scores.md` — tennis format rules (Bo5/Bo3), live
  score sources (tennisstats/Robinhood work, ESPN misses challengers, Sofascore
  403), score-state → win-prob heuristic, TTL-by-score-state, live coin-flip
  structural SKIP under band+floor rules, + pre-match research (stevegtennis.com
  H2H/form/event-stats incl. ITF/M25, sofascore start-time snippets, surface
  check) + ITF/doubles ticker prefixes.
- `references/cross-venue-live-flip.md` — PMXT-vs-Kalshi live flip hunt
  (2026-08-04): PMXT stale-event trap, native Kalshi series enumeration +
  orderbook_fp string-field traps, Polymarket gamma recipe (UA header, outcomes
  JSON-string, bestBid/bestAsk), 429 backoff, Kalshi ATP mid-day dead zone.
- `references/geo-trades.md` — rule 18 pipeline: DeItaone feed recipe + xurl
  persistent install, classification keywords, direction score, 7pm CT ↔ UTC
  cron mapping (`0 0 * * *`), Kalshi WTI/Brent/gold series map, verified
  Hormuz example, geo-feed-beats-options sequence.
- `references/weekly-review.md` — rule 19 weekly order review: Sun 1am CT
  cron (`0 6 * * 0` UTC), week-boundary math, success-rate/P&L calc,
  mechanical-vs-thesis split, Karpathy autoresearch report template,
  changes-only-on-approval gate.
- `references/pmxt-mcp.md` — PMXT MCP + SDK (2026-08-03): trading MCP vs
  Mintlify docs MCP distinction, Hermes MCP env filtering + wrapper-script
  pattern (key via ~/.hermes/.env, never --env literal), bursty 429 hidden
  behind `Expecting value` JSON errors, Router vs sidecar modes, UnifiedMarket
  field shapes, Router fetch_order_book limitation (use native kalshi module).
  + ORDER CREATION 410 (2026-08-05): `pmxt createOrder` on Kalshi routes
  legacy V1 → `HTTP 410: Please switch to the V2 endpoints`; place Kalshi
  orders via predictor `kalshi.place_order` only. pmxt = read-only for Kalshi.
  + PMXT SEARCH QUIRKS for Kalshi (2026-08-04): `fetchEvents(category="Fed")`
  returns volume-sorted junk (golf/baseball/senate — category filter ignored);
  `fetchMarkets(query="Fed decision September")` / `"S&P 500 up down today"`
  return `[]` for real markets. When ticker is known, go `fetchMarket(slug=...)`
  DIRECT (`KXFEDDECISION-26SEP-H0`, `KXFEDDECISION-26SEP-C25`,
  `KXRATECUT-26DEC31`). 3+ back-to-back `fetchOrderBook` calls → 429 fast;
  sleep ≥8s between or use `fetchOrderBooks` batch variant.
  + `fetchEvents(series=...)` returns STALE events — volume24h is often the
    Polymarket-side volume for matches ALREADY FINALIZED on Kalshi. Cross-venue
    methods (`fetchMarketMatches`/`fetchEventMatches`/`fetchArbitrage`) require
    `exchange="router"` — kalshi/polymarket return "Method not supported".
    Full recipe: `references/cross-venue-live-flip.md`.
- `references/investor-agent-mcp.md` — financial research MCP server
  (ferdousbhai/investor-agent): npm NOT published (build from source), Hermes
  config args-must-be-list trap, 7 tools, stdio test recipe, durability
  (/data/workspace), USO-options-as-WTI-proxy cross-check for oil/energy hunts
  incl. Sunday no-tape caveat.
- `references/earnings-mention-markets.md` — Kalshi earnings-mention keyword
  markets: anatomy (yes_sub_title holds keyword), transcript-research gate
  (PLTR COMM 0.26 vs 0.70+ misprice), phrase-search recipe, order mechanics,
  + NEAR-CERTAIN CLOSEBY limit-fill class (VJ 2026-08-03, PLTR REVE 0.894
  VWAP / +7.6c EV) — 40c-band exception GRANTED by VJ 2026-08-03 ("buy all",
  per-batch not standing; REVE/SLOP/MAVE/WERI/FOOD placed 0.56-0.89),
  + MULTI-COMPANY same-night hunt flow (2026-08-03): earnings_calendar →
  pmxt earnings query → native `/markets?event_ticker=` for prices (pmxt
  prices null for Kalshi), series_ticker trap (KXPLTR = price-targets NOT
  mentions), exact-keyword resolution trap (GRAB BUYB "repurchase" ≠
 "Buyback"), same-night candidate set (GRAB DELI / SNAP SPEC+PERP / PLTR COMM),
 + TTL-survives-to-call fix (0.8× formula dies pre-call; use 8h via raw
 place_order) and order-field gotchas (orderbook_fp key, initial_count_fp,
 price = 1−no_price_dollars).
- `predict` skill — hunt flow, research gates, arb (PMXT/Predexon).
- `scripts/vj_batch_mentions.py` — reusable multi-market batch placement:
  wall-level limits, notional cap, timed-event TTL, `--verify` resting-order
  field check. Edit ORDERS + EVENT_START_UTC per batch, run from repo.
- `MACRO_NEWS.md` (repo, NOT a skill file) — VJ-forwarded macro batches with
  reads + Kalshi implications. Memory `[MACRO-FEED]` is the pointer; the file
  is the persisted reference. Append, don't replace.
