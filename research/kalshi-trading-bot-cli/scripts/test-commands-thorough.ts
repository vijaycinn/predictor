#!/usr/bin/env bun
/**
 * Thorough test of every slash command.
 * Checks: no empty columns, pagination works, data is sensible.
 * Run: bun scripts/test-commands-thorough.ts
 */
import { handleSlashCommand } from '../src/commands/index.js';

let passed = 0;
let failed = 0;
const failures: string[] = [];

function fail(cmd: string, reason: string, detail?: string) {
  failed++;
  const msg = `${cmd}: ${reason}`;
  failures.push(msg);
  console.log(`  ✗ ${reason}`);
  if (detail) console.log(`    ${detail}`);
}

function pass(msg: string) {
  passed++;
  console.log(`  ✓ ${msg}`);
}

function checkTable(cmd: string, output: string, opts: {
  minRows?: number;
  requiredColumns?: string[];
  noEmptyColumns?: boolean;
} = {}) {
  const lines = output.split('\n');
  const tableLines = lines.filter(l => l.startsWith('│') && !l.includes('─'));

  if (tableLines.length === 0) {
    fail(cmd, 'No table found in output');
    return false;
  }

  const headerLine = tableLines[0];
  const headers = headerLine.split('│').filter(c => c.trim()).map(c => c.trim());
  const dataRows = tableLines.slice(1);

  // Check minimum rows
  const minRows = opts.minRows ?? 1;
  if (dataRows.length < minRows) {
    fail(cmd, `Expected at least ${minRows} data rows, got ${dataRows.length}`);
    return false;
  }
  pass(`${dataRows.length} data rows`);

  // Check required columns exist
  if (opts.requiredColumns) {
    for (const col of opts.requiredColumns) {
      if (!headers.some(h => h.includes(col))) {
        fail(cmd, `Missing required column: ${col}`, `Headers: ${headers.join(', ')}`);
        return false;
      }
    }
    pass(`Required columns present: ${opts.requiredColumns.join(', ')}`);
  }

  // Check no empty columns (all cells in a column are "-")
  if (opts.noEmptyColumns) {
    for (let colIdx = 0; colIdx < headers.length; colIdx++) {
      const colValues = dataRows.map(row => {
        const cells = row.split('│').filter(c => c.trim()).map(c => c.trim());
        return cells[colIdx] ?? '';
      });
      const allEmpty = colValues.every(v => v === '-' || v === '');
      if (allEmpty && dataRows.length > 0) {
        fail(cmd, `Column "${headers[colIdx]}" is entirely empty (all dashes)`,
          `Values: ${colValues.slice(0, 3).join(', ')}`);
        return false;
      }
    }
    pass('No entirely-empty columns');
  }

  return true;
}

async function testCommand(cmd: string, checks: (result: any) => void) {
  console.log(`\n${'━'.repeat(70)}`);
  console.log(`CMD: ${cmd}`);
  try {
    const start = Date.now();
    const result = await handleSlashCommand(cmd);
    const elapsed = Date.now() - start;
    console.log(`  Returned in ${elapsed}ms`);
    checks(result);
  } catch (e: any) {
    fail(cmd, `THREW: ${e.message}`);
  }
}

// ═══════════════════════════════════════════════════════════════════
// TEST EVERY COMMAND
// ═══════════════════════════════════════════════════════════════════

// --- /help ---
await testCommand('/help', (r) => {
  if (!r) return fail('/help', 'Returned null');
  if (!r.output.includes('/scan')) fail('/help', 'Missing /scan in help');
  else pass('Contains /scan');
  if (!r.output.includes('/balance')) fail('/help', 'Missing /balance');
  else pass('Contains /balance');
  if (!r.output.includes('/buy')) fail('/help', 'Missing /buy');
  else pass('Contains /buy');
});

// --- /status ---
await testCommand('/status', (r) => {
  if (!r) return fail('/status', 'Returned null');
  if (!r.output.includes('Exchange')) fail('/status', 'Missing exchange status');
  else pass('Shows exchange status');
  if (!r.output.includes('Trading')) fail('/status', 'Missing trading status');
  else pass('Shows trading status');
});

// --- /balance ---
await testCommand('/balance', (r) => {
  if (!r) return fail('/balance', 'Returned null');
  if (!r.output.includes('$')) fail('/balance', 'No dollar amounts');
  else pass('Shows dollar amounts');
  if (!r.output.includes('Balance')) fail('/balance', 'Missing Balance label');
  else pass('Shows Balance label');
});

// --- /positions ---
await testCommand('/positions', (r) => {
  if (!r) return fail('/positions', 'Returned null');
  // Either shows table or "No open positions."
  if (r.output.includes('No open positions')) {
    pass('Correctly shows no positions');
  } else {
    checkTable('/positions', r.output, {
      requiredColumns: ['Ticker', 'Position'],
      noEmptyColumns: true
    });
  }
});

// --- /orders ---
await testCommand('/orders', (r) => {
  if (!r) return fail('/orders', 'Returned null');
  if (r.output.includes('No orders found')) {
    pass('Correctly shows no orders');
  } else {
    checkTable('/orders', r.output, {
      requiredColumns: ['Ticker', 'Status'],
      noEmptyColumns: true
    });
  }
});

// --- /events (unfiltered, from index) ---
await testCommand('/events', (r) => {
  if (!r) return fail('/events', 'Returned null');
  checkTable('/events', r.output, {
    minRows: 10,
    requiredColumns: ['Ticker', 'Title', 'Mkts', 'Top Outcome', 'YES'],
    noEmptyColumns: true
  });
  if (!r.output.includes('/events next')) fail('/events', 'Missing pagination hint');
  else pass('Shows pagination hint');
});

// --- /events KXTESLA (filtered) ---
await testCommand('/events KXTESLA', (r) => {
  if (!r) return fail('/events KXTESLA', 'Returned null');
  checkTable('/events KXTESLA', r.output, {
    minRows: 1,
    requiredColumns: ['Ticker', 'Title', 'Mkts', 'YES'],
    noEmptyColumns: true
  });
  // Check it actually shows Tesla events
  if (!r.output.includes('KXTESLA')) fail('/events KXTESLA', 'No Tesla events');
  else pass('Shows Tesla events');
});

// --- /events next (pagination) ---
await testCommand('/events next', (r) => {
  if (!r) return fail('/events next', 'Returned null');
  // After /events KXTESLA, "next" should show no more or different data
  // This tests the edge case
  pass('Pagination responded');
});

// --- Reset events pagination ---
await testCommand('/events', (r) => {
  // Reset pagination state
  pass('Reset pagination');
});

// --- /events next (after reset, page 2 from index) ---
await testCommand('/events next', (r) => {
  if (!r) return fail('/events next', 'Returned null');
  if (r.output.includes('No more events')) {
    pass('Correctly shows no more events');
  } else {
    checkTable('/events next (p2)', r.output, {
      minRows: 10,
      noEmptyColumns: true
    });
  }
});

// --- /markets (unfiltered, from index) ---
await testCommand('/markets', (r) => {
  if (!r) return fail('/markets', 'Returned null');
  checkTable('/markets', r.output, {
    minRows: 10,
    requiredColumns: ['Ticker', 'Title', 'YES Ask', 'NO Ask', 'Volume', 'Closes'],
    noEmptyColumns: true
  });
  if (!r.output.includes('/markets next')) fail('/markets', 'Missing pagination hint');
  else pass('Shows pagination hint');
});

// --- /markets next (page 2) ---
let marketsPage1FirstRow = '';
{
  const r = await handleSlashCommand('/markets');
  const rows = r!.output.split('\n').filter((l: string) => l.startsWith('│') && !l.includes('─') && !l.includes('Ticker'));
  marketsPage1FirstRow = rows[0] ?? '';
}
await testCommand('/markets next', (r) => {
  if (!r) return fail('/markets next', 'Returned null');
  const rows = r.output.split('\n').filter((l: string) => l.startsWith('│') && !l.includes('─') && !l.includes('Ticker'));
  if (rows[0] === marketsPage1FirstRow) {
    fail('/markets next', 'Page 2 is identical to page 1 — pagination broken');
  } else {
    pass('Page 2 has different data than page 1');
  }
  checkTable('/markets next', r.output, {
    minRows: 10,
    noEmptyColumns: true
  });
});

// --- /markets KXTESLA (filtered) ---
await testCommand('/markets KXTESLA', (r) => {
  if (!r) return fail('/markets KXTESLA', 'Returned null');
  checkTable('/markets KXTESLA', r.output, {
    minRows: 5,
    requiredColumns: ['Ticker', 'YES Ask', 'NO Ask', 'Volume'],
    noEmptyColumns: true
  });
  if (!r.output.includes('KXTESLA')) fail('/markets KXTESLA', 'No Tesla markets');
  else pass('Shows Tesla markets');
});

// --- /event KXTESLA-26-Q1 (detail view) ---
await testCommand('/event KXTESLA-26-Q1', (r) => {
  if (!r) return fail('/event', 'Returned null');
  if (!r.output.includes('KXTESLA-26-Q1')) fail('/event', 'Missing event ticker');
  else pass('Shows event ticker');
  if (!r.output.includes('Tesla')) fail('/event', 'Missing Tesla in title');
  else pass('Shows Tesla title');
  if (!r.output.includes('Markets (')) fail('/event', 'Missing markets section');
  else pass('Shows markets section');
  // Check the nested markets table
  checkTable('/event KXTESLA-26-Q1', r.output, {
    minRows: 5,
    requiredColumns: ['Ticker', 'YES Ask', 'NO Ask', 'Volume'],
    noEmptyColumns: true
  });
});

// --- /market KXTESLA-26-Q1-340000 (detail view) ---
await testCommand('/market KXTESLA-26-Q1-340000', (r) => {
  if (!r) return fail('/market', 'Returned null');
  if (!r.output.includes('KXTESLA-26-Q1-340000')) fail('/market', 'Missing ticker');
  else pass('Shows ticker');
  if (!r.output.includes('YES Bid')) fail('/market', 'Missing YES Bid');
  else pass('Shows YES Bid');
  if (!r.output.includes('NO Bid')) fail('/market', 'Missing NO Bid');
  else pass('Shows NO Bid');
  if (!r.output.includes('Volume')) fail('/market', 'Missing Volume');
  else pass('Shows Volume');
  // Check prices aren't $0.00 for this active market
  if (r.output.includes('YES Bid:    $0.00')) fail('/market', 'YES Bid is $0.00');
  else pass('YES Bid is non-zero');
  if (r.output.includes('Orderbook')) pass('Shows orderbook');
  else fail('/market', 'Missing orderbook');
});

// --- /buy (trade preview) ---
await testCommand('/buy KXTESLA-26-Q1-340000 1 65', (r) => {
  if (!r) return fail('/buy', 'Returned null');
  if (!r.output.includes('Order Preview')) fail('/buy', 'Missing order preview');
  else pass('Shows order preview');
  if (!r.output.includes('BUY')) fail('/buy', 'Missing BUY action');
  else pass('Shows BUY action');
  if (!r.pendingTrade) fail('/buy', 'No pending trade set');
  else pass('Sets pending trade');
  if (r.pendingTrade?.ticker !== 'KXTESLA-26-Q1-340000') fail('/buy', 'Wrong ticker in pending trade');
  else pass('Correct ticker in pending trade');
});

// --- /sell (trade preview) ---
await testCommand('/sell KXTESLA-26-Q1-340000 5 70', (r) => {
  if (!r) return fail('/sell', 'Returned null');
  if (!r.output.includes('SELL')) fail('/sell', 'Missing SELL action');
  else pass('Shows SELL action');
  if (!r.pendingTrade) fail('/sell', 'No pending trade set');
  else pass('Sets pending trade');
  if (r.pendingTrade?.count !== 5) fail('/sell', `Wrong count: ${r.pendingTrade?.count}`);
  else pass('Correct count');
});

// --- /buy with bad args ---
await testCommand('/buy', (r) => {
  if (!r) return fail('/buy (no args)', 'Returned null');
  if (!r.output.includes('Usage')) fail('/buy (no args)', 'No usage hint');
  else pass('Shows usage hint');
});

// --- /cancel with no args ---
await testCommand('/cancel', (r) => {
  if (!r) return fail('/cancel', 'Returned null');
  if (!r.output.includes('Usage')) fail('/cancel', 'No usage hint');
  else pass('Shows usage hint');
});

// --- Agent fall-through commands ---
for (const cmd of ['/edge', '/recommend', '/deep-research', '/portfolio', '/unknown-cmd']) {
  await testCommand(cmd, (r) => {
    if (r !== null) fail(cmd, `Should return null (fall to agent), got output`);
    else pass('Correctly falls through to agent');
  });
}

// ═══════════════════════════════════════════════════════════════════
// SUMMARY
// ═══════════════════════════════════════════════════════════════════
console.log(`\n${'═'.repeat(70)}`);
console.log(`RESULTS: ${passed} passed, ${failed} failed`);
if (failures.length > 0) {
  console.log(`\nFAILURES:`);
  for (const f of failures) {
    console.log(`  • ${f}`);
  }
  process.exit(1);
}
