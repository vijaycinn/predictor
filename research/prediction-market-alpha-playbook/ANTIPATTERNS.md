# ANTIPATTERNS — Silent Failures That Will Burn You

Each entry is a real, observed failure mode. Most corrupt data silently for days or weeks before detection. Read this **before** writing code — knowing the trap is 90% of avoiding it.

---

## Side/Token Alignment

**Failure**: Buying YES token when betting NO side. Order fills, shows "success" in logs, and silently loses at resolution.

**Root cause**: Outcome index vs outcome string mismatch. Code uses `outcome.toLowerCase() === "yes"` but the market is "Up/Down" or "Team A/Team B" or party names — no "yes" string exists. Defaults to NO side but buys YES token.

**Fix**: Always use `outcomeIndex` (0 or 1) rather than string matching. Index 0 = first outcome listed (often AWAY team for sports, FIRST candidate for elections, etc.).

```typescript
// BAD
const side = outcome.toLowerCase() === "yes" ? "YES" : "NO"

// GOOD
const side = outcomeIndex === 0 ? "YES" : "NO"  // with documented mapping
```

**Sports slug gotcha**: Polymarket sports slugs are `{sport}-{away}-{home}-{date}`. `outcomes[0]` is the AWAY team. If your strategy says "home team wins at 60%", you need `prices[1]` and `tokens[1]`.

---

## 1 − yes_ask ≠ NO Ask

**Failure**: Computing NO ask as `1 - yes_ask` fabricates false arbs. Real cost is higher by the full spread width.

**Correct formulas**:
- NO ask (price to BUY NO immediately) = `1 - yes_BID`
- NO bid (price a NO seller receives) = `1 - yes_ask`

**Why**: If yes_bid=0.11 and yes_ask=0.18 (spread=7pp), a market-maker holding NO sells it at `1 - 0.11 = $0.89` (crossing YES-side's bid). They do NOT offer NO at `1 - 0.18 = $0.82` — that's what a NO buyer would want (crossing nothing).

**Observed damage**: fake 3pp monotonicity-violation arb surfaced; real cost was 7pp higher, signal flipped to −EV. Almost fired a losing trade.

---

## Journal PnL Fiction

**Failure**: In-process journal records report +$22K of wins that never happened. Downstream dashboards, alerts, and graduation gates are all lying.

**Mechanism**: Multiple compounding bugs:
1. Exit-stamping bug stamps binary oracle read (`pnl = won ? size_usd : -size_usd`) on rows where `actual_fill_price IS NULL` — partial fills get full-payout PnL
2. Low-entry strategies (crypto_updown at 1-5¢ tokens) resolve "won" via positions-API `curPrice >= 0.5` brief pre-settle window before oracle finalizes → fake WR
3. Synthetic PnL computers use formulas like `pnl = fillRate × spread × rebate` instead of actual cash events
4. Paper resolver inflates low-entry strategies (crypto_updown, resolution_snipe, market_maker) with formula-shaped PnL

**Fix**: 
- Every live position must have `actual_fill_price` populated before PnL is computed
- `exit_stamping_suspect=1` column on `live_trades` for rows with NULL fill price
- Phase-3 REDEEM-reconciliation path populates real PnL from on-chain activity
- Dashboard, graduation-lifecycle, analyze-live-pnl all filter `WHERE exit_stamping_suspect=0`
- Paper rows use `inflation_flagged` column with same methodology

**Meta-rule**: **Never trust journal PnL.** Always reconcile via exchange Data API before reporting.

---

## Aggregate WR Hides Sub-Cohort Alpha

**Failure**: Killing a strategy at 11% WR / -$664 realized when exhaustive cohort search would have found a `price≥80¢ NORM` sub-cohort at 100% WR (8W/0L) AND `price<80¢ FADE × dow=Wednesday` sub-cohort at +$245.

**Rule**: Before killing any strategy on aggregate WR or $, run exhaustive cohort search against VPS-live DB. If ANY cohort at N≥5 has `mean > 0` AND `Wilson lb95 ≥ 40%`, retarget rather than amputate.

**Tested pattern**: 4 of 4 "killed" strategies had hidden alpha when analyzed cohort-by-cohort. Killing on aggregate is a systematically wrong default.

**Recurring sub-cohort shapes**:
- **`price≥80¢ NORM`** — clear-win cohort (near-certain outcome at small discount)
- **`price<80¢ FADE`** — adverse-selection correction (invert original signal's direction)

Check these two before declaring failure.

---

## PM Oracle Systematically Diverges from Scanner Reference

**Failure**: Crypto up/down scanner sees "Binance is trending up" and buys YES for "will price be higher in 5 minutes". Polymarket oracle resolves based on different feed (TWAP, Coinbase, UMA-weighted) that diverges ~93% of the time.

**Pattern**: Any strategy whose scanner reference (Binance tick, weather forecast, consensus model) differs from the resolution oracle is vulnerable. 7% WR NORM, 93% WR FADE on N=28.

**Rule**: Every scanner should declare:
- What reference data does my signal use?
- What oracle does the market use for resolution?
- Are they the same feed?

If different, FADE (or at least test FADE variant) before trusting NORM.

---

## CoinGecko 429 Silent-Kill

**Failure**: Scanner imports `getReferencePrice(symbol)`. Under the hood, `needsCoinGecko(symbol)` returns `true` for every mapped symbol, so ALL traffic routes to CoinGecko. CoinGecko demo tier rate-limits aggressively. Scanner silently produces zero opportunities because every price lookup 429s.

**Fix**: Invert the gate. Use Binance klines as primary (free, unlimited); fall through to CoinGecko ONLY for unsupported symbols (e.g., HYPE which isn't on Binance).

```typescript
// BAD
function needsCoinGecko(symbol) { return true for all supported }  // routes everything

// GOOD
const BINANCE_UNSUPPORTED = new Set(["hypeusdt"])
function getReferencePrice(symbol) {
  if (!BINANCE_UNSUPPORTED.has(symbol)) return binanceKlines(symbol)
  return coinGecko(symbol)  // fallback only
}
```

**Diagnosis tool**: Write a `probe-<scanner>.ts` one-shot that runs the scanner's core logic and prints opportunities. If production returns 0 fires but probe returns 4 in 15s, the data pipeline is broken, not the signal.

---

## Proxy Wallet vs EOA Confusion

**Failure**: Set `POLYMARKET_ADDRESS=<your EOA>`. Bot fails with cryptic "invalid signature" or "not authorized" errors. Hours of debugging.

**Rule**: For venues with proxy-wallet architecture, the **proxy** is what holds funds. Your EOA signs on behalf of the proxy. `POLYMARKET_ADDRESS` must be the proxy (looks like `0x...`), NOT the EOA.

**Diagnosis**: If your address doesn't appear to hold funds when you query Data API `/positions`, you're using the wrong address.

---

## Microshare Balance Mismatch

**Failure**: Data API reports position size as `52.9661` shares. Your sell script rounds up to `52.97`. CLOB rejects with "not enough balance / allowance: balance 52966100, order amount 52970000".

**Fix**: Floor sizes to 4 decimals before submitting:

```typescript
const flooredSize = Math.floor(reportedSize * 10000) / 10000
```

**Why**: CLOB uses integer microshares internally. `52.97` is `52,970,000` microshares, but actual balance is only `52,966,100` microshares (=`52.9661`). The rounding gap is exactly the gotcha.

---

## JS Float Precision on Threshold Checks

**Failure**: `1 - 0.07 = 0.9299999999...`, fails `>= 0.93` silently. Trade doesn't fire, strategy appears idle, hours of confusion before checking actual arithmetic.

**Fix**: Round to 3 decimals before any probability threshold comparison.

```typescript
const probAboveThreshold = Math.round((1 - yesBid) * 1000) / 1000
if (probAboveThreshold >= 0.93) fire()
```

---

## Thin-Book Exit Trap

**Failure**: You hold 100 shares. Mid price is $0.18. You think you'll recover ~$18 on exit. Actual fill walks the bid ladder down to $0.073 average — you recover $7.30, losing $11 to exit slippage you didn't budget.

**Rule**: Exit cost must be computed by **walking the bid ladder**, never displayed mid. For any position you might exit early, compute worst-case `avg_fill_price = sum(bid_i × size_i) / total_size` across visible bids.

**Spread signal**: 17pp+ spread = abandoned market fingerprint. Don't enter positions you might want to exit on markets with wide spreads.

---

## Thin-Book Positions Are Capital-Locked

**Failure**: Fire $150 into small partial-basket position on thin-book market. Market moves, you want to exit. Best recoverable is 40-70% of mid. Capital is effectively locked until resolution.

**Rule**: Small positions (<$200) on thin markets should be sized **like holds-to-resolution**, not as revolving capital.

**Pre-fire checklist**: "Am I willing to hold this to resolution if the exit book is 50% of entry?" If no, don't fire.

---

## CRLF Env Gotcha

**Failure**: `.env` file edited on Windows, committed to Git, pulled on Linux VPS. Bash reads `POLYMARKET_ADDRESS=0x...\r` with trailing carriage return. axios URL-encodes it as `%0D`. Polymarket Data API returns HTTP 400 "required query param 'user' not provided".

**Fix**: Defensively `.trim()` every env read in config.

```typescript
function env(key: string, fallback?: string): string {
  const raw = process.env[key] ?? fallback
  if (raw === undefined) throw new Error(`Missing env var: ${key}`)
  return raw.trim()  // strip CR/LF/whitespace
}
```

---

## CI Silent Deploy Drift

**Failure**: CI correctly blocks broken-lint deploys. 7 consecutive commits fail silently. Production stays on old code for hours while you think you're testing new features.

**Rule**: 
- Run `npx tsc --noEmit && npx eslint . --quiet` (project-wide, not file-scoped) **BEFORE** pushing
- After pushing, verify CI turned green via `gh run list --limit 1`
- Configure Telegram alerts on main-branch CI failure so repeated failures aren't invisible

**Why this matters**: Scoped lint (`npx eslint <specific-file>`) misses unused-import errors in other files that CI's project-wide lint catches. If you scope-lint, you can silently push broken code.

---

## Scp'd-Then-Committed File Collision

**Failure**: Manually scp an operational script to VPS for urgent execution. Later commit the same file to git. VPS auto-pulls on CI deploy → git merge aborts with "untracked working tree files would be overwritten by merge".

**Fix**: In the VPS deploy script, run `git clean -fd src/scripts/ tmp/` (scoped to known-safe dirs) before `git pull origin main`. Use `|| true` to keep graceful on first deploy.

**Alternative discipline**: Don't scp files you're going to commit. Commit → push → CI → pull is the one-way flow.

---

## Shared DB ID Collision

**Failure**: Two processes write to the same SQLite DB. Each maintains its own `tradeCounter`. Both generate `live-142`. `INSERT OR IGNORE` silently drops one. Later `UPDATE live_trades SET pnl=X WHERE id='live-142'` overwrites the survivor's row.

**Fix**: Per-process ID prefix env var (e.g., `PROCESS_ID_PREFIX=pb` for main bot, `xarb` for autofire sidecar, `ih` for insider-hunter sidecar). All generated IDs include the prefix.

---

## Combo-Arb / Multi-Leg Toxicity

**Failure**: Strategy that fires multi-leg combo bets (e.g., "winner AND margin" pairs) can have 0% WR over thousands of trades because the combo payoff structure hides structural mispricing.

**Lesson**: Permanently-killed strategies exist because the thesis is fundamentally broken, not because of execution bugs. Some examples (from various prediction-market bots):
- **Combo arbs on correlated binaries** (bets that require multiple true statements simultaneously) — consistently -EV
- **UMA dispute arbitrage on commodity markets** — category-biased, convergence thesis violated
- **Market-maker synthetic PnL** — if your PnL formula is `fillRate × spread × rebate`, you're computing a spreadsheet dream, not real fills

**Rule**: Any strategy whose PnL formula doesn't include `actual_fill_price` is suspect. Always look at where PnL comes from.

---

## Public Polygon RPC Unreliability

**Failure**: Bot uses `polygon-rpc.com` or `ankr` free-tier RPC. Under production load, returns `noNetwork` errors, times out on `getLogs`, ethers v5 `contract.on()` silently drops events. Redemption fails, resolution monitoring misses events.

**Fix**: Pay for Alchemy / Infura / QuickNode. Mandatory for production Polygon interaction.

---

## Search-Before-Build

**Failure**: Spend 2 days building custom data aggregator. Discover `@dome-api/sdk` exists on npm and does 80% of what you built. Throw your code away.

**Rule**: Before ANY "build from scratch" proposal, 30-second search:
- `npm view <package>` for candidates
- WebSearch for "<problem domain> API"
- Check existing MCP servers
- Check public GitHub for prior art

---

## Canonical Slug From Free-Text

**Failure**: Use `gamma-api.polymarket.com/markets?_q=splits` to find markets. Endpoint returns "GTA VI" catch-all regardless of query. Strategy silently operates on wrong markets for 20 hours.

**Fix**: Always construct canonical slugs from known-stable inputs. Never use free-text search.

---

## Fat-Tail Strategies Killed on Small N

**Failure**: Kill a fat-tail strategy (e.g., cheap tail bets with 100× payoffs) after 5 losing trades. Each loss is $1-$5; each win would be $100+. Small-N WR is meaningless for fat-tail distributions.

**Rule**: Never kill fat-tail signals on N<30. Audit `mean ROI` and `distribution shape` before killing, not WR.

**Example**: A strategy with 10% WR and mean +$1.16/trade has positive expected value. Killing at 0/5 (before any wins) discards the edge.

---

## Thin Slug Construction

**Failure**: Build slug as `"{teamA}-{teamB}-{date}"` but Polymarket convention is `"{sport}-{away}-{home}-{date}"`. Your matcher finds no markets and silently idles.

**Fix**: Read real Polymarket slugs for 20 markets before hardcoding format. Validate against at least 2 different sports / categories.

---

## Graduation-Pipeline Gotchas

**Failure**: Complex interacting bugs in the lifecycle state machine:
1. `TRACKED_STRATEGIES` drift (config set out of sync with code)
2. Reconciler pnl-only override (uses journal PnL instead of Data API)
3. Count-based demote window (counts all trades instead of most recent N)
4. Paper-only scanners ignoring LIVE flag (scanner fires live even when `STRATEGY_LIVE_ENABLED=false`)

**Rule**: Every live gate must check at point of fire, not at scanner registration. Dead-code the live path if flag is false.

---

## Insider Cluster vs News Herd

**Failure**: Copy flow from "25 wallets converging on market X". Turns out it's the news herd — retail reacting to a breaking story, taking losing positions. Copying the herd loses consistently.

**Taxonomy**:
- **Sports clusters**: 5-13 wallets, 3-8× ROI, mechanical information (injury/fight/match-fix). These are informed traders. Copy.
- **News herds**: 25-40 wallets on LOST narrative bets. Retail sentiment chasers. Do NOT copy.

**Filter**: `HERD_THRESHOLD = 25` at (market, side). Above threshold = herd, ignore. Below threshold with elite-wallet composition = cluster, trade.

---

## Convergence-Arb vs Insider Fingerprint

**Failure**: Fresh-wallet + single-event scorer fires equally on directional insiders AND basket arbers. Basket arbers open many markets simultaneously for sum-arb lock-in — they're not making directional bets.

**Fix**: Sibling-market lookup. For each candidate wallet, check if they have positions on sibling markets (same event end_ts ±48h, different market_id). Multiple sibling positions = arb basket, not insider.

---

## Clear-Win Category Bias

**Failure**: "100% WR" on uma_arb strategy. Turns out all 20 wins were non-commodity markets. Commodity markets have oracle-feed divergence that breaks the convergence thesis. Once included, WR drops to 40%.

**Rule**: Any "100% WR" claim on small N is suspected category-biased. Stratify by market category before trusting.

---

## VPS Is Running Yesterday's Code

**Failure**: You commit and push a fix. Hours later, the fix isn't affecting production. Diagnose for hours. Discover VPS auto-deploy wasn't running (CI failed on lint), VPS is running 7 commits old.

**Verification protocol**:
1. After every push, `gh run list --limit 1` — is CI green?
2. `ssh vps "git -C /root/... log --oneline -1"` — does VPS HEAD match origin?
3. `pm2 status` — is uptime > your-deploy-time? (Low uptime = recent restart = deploy picked up.)

**The VPS is not a git repo** was once a memory-worthy rule. After proper CI/CD, `VPS auto-deploys when CI is green` is the new rule. Both are true at different times; knowing which regime you're in matters.

---

## Paper-Resolver Inflation On Low-Entry Strategies

**Failure**: Paper-trade system marks every `entry ≤ 5¢` trade as "won" via some formula path. Low-entry strategies (crypto_updown, resolution_snipe) show fake $500K paper PnL.

**Fix**: 
- Audit paper-resolver code for any formula-based PnL computation
- Add `inflation_flagged` column to `paper_trades` with retroactive backfill
- All downstream PnL queries filter `WHERE inflation_flagged=0`

**Meta-rule**: if your paper PnL exceeds your live PnL by more than 10×, something is wrong with the paper resolver. Audit before trusting.

---

## Summary Rules

- **Ground truth lives at the exchange.** Data API > journal.
- **Side = outcome index, not string.** Never parse "yes"/"no" strings.
- **1 − yes_ask is NOT the NO ask.** Know the fee/spread conventions.
- **Wilson lb95 > point WR.** Small N needs lower-bound thinking.
- **Fat-tail distributions need mean/shape analysis, not WR.** Don't kill on 5L.
- **Verify deployment after every push.** CI green-gate can hide silent drift.
- **Search before you build.** Check npm, MCPs, existing SaaS first.
- **Floor to 4 decimals for any share-size submission.** Microshares lie.
- **Trim every env var.** CRLF is invisible.
- **Run project-wide lint, not file-scoped.** CI catches what scoped doesn't.
