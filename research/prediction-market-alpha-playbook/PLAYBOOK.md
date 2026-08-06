# PLAYBOOK — Zero to First Paper Fire

This is the opinionated 10-step build sequence for an AI agent or developer starting from scratch. Each step has concrete deliverables and validation criteria. Expected total time: **1-3 days** to first paper fire, **1-2 weeks** to first live-canary fire.

---

## Prerequisites

- **Language**: TypeScript (Node.js 20+) recommended. Python works but SDKs are more mature in TS.
- **Platform**: Linux VPS for production. Development on anything.
- **Accounts**:
  - Polymarket: create via web UI, fund via USDC on Polygon, derive proxy wallet + API keys
  - Kalshi (optional, US-regulated): KYC required, API key via dashboard
  - GitHub: for CI/CD
- **API keys to obtain** (free tiers sufficient for testing):
  - Alchemy (Polygon RPC)
  - OpenWeatherMap (if weather-focused)
  - Telegram Bot (for notifications)

Estimated setup: 2-4 hours including KYC.

---

## Step 1 — Project skeleton

Create repo structure:

```
myBot/
  src/
    core/
      config.ts
      env-validate.ts
    scanner/
    execution/
    utils/
    index.ts
  .env.example
  .gitignore  (with .env, node_modules, logs)
  package.json
  tsconfig.json
```

**Dependencies**:
```json
{
  "@polymarket/clob-client": "latest",
  "axios": "^1.7.0",
  "better-sqlite3": "^11.0",
  "dotenv": "^17.0",
  "ethers": "^5.7",
  "tsx": "^4.0",
  "typescript": "^5.5"
}
```

**Dev dependencies**:
```json
{
  "eslint": "^9.0",
  "@typescript-eslint/parser": "^8.0",
  "@typescript-eslint/eslint-plugin": "^8.0",
  "jest": "^29.0",
  "@types/node": "^20.0"
}
```

**Verification**: `npx tsc --noEmit && npx eslint .` both exit clean on empty project.

---

## Step 2 — Environment validation

Before any business logic, write `env-validate.ts`:

```typescript
import "dotenv/config"

interface EnvRule {
  key: string
  required: boolean
  pattern?: RegExp
  hint?: string
}

const RULES: EnvRule[] = [
  { key: "POLYMARKET_ADDRESS", required: true, pattern: /^0x[a-fA-F0-9]{40}$/, hint: "Proxy wallet (not EOA)" },
  { key: "POLYMARKET_PRIVATE_KEY", required: true, pattern: /^0x[a-fA-F0-9]{64}$/, hint: "64-hex, 0x-prefixed" },
  { key: "POLYGON_RPC_URL", required: true, pattern: /^https:\/\/.+/, hint: "Paid RPC, not public" },
  { key: "TELEGRAM_BOT_TOKEN", required: false, pattern: /^\d+:[A-Za-z0-9_-]{30,}$/ },
  // ... more as needed
]

export function assertValidEnv(): void {
  const errors: string[] = []
  for (const rule of RULES) {
    const val = process.env[rule.key]?.trim()  // .trim() for CRLF safety
    if (!val && rule.required) errors.push(`${rule.key} missing`)
    else if (val && rule.pattern && !rule.pattern.test(val)) {
      errors.push(`${rule.key} malformed`)
    }
  }
  if (errors.length) {
    console.error("env invalid:"); errors.forEach(e => console.error("  " + e))
    process.exit(1)
  }
}
```

**Call at startup**, before any imports that could throw cryptic errors on missing env.

**Verification**: Bot refuses to start with missing env, prints clear messages.

---

## Step 3 — First strategy: NEG_RISK Sum Arb

This is the simplest real strategy to implement and gives you fire-path integration without model risk.

### 3.1 Gamma API client

```typescript
// src/utils/gamma.ts
import axios from "axios"

export interface GammaMarket {
  id: string
  slug: string
  negRisk: boolean
  clobTokenIds: string  // JSON array
  outcomes: string  // JSON array
  outcomePrices: string  // JSON array
  // ...
}

export interface GammaEvent {
  id: string
  slug: string
  markets: GammaMarket[]
  negRisk: boolean
  // ...
}

export async function fetchNegRiskEvents(limit = 200): Promise<GammaEvent[]> {
  const resp = await axios.get<GammaEvent[]>("https://gamma-api.polymarket.com/events", {
    params: { negRisk: true, active: true, closed: false, limit },
    timeout: 10_000,
  })
  return resp.data.filter(e => e.markets?.length >= 3)
}
```

### 3.2 Bracket arb scanner

```typescript
// src/scanner/neg-risk-bracket.ts
import { fetchNegRiskEvents } from "../utils/gamma.js"

export interface BracketArb {
  eventSlug: string
  legs: Array<{ tokenId: string, side: "YES" | "NO", price: number, size: number }>
  expectedPayout: number
  sumYesAsk: number
}

export async function scanBracketArbs(): Promise<BracketArb[]> {
  const events = await fetchNegRiskEvents(200)
  const arbs: BracketArb[] = []
  
  for (const event of events) {
    const outcomePrices = event.markets.map(m => {
      const prices = JSON.parse(m.outcomePrices) as string[]
      return parseFloat(prices[0])  // YES price
    })
    
    const sumYesAsk = outcomePrices.reduce((s, p) => s + p, 0)
    
    if (sumYesAsk > 1.03) {
      // Opportunity: sell all YES tokens (or equivalently buy all NO tokens)
      // Fire condition: all legs must have visible liquid asks
      // ... populate arbs[] ...
    }
  }
  
  return arbs
}
```

**Important gotcha**: check every leg has a visible ask at your size before firing. Partial-basket (any leg has `ask=null`) invalidates the arb.

### 3.3 Fire path (paper-only first)

```typescript
// src/execution/fire-bracket.ts
export async function fireBracketArb(arb: BracketArb): Promise<void> {
  // Record paper trades for each leg BEFORE any live action
  for (const leg of arb.legs) {
    await recordPaperTrade({
      strategy: "neg_risk_bracket_arb",
      tokenId: leg.tokenId,
      side: leg.side,
      entry: leg.price,
      size: leg.size,
      arbClass: "neg_risk_bracket_arb",
    })
  }
}
```

**Paper-only**: don't even wire live orders yet. Build muscle memory on the paper side. Run for 48h, see arb hits.

**Expected cadence**: 0-3 arbs per day. NEG_RISK markets are generally efficient. If you see dozens per hour, you have a bug — arbs are rare when they happen.

---

## Step 4 — Paper-trade DB + logging

Set up SQLite:

```typescript
// src/execution/db.ts
import Database from "better-sqlite3"

const db = new Database("logs/trades.db")

db.exec(`
  CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    slug TEXT,
    question TEXT,
    token_id TEXT,
    side TEXT,
    size_usd REAL,
    entry_price REAL,
    actual_fill_price REAL,
    exit_price REAL,
    resolved INTEGER DEFAULT 0,
    pnl REAL,
    inflation_flagged INTEGER DEFAULT 0,
    arb_class TEXT,
    timestamp INTEGER NOT NULL,
    resolved_at INTEGER
  );
  
  CREATE TABLE IF NOT EXISTS live_trades (
    id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    slug TEXT,
    question TEXT,
    token_id TEXT,
    side TEXT,
    size_usd REAL,
    entry_price REAL,
    actual_fill_price REAL,
    fill_status TEXT,
    exit_price REAL,
    resolved INTEGER DEFAULT 0,
    pnl REAL,
    exit_stamping_suspect INTEGER DEFAULT 0,
    arb_class TEXT,
    leg_group_id TEXT,
    leg_index INTEGER,
    timestamp INTEGER NOT NULL,
    resolved_at INTEGER
  );
  
  CREATE INDEX IF NOT EXISTS idx_live_strategy ON live_trades(strategy);
  CREATE INDEX IF NOT EXISTS idx_live_resolved ON live_trades(resolved);
`)
```

**Key design**: `inflation_flagged` and `exit_stamping_suspect` columns are there from day 1. You'll need them.

---

## Step 5 — Data API integration + PnL reconciliation

```typescript
// src/utils/polymarket-data-api.ts
import axios from "axios"

export interface DataApiPosition {
  slug: string
  conditionId: string
  outcome: string
  outcomeIndex: number
  size: number
  initialValue: number
  curPrice: number
  cashPnl: number
  currentValue: number
  redeemable: boolean
}

export async function fetchPositions(address: string): Promise<DataApiPosition[]> {
  const resp = await axios.get<DataApiPosition[]>(
    "https://data-api.polymarket.com/positions",
    { params: { user: address, sizeThreshold: 0.1, limit: 500 }, timeout: 15_000 }
  )
  return resp.data ?? []
}

export async function fetchActivity(address: string, limit = 100) {
  const resp = await axios.get(
    "https://data-api.polymarket.com/activity",
    { params: { user: address, type: "TRADE", limit }, timeout: 15_000 }
  )
  return resp.data ?? []
}
```

**Reconciliation cron** (daily minimum):

```typescript
// Reconciles journal PnL against Data API ground truth
export async function reconcileLivePnl(address: string): Promise<void> {
  const activity = await fetchActivity(address, 500)
  const positions = await fetchPositions(address)
  
  const openLive = db.prepare(
    "SELECT * FROM live_trades WHERE resolved = 0"
  ).all() as LiveTradeRow[]
  
  for (const trade of openLive) {
    const pos = positions.find(p => p.conditionId === trade.marketId)
    if (!pos || !pos.redeemable) continue
    
    // POSITION IS RESOLVED
    if (trade.actual_fill_price === null) {
      // Can't stamp — mark suspect, wait for Data API activity reconciliation
      db.prepare("UPDATE live_trades SET exit_stamping_suspect = 1 WHERE id = ?")
        .run(trade.id)
      continue
    }
    
    const won = pos.curPrice >= 0.5  // only valid when redeemable
    const exitPrice = won ? 1.0 : 0.0
    const pnl = won
      ? (1.0 - trade.actual_fill_price) * (trade.size_usd / trade.actual_fill_price)
      : -trade.size_usd
    
    db.prepare(`
      UPDATE live_trades 
      SET exit_price = ?, pnl = ?, resolved = 1, resolved_at = ?
      WHERE id = ?
    `).run(exitPrice, pnl, Date.now(), trade.id)
  }
}
```

**Rule**: No strategy graduates or scales based on journal PnL. Always reconcile first.

---

## Step 6 — CLOB execution integration

Only after paper-only has run stably for 48h:

```typescript
// src/execution/clob-executor.ts
import { ClobClient, Chain, SignatureType, Side, OrderType } from "@polymarket/clob-client"
import { Wallet } from "@ethersproject/wallet"

let client: ClobClient | null = null

export async function initClobClient(privateKey: string): Promise<void> {
  const signer = new Wallet(privateKey)
  const chainId = Chain.POLYGON
  const funderAddress = process.env.POLYMARKET_ADDRESS  // proxy, not EOA

  client = new ClobClient(
    "https://clob.polymarket.com",
    chainId,
    signer,
    undefined,  // creds derived from signer
    SignatureType.POLY_PROXY,
    funderAddress
  )
  
  // Derive L2 API key (writes to ClobClient internal state)
  const creds = await client.createOrDeriveApiKey()
  client.setApiCreds(creds)
}

export async function buyLimit(tokenId: string, size: number, maxPrice: number): Promise<{sold: boolean, orderId?: string, fillPrice?: number}> {
  if (!client) throw new Error("CLOB client not initialized")
  
  // Floor size to 4 decimals to dodge microshare mismatch
  const flooredSize = Math.floor(size * 10000) / 10000
  
  const order = await client.createAndPostOrder({
    tokenID: tokenId,
    price: maxPrice,
    side: Side.BUY,
    size: flooredSize,
    feeRateBps: 0,
  }, { tickSize: "0.001", negRisk: false })
  
  return {
    sold: order.status === "matched",
    orderId: order.orderID,
    fillPrice: parseFloat(order.takingAmount || "0") / flooredSize,
  }
}
```

**Never commit private keys. Ever.**

---

## Step 7 — Event loop + main()

```typescript
// src/index.ts
import "dotenv/config"
import { assertValidEnv } from "./core/env-validate.js"
import { initClobClient } from "./execution/clob-executor.js"
import { scanBracketArbs } from "./scanner/neg-risk-bracket.js"
import { reconcileLivePnl } from "./utils/polymarket-data-api.js"

assertValidEnv()

async function runScanCycle(): Promise<void> {
  try {
    const arbs = await scanBracketArbs()
    if (arbs.length > 0) {
      console.log(`bracket scan: ${arbs.length} opportunities`)
      for (const arb of arbs) { await firePaperArb(arb) }
    }
  } catch (err) {
    console.error("scan cycle error:", err)
  }
}

async function runReconciliation(): Promise<void> {
  try {
    await reconcileLivePnl(process.env.POLYMARKET_ADDRESS!.trim())
  } catch (err) {
    console.error("reconciliation error:", err)
  }
}

async function main(): Promise<void> {
  await initClobClient(process.env.POLYMARKET_PRIVATE_KEY!.trim())
  
  console.log("bot starting")
  
  // Initial reconciliation
  await runReconciliation()
  
  // Cron scanner
  setInterval(runScanCycle, 30_000)
  
  // Reconciliation every 10 min
  setInterval(runReconciliation, 10 * 60_000)
  
  process.on("SIGINT", () => { console.log("shutting down"); process.exit(0) })
}

main().catch(err => { console.error("fatal:", err); process.exit(1) })
```

**Verification**: bot starts clean, logs scan cycles every 30s, reconciles every 10 min.

---

## Step 8 — Add safety guards

```typescript
// src/execution/safety-guard.ts
const EXPOSURE = { total: 0, perStrategy: {} as Record<string, number> }
const DISABLED = new Set<string>()
const RECENT_LOSSES: Record<string, Array<{ ts: number, pnl: number }>> = {}

export const SAFETY = {
  MAX_TOTAL_EXPOSURE_USD: 300,
  MAX_SINGLE_POSITION_USD: 25,
  DAILY_LOSS_CAP_PER_STRATEGY: 50,
  CONSECUTIVE_LOSS_AUTO_DISABLE: 3,
}

export function canTradeLive(strategy: string, sizeUsd: number): { ok: boolean, reason?: string } {
  if (DISABLED.has(strategy)) return { ok: false, reason: "disabled" }
  if (EXPOSURE.total + sizeUsd > SAFETY.MAX_TOTAL_EXPOSURE_USD) return { ok: false, reason: "total-exposure-cap" }
  if (sizeUsd > SAFETY.MAX_SINGLE_POSITION_USD) return { ok: false, reason: "single-position-cap" }
  
  const todaysLosses = (RECENT_LOSSES[strategy] ?? [])
    .filter(x => x.ts > Date.now() - 86400000)
    .reduce((s, x) => s + x.pnl, 0)
  if (todaysLosses < -SAFETY.DAILY_LOSS_CAP_PER_STRATEGY) {
    return { ok: false, reason: "daily-loss-cap" }
  }
  
  return { ok: true }
}

export function recordLiveTrade(strategy: string, sizeUsd: number): void {
  EXPOSURE.total += sizeUsd
  EXPOSURE.perStrategy[strategy] = (EXPOSURE.perStrategy[strategy] ?? 0) + sizeUsd
}

export function recordStrategyResult(strategy: string, pnl: number): void {
  RECENT_LOSSES[strategy] = RECENT_LOSSES[strategy] ?? []
  RECENT_LOSSES[strategy].push({ ts: Date.now(), pnl })
  
  // Auto-disable on 3 consecutive losses
  const recent = RECENT_LOSSES[strategy].slice(-SAFETY.CONSECUTIVE_LOSS_AUTO_DISABLE)
  if (recent.length === SAFETY.CONSECUTIVE_LOSS_AUTO_DISABLE && recent.every(x => x.pnl < 0)) {
    DISABLED.add(strategy)
    console.log(`AUTO-DISABLE ${strategy} — 3 consecutive losses`)
  }
}
```

Wire into fire path:

```typescript
const gate = canTradeLive(strategy, sizeUsd)
if (!gate.ok) return { paper: true, live: false, reason: gate.reason }
```

---

## Step 9 — Observability

### Telegram alerts

```typescript
// src/utils/telegram.ts
import axios from "axios"

const TOKEN = process.env.TELEGRAM_BOT_TOKEN?.trim()
const CHAT = process.env.TELEGRAM_CHAT_ID?.trim()

export async function tgSend(message: string): Promise<void> {
  if (!TOKEN || !CHAT) return
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id: CHAT, text: message, parse_mode: "Markdown"
    }, { timeout: 10_000 })
  } catch (err) { /* silent */ }
}

export async function tgTradeFired(strategy: string, side: string, size: number, price: number): Promise<void> {
  await tgSend(`🔵 ${strategy} ${side} $${size} @ ${price.toFixed(3)}`)
}

export async function tgDailyPnl(totalPnl: number, byStrategy: Record<string, number>): Promise<void> {
  const lines = [
    `📊 *Daily PnL:* ${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}`,
    ...Object.entries(byStrategy).map(([s, p]) => `  ${s}: ${p >= 0 ? '+' : ''}$${p.toFixed(2)}`)
  ]
  await tgSend(lines.join("\n"))
}
```

### /metrics endpoint

```typescript
// src/utils/metrics.ts
import http from "http"

const METRICS = {
  positions_open: 0,
  scan_cycles_total: 0,
  fires_total: {} as Record<string, number>,
  usdc_balance_dollars: 0,
}

export function startMetricsServer(port = 9090): void {
  http.createServer((req, res) => {
    if (req.url !== "/metrics") { res.writeHead(404); return res.end() }
    res.writeHead(200, { "Content-Type": "text/plain" })
    res.write(`# HELP bot_positions_open Number of open positions\n`)
    res.write(`# TYPE bot_positions_open gauge\n`)
    res.write(`bot_positions_open ${METRICS.positions_open}\n`)
    // ... more metrics
    res.end()
  }).listen(port, "127.0.0.1", () => console.log(`metrics on :${port}/metrics`))
}
```

Grafana scrapes `http://localhost:9090/metrics` via Prometheus; build dashboards for per-strategy PnL, fire cadence, exposure.

---

## Step 10 — CI/CD pipeline

`.github/workflows/ci-deploy.yml`:

```yaml
name: CI + Deploy
on:
  push:
    branches: [main]

jobs:
  tsc-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npx tsc --noEmit

  eslint-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npx eslint . --quiet

  smoke-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npx jest --passWithNoTests

  deploy:
    needs: [tsc-check, eslint-check, smoke-tests]
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /root/mybot
            git clean -fd src/scripts/ tmp/ 2>&1 || true
            git pull origin main
            npm ci --legacy-peer-deps
            pm2 restart bot --update-env

  alert-on-failure:
    needs: [tsc-check, eslint-check, smoke-tests]
    runs-on: ubuntu-latest
    if: failure() && github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - name: Notify
        run: |
          curl -X POST https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage \
            -d chat_id=${{ secrets.TELEGRAM_CHAT_ID }} \
            -d "text=🚨 CI failed on main — deploy skipped. commit: ${{ github.sha }}"
        continue-on-error: true
```

**Critical**: the `git clean -fd src/scripts/ tmp/` line in deploy handles the scp'd-then-committed collision trap. `|| true` keeps it graceful.

**Verify**: push any trivial commit, watch `gh run list --limit 1` — must turn green, must deploy.

---

## After Step 10: What Comes Next

You now have a working bot with one strategy (NEG_RISK bracket arb) in paper mode, safety guards, Data API reconciliation, observability, and CI/CD. From here:

### Week 2: Second strategy
Implement **within-market YES+NO < 1.0 arb**. Same structural-arb class, different scan surface. Validates your fire path on a second pattern.

### Week 3: Data API reconciliation + graduation
Run 100+ paper fires, confirm PnL reconciles to Data API, graduate first strategy to **shadow-live** ($1/fire).

### Week 4: Third strategy + exhaustive search tool
Build `exhaustive-cohort-search.ts` per `METHODOLOGY.md`. You'll want this before you have any strategies worth killing.

### Week 5-6: Cross-exchange
Add Kalshi API integration. Build the `400bps raw edge floor` gate. Cross-venue arbs are rarer but larger when they hit.

### Ongoing
- Reconciliation jobs quarterly
- Exhaustive-search re-runs on every strategy with ≥50 new resolved rows
- Memory entries for every "that burned me" lesson

---

## What NOT To Do

- **Don't start with directional/predictive strategies.** Start with structural arbs. Much less to debug.
- **Don't skip paper mode.** Every strategy paper-validates before live. Exception: none.
- **Don't trust CI "success" without `gh run list` check.** Green-gate failures can hide.
- **Don't commit `.env`.** Yes, still don't.
- **Don't scale sizing before N≥30 with Wilson lb95≥55%.** Fat-tail rewards are variance; fat-tail losses are ruin.
- **Don't kill strategies on aggregate WR.** Exhaustive cohort search first. Always.

---

## Honest Expectations

- **Week 1-2**: $0 in real revenue. You're building. Accept it.
- **Week 3-4**: First live canary fires. Single-digit dollars per week. Not the point — you're validating the pipeline.
- **Week 5-8**: Graduated first strategy. Real $ starts if strategy has real edge.
- **Month 3+**: Multiple strategies, portfolio-level view, meaningful revenue (assuming edges found).

Prediction markets are net-zero games minus fees + infrastructure. The edge that exists is fragmented across scenarios and decays. Keep searching, keep measuring, keep disciplined.

---

## One Closing Rule

**If you take only one thing from this playbook, take this:**

> Before killing any strategy on aggregate WR or $, run exhaustive cohort search against the VPS-live DB. If ANY cohort at N≥5 has `mean > 0` AND `Wilson lb95 ≥ 40%`, retarget rather than amputate.

4 of 4 "killed" strategies had hidden alpha when tested this way. Your default should be retarget, not kill.
