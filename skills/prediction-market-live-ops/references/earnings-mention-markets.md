# Earnings-mention markets (Kalshi) — research pattern (2026-08-02)

Kalshi `KXEARNINGSMENTION<TICKER>-<DATE>-<KW>` markets pay on whether a
company MENTIONS a keyword on its next earnings call. Cheap-looking strikes
can be massive misprices because the resolution is a transcript phrase check,
not a fundamentals bet.

## Anatomy

- Event: `KXEARNINGSMENTIONPLTR-26AUG03` — "What will Palantir say during
  their next earnings call?" Settlement source = company IR page (e.g.
  investors.palantir.com earnings release). Verify via
  `GET /events/{event_ticker}` → `settlement_sources`.
- Markets: one per keyword, ticker suffix is an abbreviation of the keyword.
  **`yes_sub_title` field carries the readable keyword** (e.g. `COMM` →
  "Commercial Growth", `WARP` → "Warp Speed", `NVID` → "Nvidia", `SLOP` →
  "Slop / AI Slop", `MAVE` → "Maven"). Pull it — titles are truncated garbage.
- Event `close_time` is None; strike list has `expiration_value` etc.

## The research gate (what makes COMM a trade)

Market price ≠ mention probability — the misprice exists when the phrase is
near-certain but the market prices it cheap. Evidence source: PREVIOUS QUARTER
TRANSCRIPTS (fool.com earnings call transcripts are searchable).

PLTR COMM case (2026-08-02): Q1 2026 transcript says "commercial revenue
growth" / "commercial segment" / "U.S. commercial growth" MULTIPLE times —
Palantir discusses commercial growth on every call. Market priced "mention
Commercial Growth" at 0.26 → est 0.70+ → +44c misprice. Trade: YES @ 0.26
(band OK, floor OK from transcript evidence).

## Search phrase for transcript evidence

`<company> earnings call "<keyword>" Q1 2026 transcript` — check the keyword
appears, ideally multiple times, and is a routine segment (revenue guidance,
growth segments, partnership names). If the phrase is a one-off (e.g. a meme
word like "slop"), treat the market as efficient.

## Keyword → trade mapping notes

- REVE (Revenue Guidance) / INTE (International) / MAVE (Maven) / WARP
  (Warp Speed): high-prob but priced 60-96c — cheap-side entry gone, but see
  NEAR-CERTAIN CLOSEBY section below (VJ 2026-08-03) — these became a NEW
  trade class, not dead ends.
- COMM (Commercial Growth) type: routine phrase priced cheap = the play.
- Sub-50% cheap strikes (ICE, GOVE, AUTO, IRAN): floor-blocked, skip unless
  transcript evidence lifts them — research first, never assume.

## Near-certain closeby limit fills (VJ thesis 2026-08-03)

VJ: even when a market looks "priced out" (YES 60-96c), if resolution is
CLOSE (≤24h — earnings call tonight), place a LIMIT order at the
volume-weighted bid cluster level and ride to 1.00. Only valid when the
outcome is genuinely near-certain (base rate ~1.0 across prior transcripts:
REVE — PLTR raises revenue guidance every single quarter, ~0.97).

Verified example (PLTR reports Aug 3 after-hours, event
KXEARNINGSMENTIONPLTR-26AUG03):
- REVE: best bid 0.90 / ask 0.91 (1c spread), bid depth 3518.
  top3 bid cluster VWAP = 0.894 (0.90×1076, 0.89×296, 0.88×334).
  EV @ P=0.97 = 0.97×1.00 − 0.894 = +7.6c/contract (~8.5% overnight).
- Method: `kalshi.fetch_orderbook(ticker)` → bid_ladder [price,size] →
  top-3 VWAP cluster (NOT full-ladder VWAP — deep far-from-touch bids drag
  it down: REVE full-cluster VWAP was 0.434, meaningless; top3 = 0.894).
- Non-candidates: Sovereign AI 0.57 / Commercial Growth 0.47 / Nvidia 0.43 —
  genuinely uncertain mentions, not near-certain. The thesis class is
  keywords with ~100% historical mention rate, priced 60-96c.

✅ RESOLVED — VJ GRANTED the near-certain exception (2026-08-03): directive
"Buy all with limit order closest to the range. Max bid for each order not to
exceed $1.20" explicitly covered the 60-96c near-certain set. Batch placed:
PLTR REVE 0.89, SLOP 0.70, MAVE 0.88, GRAB WERI 0.56, FOOD 0.58 — all above
the 40c band, all limit at cluster VWAP, notional ≤ $1.20/order. The grant is
PER-BATCH and per-directive: it is NOT a standing band lift. A future batch
of >40c near-certain buys still needs VJ to say "buy all" / name the set
again, or the band stays hard (place nothing without his words).

## Multi-company hunt — same-night reporters (2026-08-03)

Flow for "hunt earnings-mention opportunities" (PLTR+GRAB+SNAP+MCD all reported Aug 3):
1. investor-agent MCP `earnings_calendar(date=today)` → who reports TODAY (PLTR, GRAB, SNAP...).
2. pmxt `fetchEvents(exchange=kalshi, query="earnings")` → mention events with market UUIDs, titles, volume.
3. **pmxt prices are NULL for Kalshi mention markets** — native API for prices:
   `GET /markets?event_ticker=KXEARNINGSMENTIONPLTR-26AUG03&limit=200` (reliable filter).
4. Ticker anatomy: pmxt slug `KXEARNINGSMENTIONPLTR-26AUG03-COMM` → event = `KXEARNINGSMENTIONPLTR-26AUG03`,
   market suffix = keyword abbrev (COMM, SOVE, DELI...). `yes_sub_title` holds readable keyword.
5. Research gate: previous-quarter transcript (fool.com) phrase-search per keyword → est prob.
   BUY only when est ≥50% from transcript AND price ≤40c band (per predict skill).

**API pitfalls (hit 2026-08-03)**:
- `GET /events?status=open` caps at 200/page — mention events may not appear in first page.
- `cursor={n*1000}` on `/markets` paginates WRONG (repeats page 0). Go straight to `/markets?event_ticker=<EV>`.
- **series_ticker trap**: `KXPLTR` series = PRICE-TARGET/CUSTOMER markets ("Above 1075" etc.), NOT mention
  markets. Mention event ticker ALWAYS contains `EARNINGSMENTION` infix. Fetching series KXPLTR wastes a pass.
- Event titles are truncated garbage; keyword lives in `yes_sub_title`.
- Cross-venue: pmxt router/polymarket returned EMPTY for PLTR earnings mentions — these are Kalshi-only;
  no arb leg. Edge = pure transcript-info vs Kalshi price.

**Exact-keyword trap (GRAB BUYB 2026-08-03)**: resolution = the EXACT keyword spoken on the call. Q1
transcript says "repurchase $400M of shares"; market keyword "Buyback / Buy Back" — NOT a match. Check the
literal term in the transcript, not the concept. Contrast: SNAP PERP (Perplexity) IS a match — Q1 "amicably
ended the Perplexity deal", fresh news → 0.12 underpriced. GRAB DELI (Delivery Hero) is a match — Q1 SEC
release confirms foodpanda-Taiwan acquisition FROM Delivery Hero.

**Aug 3 2026 same-night candidate set** (all resolved after 5pm ET call):
- GRAB DELI Delivery Hero 0.22/0.24 — est 0.75, +51c — band+floor OK
- SNAP SPEC Spectacles 0.28/0.29 — est 0.80, +51c — band+floor OK
- PLTR COMM Commercial Growth 0.40/0.41 — est 0.75, +34c — band edge (bid 0.40)
- SNAP PERP Perplexity 0.12/0.13 — est 0.65, +52c — band+floor OK
- Band-violation near-certain set (60-96c, GRANTED by VJ 2026-08-03): PLTR REVE/SLOP/MAVE, GRAB WERI/FOOD — all placed 0.56-0.89

## Speech-event mention markets — same class as earnings (2026-08-03)

NOT just earnings calls. Any "What will X say during Y" event resolves on a
transcript/remarks phrase check. Verified: `KXTRUMPMENTION-26AUG03` — Trump
EO signing (Oval Office, press pool). Anatomy identical: event ticker
`KXTRUMPMENTION-26AUG03`, one market per keyword suffix (`OIL`, `IRAN`,
`AFFO`, `DUMB`...), readable keyword in `yes_sub_title`. Event has a hard
START time (1:30pm ET signing) — timed-event TTL rule applies
(ttl = event_start − now).

EO/speech hunt flow (verified 2026-08-03):
1. **Identify the EVENT TOPIC FIRST** — the EO subject defines the likely
   keywords. Search `<event> <date> executive order what is it about`;
   the topic (e.g. oil production — Sable pipeline, Defense Production Act,
   +50k bbl/day) makes OIL near-certain and shapes the whole candidate set.
2. **Check the speaker's RECENT rhetoric** — Trump's own tweets that morning
   are the strongest keyword evidence (Iran 4x in one tweet, "Dumocrats",
   "Radical Left's Fake Poll numbers"). Fresh tweets > stale base rates.
3. Map: topic keywords (OIL 0.80 = near-certain, correctly priced, no edge),
   rhetoric keywords (RADI/DUMB cheap + tweet-backed = edge), phrase-mismatch
   traps (same as GRAB BUYB — exact term must appear).
4. Wall-level pricing, not quote bid: AFFO quote 0.19/0.25 but full ladder
   wall 0.13×104 (deep 0.01×533 is trash floor). VJ fills at the wall.

Live example: EO signing 13:03 CT, AFFO (Afford/Affordable) wall 0.13,
RADI (Radical Left) wall 0.17×275, DUMB (Dumbocrat) wall 0.12×748. Trump
had tweeted "GET CONSUMER OIL PRICES DOWN NOW" + Iran rant hours earlier.
Est: OIL 0.95 (topic), AFFO 0.45-0.55 (rhetoric+topic), RADI 0.35-0.40,
DUMB 0.30-0.35. Band-OK cheap entries = AFFO/RADI/DUMB; OIL/IRAN are
near-certain >40c class (per-batch grant needed).

## Order mechanics (this session's verified path)

- Default TTL 1h (VJ rule) unless overridden.
- Volume-peak/density-mode maker pricing applies (see SKILL.md volume-peak
  section). PLTR COMM book: sizable volume at 0.25 → re-placed 4 @ 0.25 =
  $1.00 (was 3 @ 0.26 with 24h TTL, cancelled per VJ).

### ⚠️ TTL MUST SURVIVE TO THE CALL — hit live 2026-08-03, all 10 re-placed

LiveExecutor defaults to 1h TTL. Earnings call 6.5h out → orders expire
BEFORE the call; near-certain class never rides to resolution. First batch
used `0.8 × hours_to_expiry` = 5.2h — still died 19:32Z vs call 21:00Z.
Cancelled ALL 10 and re-placed with 8h TTL.

Fix: for mention batches, bypass LiveExecutor (it hardcodes the 1h default)
and call `kalshi.place_order(ticker, "YES", count, limit, hours_to_expiry=0,
max_lifetime_hours=8.0)` — 8h covers call + resolution buffer. Keep
`risk.pre_flight_check` before each order; the gate is what matters, not the
executor wrapper. Mention markets have `close_time: None` and resolve at
call end — the `0.8 × hours_to_call` formula is WRONG here: you want the
order ALIVE at call time, not dead before it.

### Order/field gotchas (verified live 2026-08-03)

- Orderbook JSON key is `orderbook_fp` (arrays `yes_dollars`/`no_dollars` of
  `[price,size]` ASCENDING, last = best bid) — NOT `orderbook.yes`.
- Order-list objects: `initial_count_fp`/`remaining_count_fp` (not `count`),
  price = `1.0 - no_price_dollars` (no_price is the NO-side quote; YES bids
  show `no_price_dollars` = 1 − bid). Printing `o["price"]` shows 0.00 —
  display bug, NOT a bad order. Verify with `initial_count_fp` + ticker.
- Creds: KALSHI keys usually already exported in shell env; if not, load
  `/data/.hermes/.env` explicitly — HOME may be `/data/.hermes/home`, so
  `~/.hermes/.env` misses the file.
- Notional cap per order (VJ 2026-08-03 "max $1.20/order"): count =
  floor(1.20 / limit_price). 10-order batch = $10.41 total, all limit at
  cluster VWAP, band override for the 60-96c near-certain set.

## Wall-vs-bait order level (COMM case 2026-08-03)

When a keyword is priced mid-range (COMM ~0.40-0.47), the TOP of the book can
be bait-thin while the real money sits far lower. COMM full ladder:
best bid 0.40×200 (thin) → cliff (0.35×6, 0.30×73, 0.27×95) → WALL at
0.10×2953, 0.14×437, 0.13×333. Volume-peak center of mass ≈ 0.13.

- **Rule: bid at the wall VWAP, not best bid.** Order level = 0.13 (sits at
  the wall, matches volume mean 0.1285, high fill odds). Bidding 0.38-0.40 =
  paying the bait price with only 200 contracts of depth behind it.
- A 0.13 fill on a 40c-implied market is a lottery-adjacent shape (if phrase
  said → +87c) — the WALL's own price is the crowd's fair value read; cheap
  fill caps downside. VJ decides; never auto-place this shape.
- ⚠️ **SIDE-INVERSION TRAP (hit live 2026-08-03)**: raw `kalshi.place_order`
  with lowercase `side="yes"` failed the `side == "YES"` check → built an
  ASK/SELL → 3x YES @ 0.13 approved became SELL 3 @ 0.40 (position_fp −3).
  Code fixed (side_map normalization, commit `791bb46`), but ALWAYS route
  through `LiveExecutor` (normalizes side + pre-flight guards). Verify fill
  direction against `position_fp` sign before reporting success. Undo = buy
  back same count at ask; cost ~fees + 1-2c.
