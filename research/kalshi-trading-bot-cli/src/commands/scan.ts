import type { ParsedArgs } from './parse-args.js';
import type { CLIResponse } from './json.js';
import type { ScanResult } from '../scan/loop.js';
import { wrapSuccess, wrapError } from './json.js';
import { getDb } from '../db/index.js';
import { auditTrail } from '../audit/index.js';
import { ScanLoop } from '../scan/loop.js';
import { createOctagonInvoker } from '../scan/invoker.js';
import { formatScanTable } from './scan-formatters.js';

export async function handleScan(args: ParsedArgs): Promise<CLIResponse<ScanResult>> {
  const db = getDb();
  const invoker = createOctagonInvoker();
  const loop = new ScanLoop(db, auditTrail, invoker);

  const result = await loop.runOnce({
    theme: args.theme ?? 'top50',
    dryRun: args.dryRun,
  });

  const actionable = result.edgeSnapshots.filter(
    (s) => s.confidence === 'high' || s.confidence === 'very_high'
  ).length;

  const meta: CLIResponse<ScanResult>['meta'] = {
    scan_id: result.scanId,
    theme: args.theme ?? 'top50',
    events_scanned: result.eventsScanned,
    actionable,
    octagon_credits_used: result.octagonCreditsUsed,
  };

  return wrapSuccess('scan', result, meta);
}

export function formatScanHuman(result: ScanResult): string {
  return formatScanTable(result);
}
