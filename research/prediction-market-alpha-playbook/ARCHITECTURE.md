# ARCHITECTURE — System Design Patterns

These are the patterns that survived contact with production. Each has a concrete rationale and, where relevant, a named antipattern it resolves.

---

## 1. Event-Loop with Cron + Fast Scanner Tiers

Run two concurrent scanner tiers:

- **Fast tier** (10-second interval): price-sensitive strategies (crypto up/down, resolution sniping, orderflow)
- **Cron tier** (30-second interval): heavier strategies (arb scans, whale polling, graduation evaluation)

```
EventLoop {
  fastScanTimer: setInterval(runFastScan, 10_000)
  cronScanTimer: setInterval(runCronScan, 30_000)
  
  runFastScan(): read binance WS prices, check crypto_updown opps
  runCronScan(): 
    1. scan weather/directional edges
    2. scan arb surfaces (bracket, within-market, cross-exchange)
    3. check existing positions (resolve, exit)
    4. whale feed, orderflow
    5. log scan cycle summary
}
```

**Why**: Price-sensitive edges lose value in 30 seconds. Heavy-compute scans don't need that cadence. Separating lets each run at the right rhythm without CPU contention.

**Watchdog**: log `"cron scan still running — skipping tick"` if a cron cycle overlaps the next tick. Chronic overlap means scanner is too slow; profile it.

---

## 2. Paper/Live Parallel Execution via `executeOrPaper` Bridge

All strategies fire through a single bridge function:

```typescript
function executeOrPaper(opts: {
  strategy: string
  marketId: string
  slug: string
  question: string
  side: "YES" | "NO"
  tokenId: string
  entryPrice: number
  paperSize: number        // always logged as paper_trades
  liveSize: number | undefined  // if defined AND STRATEGY_LIVE_ENABLED[strategy], also fires live
  arbClass: string         // for cohort isolation later
  clvRef?: { referenceProb: number }
}): Promise<{ paper: boolean, live: boolean, orderId?: string }>
```

**Rules**:
- `liveSize: undefined` → paper-only regardless of STRATEGY_LIVE_ENABLED
- `liveSize: N` + `STRATEGY_LIVE_ENABLED[strategy] === true` → paper + live
- `liveSize: N` + `STRATEGY_LIVE_ENABLED[strategy] === false` → paper-only

**Why**: Paper and live should always be the same decision through the same codepath. If paper fires but live doesn't under the same conditions, you've introduced a divergence that will mask bugs. The bridge enforces unified decisioning.

**Arb class tagging**: `arbClass` is a free-form sub-cohort label (`"directional_v2_norm80"`, `"crypto_updown_fade"`). Enables `replay-live-cohort --arb-class X` for post-hoc cohort measurement.

---

## 3. Graduation State Machine

Strategies evolve through discrete states:

```
paper → shadow_live → live_1x → live_2x → live_5x
                ↓
               kill ← any state (on manual intervention or breach)
```

**Transition gates** (apply to EACH state transition):

- `paper → shadow_live`: N≥20 resolved paper trades with `inflation_flagged=0`, Wilson lb WR ≥52%, avg PnL/trade ≥ $0
- `shadow_live → live_1x`: additional per-strategy graduation criteria (volume, category, etc.)
- `live_1x → live_2x`: N≥30 resolved LIVE trades since live_1x transition, Wilson lb live WR ≥ 55%, realized live PnL > $0
- `live_2x → live_5x`: N≥60 resolved LIVE trades since live_2x, Wilson lb live WR ≥ 57%, profit factor ≥ 1.5

**Demotion** (any live → one step down): 3 consecutive sub-threshold evaluation windows OR realized PnL < -3% of deployed capital.

**Kill**: two consecutive demotions from live_1x back to paper → flag `kill` state for operator review.

**Formally-killed list**: separate set of strategies that cannot auto-regraduate. Removal requires documented verdict + exhaustive-cohort re-search proving out-of-sample evidence.

**Storage**: `config/strategy-lifecycle.json` + transition history in the same file. Everything greppable + diffable.

---

## 4. Safety Guards (Bankroll Protection Layer)

Before any live fire, check all of:

```typescript
function canTradeLive(strategy, proposedSize): {ok: boolean, reason?: string} {
  if (isStrategyDisabled(strategy)) return {ok: false, reason: "strategy-disabled"}
  if (totalExposureUsd + proposedSize > MAX_TOTAL_EXPOSURE_USD) return {ok: false, reason: "exposure-cap"}
  if (proposedSize > MAX_SINGLE_POSITION_USD) return {ok: false, reason: "single-position-cap"}
  if (dailyStrategyPnl[strategy] < -DAILY_LOSS_CAP_PER_STRATEGY) return {ok: false, reason: "daily-loss-cap"}
  if (recentConsecutiveLosses[strategy] >= 3) return {ok: false, reason: "auto-disable-3-losses"}
  return {ok: true}
}
```

**Per-asset daily loss cap**: For multi-asset strategies (BTC + ETH + SOL crypto_updown), track per-asset PnL. If SOL hits -$50/day, disable SOL specifically without killing the whole strategy.

**Re-enable**: 24h cooldown OR manual override. Never auto-re-enable on same day as trip.

**Why**: Production bots find new ways to lose money. Guardrails don't prevent bugs, but they bound blast radius. A scanner gone wild firing wrong-side trades at $25/pop is catastrophic without caps; merely annoying with them.

---

## 5. Data-API-First PnL (Journal-Second)

**Rule**: Any PnL reported to users, dashboards, Telegram alerts, or graduation gates MUST come from the exchange's official Data API — NOT from in-process journaling.

**Why**: In-process journaling is subject to multiple silent failure modes:
- Stamping exit_price on partial-fill rows where `actual_fill_price IS NULL` fabricates fake wins
- Shared-DB ID collisions between processes overwrite each other's rows
- Synthetic PnL computers (formula-based: `pnl = fillRate × spread × rebate`) bypass reality entirely
- Resolution-time oracle-read race conditions flip win/loss before settlement finalizes

**Implementation**: 
- Periodic (daily or per-resolution) reconciliation job fetches `data-api.polymarket.com/activity?user=W` and overwrites journal rows with authoritative PnL
- Dashboard + Telegram query the reconciled view, not raw journal
- Graduation-lifecycle queries reconciled + `exit_stamping_suspect=0` filter for honesty

---

## 6. Exit-Stamping Honesty

When a live position resolves, compute PnL only if you have:
- `actual_fill_price` populated (from real CLOB fill receipt)
- `on_chain_resolution` confirmed (position `redeemable=true` AND final `curPrice` available)

If `actual_fill_price IS NULL`:
- Mark row with `exit_stamping_suspect=1`
- Leave `resolved=0`
- Wait for REDEEM-path reconciliation via Data API

**Do NOT** compute synthetic PnL against planned `size_usd` using a binary oracle read. On partial fills, this produces massively inflated fake wins.

**Observed damage**: A single stamping bug fabricated +$22K of fake wins across 25 rows before detection. 62% of live_trades rows got flagged on retro-audit.

---

## 7. Arb Class Tagging for Cohort Measurement

Every fire gets an `arb_class` tag:
- `"directional_v2_norm80"` — specific sub-gate
- `"directional_v2_fade_sub80"` — different sub-gate, same strategy
- `"crypto_updown_fade"` — FADE variant
- `"tail_fade"` — generic tail strategy

**Benefit**: `replay-live-cohort --arb-class X` aggregates the exact sub-cohort. Enables measurement of specific sub-gates independently, even when they share a parent `strategy` field.

**Anti-pattern**: global backfills that tag every row in a table with a single arb_class pollute the cohort. If backfill logic is unclear, leave arb_class NULL and let fresh fires populate correctly.

---

## 8. Per-Strategy Confidence → Kelly-Bounded Sizing

```typescript
function computeSize(strategy, bankroll, edge, confidence) {
  const kellyFraction = edge * confidence
  const bankrollCap = bankroll * MAX_BANKROLL_FRACTION  // e.g. 15%
  const strategyCap = SIZING[strategy].MAX_SIZE_USD
  return Math.min(
    bankroll * kellyFraction * KELLY_SCALE[confidence_bucket],
    bankrollCap,
    strategyCap
  )
}
```

**Kelly scale by confidence**:
- Low confidence: 0.25 × full Kelly (fractional)
- High confidence (multi-signal agreement): 0.5 × full Kelly
- Never exceed 0.5 × full Kelly — overbetting kurtotic distributions kills you on the third standard deviation

**Why**: Full Kelly is theoretically optimal but variance-punishing. Fractional Kelly (0.25-0.5) captures 75-90% of the expected growth rate with far less drawdown.

---

## 9. Hot Config via File-Watched Overrides

Let operators (or AI monitors) push runtime config changes without restarts:

```
config/overrides.json (file-watched, 30s poll):
{
  "hotWhales": ["0x...", "0x..."],
  "marketOverrides": {
    "<condition-id>": { "edgeBoost": 0.05, "expiresAt": "..." }
  },
  "strategyToggles": {
    "whale_follow": { "live": false, "paper": true }
  }
}
```

- Bot watches file mtime, reloads on change
- Expired overrides auto-prune
- Live-enabling via overrides is a powerful safety/unsafety lever — audit who writes the file

**Why**: Hot reload prevents "I need to restart the bot to change one flag" becoming "I won't experiment because restarts are annoying". Cheap to implement, huge ergonomic win.

---

## 10. Prometheus + Grafana Observability

Expose a `/metrics` endpoint:

```
bot_positions_open 47
bot_scan_cycles_total{tier="cron"} 1443
bot_scan_cycles_total{tier="fast"} 4330
bot_fires_total{strategy="crypto_updown_fade",result="paper"} 12
bot_fires_total{strategy="directional_v2_norm80",result="live"} 3
bot_usdc_balance_dollars 192.51
bot_daily_pnl_dollars{strategy="uma_arb"} 0.07
```

**Why**: Push dashboards, alerting, anomaly detection. The moment you're operating 3+ strategies across 2+ venues, per-strategy visibility becomes mandatory.

**Pattern**: metrics-poller runs at 60s cadence, pulls key numbers from the trading DB + Data API, publishes to /metrics. Grafana scrapes and renders.

---

## 11. CI/CD with Green-Gate Deploy

```
ci-deploy.yml:
  jobs:
    tsc-check:       # compiles TypeScript
    eslint-check:    # lint gate, project-wide
    smoke-tests:     # unit tests
    phase5-tests:    # integration + property tests
    deploy:
      needs: [tsc-check, eslint-check, smoke-tests, phase5-tests]
      steps: ssh vps "git pull && pm2 restart <services> --update-env"
    alert-on-ci-failure:
      needs: [tsc-check, eslint-check, smoke-tests, phase5-tests]
      if: failure() && github.ref == 'refs/heads/main'
      steps: send Telegram "🚨 CI failed — deploy skipped"
```

**Critical**: 
- Green gate prevents broken code from reaching production (correct)
- BUT: repeated silent failures can accumulate without operator notice
- **Add alerting on main-branch CI failure** so you know when deploys are being refused

**Observed failure mode**: ESLint unused-import errors blocked 7 consecutive deploys over 3 hours before discovery via fire-count audit. Alerting would have caught it in minutes.

**VPS self-heal**: In the deploy step, run `git clean -fd src/scripts/ tmp/` before `git pull` to handle the scp'd-then-committed file collision case (where an operational script was manually scp'd to VPS, then later committed to git → pull fails on "untracked working tree files would be overwritten").

---

## 12. Multi-Agent Development via Git Worktrees

If you have multiple AI agents or developers working in parallel:

```
mybot/                # main worktree
mybot-audit/          # audit worktree: branch feat/audit
mybot-alpha-seek/     # alpha-seeking worktree: branch feat/alpha-seek
```

Each worktree is a full working copy on a separate branch. Agents can independently commit, push, and open PRs without stepping on each other.

**Coordination protocol (for multi-agent setups)**: lightweight 6-verb contract between agents:
- **CLAIM** <task> — I'm taking this
- **DECLINE** <task> — passing
- **DONE** <task> — finished, PR/commit here
- **BLOCKED** <task> <reason> — stuck, need input
- **STATUS** <context> — here's what I see
- **QUERY** <question> — need answer

Keep messages short (6-line cap is a good discipline). 🆕 prefix for new-file introductions.

---

## 13. Persistent Memory for Cross-Session Learning

For AI-agent operators, maintain a memory system that persists across sessions:

```
memory/
  MEMORY.md                           # index of all memory files (always loaded)
  user_profile.md                     # operator preferences
  feedback_<topic>.md                 # lessons learned per topic
  project_<topic>.md                  # ongoing work state
```

**Rules**:
- Save on both SUCCESS and FAILURE (not just corrections)
- Lead each `feedback_*` file with the rule, then **Why:** and **How to apply:** lines
- Update MEMORY.md index when adding entries (one-line hooks, ~150 chars each)
- Verify stale memory against current state before acting on it

**Value**: Session N+1 doesn't re-discover what session N learned. Weeks of debugging distilled to a 3-line lesson that an agent reads on startup.

---

## 14. Side/Token Alignment (Structural Correctness)

When firing a trade:

```typescript
interface Opportunity {
  conditionId: string
  yesTokenId: string     // token that pays $1 if outcome[0] (YES-ish)
  noTokenId: string      // token that pays $1 if outcome[1] (NO-ish)
  side: "YES" | "NO"     // which side to buy
  yesPrice: number       // current YES price on the book
}

// When buying:
const tokenId = side === "YES" ? op.yesTokenId : op.noTokenId
const entryPrice = side === "YES" ? op.yesPrice : 1 - op.yesPrice
```

**Universal rule**: the token you buy must match the side you claim to be betting on. YES buys yesTokenId. NO buys noTokenId. Mismatches silently fire wrong-side bets that look "filled" in the journal but lose on resolution.

**Sports slug trap**: `{sport}-{away}-{home}-{date}` means `outcomes[0]=AWAY`. If your strategy calls "home team YES at 60%", you need `prices[1]` and `tokens[1]` — you're buying the HOME token even though the market is indexed to AWAY.

---

## 15. Multi-Process DB Isolation

If multiple processes write to the same SQLite DB:

```
main-bot process → writes trades.db with trade IDs like "pb-live-142"
xarb-autofire process  → writes trades.db with trade IDs like "xarb-live-87"
insider-hunter process → writes trades.db with trade IDs like "ih-live-15"
```

Without process prefixes:
- Both processes maintain independent `tradeCounter`
- `INSERT OR IGNORE` on collision silently drops one process's row
- Subsequent `UPDATE live_trades SET pnl=... WHERE id='live-142'` overwrites the survivor's data

**Fix**: every process gets `PROCESS_ID_PREFIX` env var, prefixes all generated IDs.

---

## 16. Redemption Queue

Resolved winning positions need on-chain redemption (convert winning shares to USDC):

```
redeemResolvedPositions() {
  for position where redeemable=true AND curPrice=1.0:
    call redeem() on CTF contract via signer
    log gas + tx hash
}
```

**Gotcha**: Public Polygon RPCs fail `noNetwork` under production load. Paid RPC (Alchemy) is essential. Failed redemption means winning positions sit as "locked" shares without converting to cash → available bankroll stays too low → fewer positions.

**Cadence**: run redemption on startup + after every N resolved positions. Not time-critical (winnings don't lose value), but backlog ties up capital.

---

## 17. Exit Manager for Open Positions

For positions that pre-resolve (price hits 0 or 1 before market close):

```
runPositionExitScan() {
  for open live position:
    if curPrice >= 0.97 AND not redeemable: skip (already effectively won, wait for resolution)
    if curPrice <= 0.03 AND still time on clock: consider stop-loss exit
    if hit take-profit threshold: sell at bid
}
```

**Critical**: when an exit fires, wire the journal immediately — don't wait for the next cron resolution scan. Otherwise the ghost exposure gap creates ~30-min lag where bankroll appears committed but position is closed.

---

## 18. Minimal Working Skeleton

For an AI agent starting fresh, this is the minimum viable architecture:

```
src/
  core/
    config.ts                 # env loading, strategy flags, gates
    env-validate.ts           # fail-fast on missing env
  scanner/
    scanner.ts                # main runScanCycle() dispatcher
    neg-risk-bracket.ts       # first strategy — structural arb
  execution/
    clob-executor.ts          # CLOB SDK wrapper, sellPosition(), buyLimit()
    safety-guard.ts           # canTradeLive() gate
    live-trade-bridge.ts      # executeOrPaper() unified fire path
    trade-journal.ts          # paper + live DB writes
    db.ts                     # SQLite schema + migrations
  utils/
    polymarket-data-api.ts    # /positions, /activity wrappers
    telegram.ts               # alert + notification helpers
    logger.ts                 # structured JSON logs
  index.ts                    # main() — event loop + startup sequence
```

Everything else grows organically. Don't build abstractions for future strategies before you have 3 actual strategies. Three similar lines beats a premature base class.

---

## What NOT to architect

- **Full strategy framework**. Strategies diverge enough that "base strategy class" becomes a bottleneck. Write each as a plain function that the scanner calls.
- **Event bus / message queue**. Unless you're distributed, an in-process event loop is simpler and debugable.
- **Generic "signal" abstraction**. Whale signals, orderflow signals, news signals all have different schemas. Don't force one shape.
- **State-machine library**. A handful of string states + a switch statement reads better than a formal FSM library for this domain.
- **Custom DB**. SQLite via better-sqlite3 handles 10K writes/sec in-process. Don't start with Postgres.

---

See `PLAYBOOK.md` for the 10-step build order using these patterns.
