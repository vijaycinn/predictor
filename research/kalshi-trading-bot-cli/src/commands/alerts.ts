import type { ParsedArgs } from './parse-args.js';
import type { CLIResponse } from './json.js';
import type { Alert } from '../db/alerts.js';
import { wrapSuccess, wrapError } from './json.js';
import { getDb } from '../db/index.js';
import { getAllAlerts } from '../db/alerts.js';
import { formatTable } from './scan-formatters.js';

export async function handleAlerts(args: ParsedArgs): Promise<CLIResponse<Alert[]>> {
  const db = getDb();

  let sinceEpoch = 0;
  if (args.since) {
    const t = new Date(args.since).getTime();
    if (!Number.isFinite(t)) {
      return wrapError('alerts', 'INVALID_DATE',
        `Invalid date for --since: "${args.since}". Use ISO format e.g. 2026-03-01T00:00:00Z`);
    }
    sinceEpoch = Math.floor(t / 1000);
  }

  const rows = getAllAlerts(db, {
    ticker: args.ticker,
    since: sinceEpoch || undefined,
  });

  return wrapSuccess('alerts', rows);
}

export function formatAlertsHuman(alerts: Alert[]): string {
  if (alerts.length === 0) {
    return '  No alerts found.';
  }

  const rows = alerts.map((a) => [
    a.created_at ? new Date(a.created_at * 1000).toISOString().slice(0, 16) : '-',
    a.ticker ?? '-',
    a.alert_type,
    a.edge !== null && a.edge !== undefined ? `${(a.edge * 100).toFixed(1)}%` : '-',
    a.message.length > 50 ? a.message.slice(0, 49) + '…' : a.message,
    a.status ?? 'pending',
  ]);

  return formatTable(
    ['Time', 'Ticker', 'Type', 'Edge', 'Message', 'Status'],
    rows,
  );
}
