# Kalshi Research Findings — condensed knowledge bank (2026-08-06)

Distilled from three external repos (AKCodez prediction-market-alpha-playbook,
RohitDayanand/PolyKalshi_Client, OctagonAI/kalshi-trading-bot-cli) plus live
verification. Full narrative + integration decisions: repo
`RESEARCH_FINDINGS.md`. Raw clones: `/data/workspace/research/` (local only —
NOT vendored to GH, VJ 2026-08-06).

## Fee economics (applies to EVERY order)

- General fee: `0.07 × p × (1-p)` per contract, rounded UP to next cent.
- Maker-fee tickers (fee = 0.0175): KXAAAGASM, KXGDP, KXPAYROLLS, KXU3,
  KXEGGS, KXCPI, KXCPIYOY, KXFEDDECISION, KXFED, KXNBA*, KXNHL*, KXINDY500,
  KXPGA, KXUSOPEN, KXPGARYDER, KXTHEOPEN, KXPGASOLHEIM, KX*SINGLES (tennis
  GS), KXNFLGAME, KXUEFACL, KXNATHANSHD, KXCLUBWC, KXTOURDEFRANCE,
  KXNASCARRACE, KXATPMATCH, KXWTAMATCH, KXMLBASGAME, KXMLBHRDERBY.
- p=0.50 → 1.75%/contract; p=0.05 or 0.95 → 0.33%/contract (quadratic decay).
- **Cross-venue arb needs ≥400bps raw edge** to survive round-trip fees.
  Sub-200bps raw edges ALWAYS net-negative. Extreme-p pairs are the only
  cheap seeds.

## NO-side price formulas (kills fake arbs)

- NO ask (cost to BUY NO) = `1 - yes_BID` — NEVER `1 - yes_ask`.
- NO bid (what a NO seller receives) = `1 - yes_ask`.
- Using `1 - yes_ask` understates cost by the full spread and fabricates
  false arbs (playbook: "almost fired a losing trade").
- Matches our Kalshi V2 rule: buy NO at L → send `price = 1 - L`.

## Structural arbs

| Edge | Tier | Fit |
|---|---|---|
| Within-market YES+NO<1.0 (buy both, redeem $1) | S | rare, closes in seconds |
| Ladder monotonicity: P(>lower) ≥ P(>upper); if `ask_yes(lower) < ask_yes(upper)` → buy lower YES + upper NO | A | applies to GOLDMON/WTI/BTCMON ladders, thin but real |
| Sum-arb lock-in: buy NO on all N mutually-exclusive at Σ>1.025 | A | Polymarket NEG_RISK only — Kalshi has no negRisk flag |
| Clear-win convergence: decided outcome priced 90-95c | B | sports/weather clean; FAILED on commodity/macro (oracle divergence) |
| Tail-fade: low-prob tail priced 5-10c over base rate | B | hold to resolution; small size |

Gotcha: partial-basket invalid — one leg `ask=null` kills the sum-arb. Verify
every leg fillable before firing.

## Kelly sizing + 5-gate risk (Octagon reference — NOT our sizing rule)

- YES: `f* = edge / (1 - pricingProb)` where pricingProb = yes_ask
- NO: `f* = |edge| / pricingProb` where pricingProb = 1 - no_ask
- Half-Kelly default (multiplier 0.5), maxPositionPct 0.10, minEdge 0.05.
- Liquidity haircut: spread >5c OR vol24h <500 → cut fraction.
- 5 gates: Kelly (>0 contracts, ≤10% bankroll), Liquidity (spread<5c,
  vol≥500), Correlation (≤3/category), Concentration (<10 open),
  Drawdown (<20%).
- Circuit breaker: daily loss $50, max DD 20%, no same-day re-enable.
- VJ's flat $1.20/order wins over Kelly — use Kelly math only for proposal
  sizing recommendations.

## Wilson lower bound (weekly review)

- N=5 100% WR → lb95 48% (random). N=30 80% → 62%. N=100 70% → 60%.
- Quote Wilson lb95, never point WR, on small N.
- Exhaustive cohort search BEFORE killing a strategy: aggregate WR hides
  sub-cohort alpha (price bucket ≥80c NORM, FADE variants, day-of-week,
  category). 4/4 "killed" strategies had hidden alpha.
- Paper→live WR degradation budget: 20-40%.

## Antipatterns worth remembering

- Side/token alignment: use outcomeIndex, never string match.
- Thin-book exit trap: exit cost = walk bid ladder, not mid. 17pp+ spread =
  abandoned market.
- Thin-book positions are capital-locked: size like hold-to-resolution.
- Float precision: round thresholds to 3dp (`0.44-0.02=0.41999`).
- Oracle divergence: any scanner whose reference differs from the resolution
  oracle → test FADE variant before trusting NORM.
- Data API > journal for PnL. Never trust in-process journaling.

## Kalshi WebSocket (future fast-tier)

- URL: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- Subscribe: `{"id":1,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_tickers":[ticker]}}`
- Messages: `error`, `ok`, `orderbook_snapshot`, `orderbook_delta` (seq for
  gap detection). Channels: `orderbook_delta`, `ticker`, `trade`, `fill`.
- Not needed at our 30m cron cadence; upgrade path for fast flips.

## Security (2026-08-06, else24/kalshi-market-bot)

Repo was MALWARE: C2 `api.failproxy.space` (byte-obfuscated), TLS verify
disabled, reflective PE loader (VirtualAlloc/CreateThread), 14MB base.pkg
dropper. Vetting protocol: map full tree → read network/ctypes files → check
obfuscated endpoints, CERT_NONE, VirtualAlloc, embedded binaries → never run
unvetted clones. External repos = IDEAS only; our predictor stack executes.
