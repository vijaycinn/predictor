import type { ParsedArgs } from './parse-args.js';
import { wrapSuccess, wrapError } from './json.js';
import { getDb } from '../db/index.js';
import { auditTrail } from '../audit/index.js';
import { ScanLoop } from '../scan/loop.js';
import { createOctagonInvoker } from '../scan/invoker.js';
import { formatScanTable } from './scan-formatters.js';
import { callKalshiApi } from '../tools/kalshi/api.js';
import { getBotSetting } from '../utils/bot-config.js';
import type { ScanResult } from '../scan/loop.js';

export async function handleWatch(args: ParsedArgs): Promise<void> {
  const db = getDb();
  const invoker = createOctagonInvoker();
  const loop = new ScanLoop(db, auditTrail, invoker);

  const rawMinInterval = Number(getBotSetting('watch.min_interval_minutes'));
  const minIntervalMinutes = Number.isFinite(rawMinInterval) && rawMinInterval > 0 ? rawMinInterval : 15;
  const intervalMinutes = args.live
    ? minIntervalMinutes
    : Math.max(minIntervalMinutes, args.interval ?? 60);
  const intervalMs = intervalMinutes * 60_000;
  const theme = args.theme ?? 'top50';

  let totalCycles = 0;
  let totalEdges = 0;
  const startTime = Date.now();
  let stopped = false;
  let timer: ReturnType<typeof setInterval>;

  const shutdown = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);

    const durationSec = ((Date.now() - startTime) / 1000).toFixed(0);
    if (args.json) {
      console.log(JSON.stringify({
        event: 'watch_stopped',
        totalCycles,
        totalEdges,
        durationSeconds: Number(durationSec),
      }));
    } else {
      console.log('');
      console.log(`Watch stopped. ${totalCycles} cycles, ${totalEdges} edges found in ${durationSec}s`);
    }
    process.exit(0);
  };

  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);

  if (!args.json) {
    console.log(`Watching theme "${theme}" every ${intervalMinutes}m (Ctrl+C to stop)\n`);
  }

  const runCycle = async (): Promise<void> => {
    try {
      const result = await loop.runOnce({ theme, dryRun: args.dryRun });
      totalCycles++;
      totalEdges += result.edgeSnapshots.length;

      if (args.json) {
        const actionable = result.edgeSnapshots.filter(
          (s) => s.confidence === 'high' || s.confidence === 'very_high'
        ).length;
        console.log(JSON.stringify(wrapSuccess('watch', result, {
          scan_id: result.scanId,
          theme,
          events_scanned: result.eventsScanned,
          actionable,
          octagon_credits_used: result.octagonCreditsUsed,
        })));
      } else {
        console.clear();
        console.log(`Watch cycle #${totalCycles} — theme "${theme}" — every ${intervalMinutes}m\n`);
        console.log(formatScanTable(result));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (args.json) {
        console.log(JSON.stringify(wrapError('watch', 'SCAN_ERROR', message)));
      } else {
        console.error(`[watch] Scan error: ${message}`);
      }
    }
  };

  // Run first cycle immediately
  await runCycle();

  // Continue running on interval until stopped
  timer = setInterval(() => {
    if (stopped) return;
    runCycle().catch((err) => {
      console.error(`[watch] Scan cycle failed: ${err instanceof Error ? err.message : String(err)}`);
    });
  }, intervalMs);

  // Keep process alive — the SIGINT handler will exit
  await new Promise<void>(() => {});
}

// ─── Per-ticker watch mode ──────────────────────────────────────────────────

interface TickerSnapshot {
  ticker: string;
  lastPrice: string;
  yesAsk: string;
  yesBid: string;
  noAsk: string;
  noBid: string;
  spread: string;
  volume: string;
  openInterest: string;
  orderbook: { price: string; quantity: number }[];
  timestamp: string;
}

function parseDollarField(val: string | number | undefined | null, isCentField = false): number {
  if (val === undefined || val === null) return 0;
  const n = typeof val === 'number' ? val : parseFloat(val as string);
  if (isNaN(n)) return 0;
  return isCentField ? n / 100 : n;
}

/** Format a value already in dollars (0.00–1.00) */
function fmtDollars(val: number): string {
  return `$${val.toFixed(2)}`;
}

/** Format a cent integer (1–99) as dollars */
function fmtCents(val: number): string {
  return `$${(val / 100).toFixed(2)}`;
}

function fmtNum(n: number | string | undefined | null): string {
  if (n === undefined || n === null) return '-';
  const val = typeof n === 'number' ? n : parseFloat(n as string);
  if (isNaN(val)) return '-';
  return val.toLocaleString();
}

async function fetchTickerSnapshot(ticker: string): Promise<TickerSnapshot> {
  // Fetch market data
  const market = await callKalshiApi('GET', `/markets/${ticker}`) as any;
  const m = market.market ?? market;

  const hasDollarYesAsk = m.yes_ask_dollars != null || m.dollar_yes_ask != null;
  const hasDollarYesBid = m.yes_bid_dollars != null || m.dollar_yes_bid != null;
  const hasDollarNoAsk = m.no_ask_dollars != null || m.dollar_no_ask != null;
  const hasDollarNoBid = m.no_bid_dollars != null || m.dollar_no_bid != null;
  const yesAsk = parseDollarField(m.yes_ask_dollars ?? m.dollar_yes_ask ?? m.yes_ask, !hasDollarYesAsk);
  const yesBid = parseDollarField(m.yes_bid_dollars ?? m.dollar_yes_bid ?? m.yes_bid, !hasDollarYesBid);
  const noAsk = parseDollarField(m.no_ask_dollars ?? m.dollar_no_ask ?? m.no_ask, !hasDollarNoAsk);
  const noBid = parseDollarField(m.no_bid_dollars ?? m.dollar_no_bid ?? m.no_bid, !hasDollarNoBid);
  const spread = yesAsk - yesBid;

  // Fetch orderbook
  let orderbook: { price: string; quantity: number }[] = [];
  try {
    const ob = await callKalshiApi('GET', `/markets/${ticker}/orderbook`) as any;
    const book = ob.orderbook ?? ob;
    const rawEntries = Array.isArray(book.yes) ? book.yes : [];
    orderbook = rawEntries
      .filter((entry: unknown): entry is [number, number] =>
        Array.isArray(entry) && entry.length === 2 &&
        typeof entry[0] === 'number' && typeof entry[1] === 'number'
      )
      .slice(0, 5)
      .map(([price, qty]: [number, number]) => ({
        price: fmtCents(price),
        quantity: qty,
      }));
  } catch {
    // Orderbook not available for all markets
  }

  // Resolve last price — dollar string fields are already in dollars; last_price is cents
  const dollarLastStr = m.last_price_dollars ?? m.dollar_last_price;
  const parsedDollarLast = dollarLastStr != null ? parseFloat(dollarLastStr) : NaN;
  const lastPriceDollars = Number.isFinite(parsedDollarLast)
    ? parsedDollarLast
    : (m.last_price != null ? m.last_price / 100 : NaN);

  return {
    ticker,
    lastPrice: Number.isFinite(lastPriceDollars) ? fmtDollars(lastPriceDollars) : '-',
    yesAsk: fmtDollars(yesAsk),
    yesBid: fmtDollars(yesBid),
    noAsk: fmtDollars(noAsk),
    noBid: fmtDollars(noBid),
    spread: `$${spread.toFixed(4)}`,
    volume: fmtNum(m.volume_fp ?? m.volume),
    openInterest: fmtNum(m.open_interest_fp ?? m.open_interest),
    orderbook,
    timestamp: new Date().toISOString(),
  };
}

function formatTickerDashboard(snap: TickerSnapshot, tick: number): string {
  const lines: string[] = [];
  lines.push(`  ${snap.ticker}  (tick #${tick})  ${new Date(snap.timestamp).toLocaleTimeString()}`);
  lines.push('');
  lines.push(`  Last Price:     ${snap.lastPrice}`);
  lines.push(`  YES Bid / Ask:  ${snap.yesBid} / ${snap.yesAsk}   Spread: ${snap.spread}`);
  lines.push(`  NO  Bid / Ask:  ${snap.noBid} / ${snap.noAsk}`);
  lines.push(`  Volume:         ${snap.volume}   Open Interest: ${snap.openInterest}`);

  if (snap.orderbook.length > 0) {
    lines.push('');
    lines.push('  Orderbook (YES, top 5):');
    for (const level of snap.orderbook) {
      lines.push(`    ${level.price}  ×${level.quantity}`);
    }
  }

  return lines.join('\n');
}

export async function handleWatchTicker(ticker: string, args: ParsedArgs): Promise<void> {
  let totalTicks = 0;
  const startTime = Date.now();
  let stopped = false;
  let timer: ReturnType<typeof setInterval>;

  const shutdown = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);

    const durationSec = ((Date.now() - startTime) / 1000).toFixed(0);
    if (args.json) {
      console.log(JSON.stringify({
        event: 'watch_stopped',
        ticker,
        totalTicks,
        durationSeconds: Number(durationSec),
      }));
    } else {
      console.log('');
      console.log(`Watch stopped. ${totalTicks} ticks in ${durationSec}s`);
    }
    process.exit(0);
  };

  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);

  const rawTickerInterval = Number(getBotSetting('watch.ticker_interval_seconds'));
  const tickerIntervalMs = (Number.isFinite(rawTickerInterval) && rawTickerInterval > 0 ? rawTickerInterval : 5) * 1000;
  const intervalMs = args.interval ? args.interval * 1000 : tickerIntervalMs;
  const intervalLabel = intervalMs >= 60_000 ? `${(intervalMs / 60_000).toFixed(0)}m` : `${(intervalMs / 1000).toFixed(0)}s`;

  if (!args.json) {
    console.log(`Watching ${ticker} every ${intervalLabel} (Ctrl+C to stop)\n`);
  }

  const runTick = async (): Promise<void> => {
    try {
      const snap = await fetchTickerSnapshot(ticker);
      totalTicks++;

      if (args.json) {
        console.log(JSON.stringify(wrapSuccess('watch:ticker', snap)));
      } else {
        console.clear();
        console.log(formatTickerDashboard(snap, totalTicks));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (args.json) {
        console.log(JSON.stringify(wrapError('watch:ticker', 'FETCH_ERROR', message)));
      } else {
        console.error(`[watch] Error: ${message}`);
      }
    }
  };

  // First tick immediately
  await runTick();

  // Continue on interval
  timer = setInterval(() => {
    if (stopped) return;
    runTick().catch((err) => {
      const message = err instanceof Error ? err.message : String(err);
      console.error(`[watch-ticker] Tick failed: ${message}`);
    });
  }, intervalMs);

  // Keep process alive
  await new Promise<void>(() => {});
}
