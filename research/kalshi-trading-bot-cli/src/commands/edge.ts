import type { ParsedArgs } from './parse-args.js';
import type { CLIResponse } from './json.js';
import type { EdgeRow } from '../db/edge.js';
import { wrapSuccess, wrapError } from './json.js';
import { getDb } from '../db/index.js';
import { getEdgeHistory, getActionableEdges, getLatestEdge } from '../db/edge.js';
import { formatEdgeTable } from './scan-formatters.js';

export async function handleEdge(args: ParsedArgs): Promise<CLIResponse<EdgeRow[]>> {
  const db = getDb();
  let rows: EdgeRow[];

  const DEFAULT_MAX_AGE_S = 24 * 60 * 60; // 24 hours
  let sinceEpoch: number;
  if (args.since) {
    const parsed = new Date(args.since).getTime();
    if (!Number.isFinite(parsed)) {
      return wrapError('edge', 'INVALID_DATE', `Invalid date format for --since: "${args.since}"`);
    }
    sinceEpoch = Math.floor(parsed / 1000);
  } else {
    sinceEpoch = Math.floor(Date.now() / 1000) - DEFAULT_MAX_AGE_S;
  }

  if (args.ticker) {
    // History for a single ticker
    rows = getEdgeHistory(db, args.ticker, sinceEpoch);
  } else if (args.minConfidence) {
    // Latest per ticker filtered by confidence
    rows = getActionableEdges(db, args.minConfidence);
    rows = rows.filter((r) => r.timestamp >= sinceEpoch);
  } else if (args.theme) {
    // Get tickers for theme, then latest edge per ticker
    const themeRows = db.query(
      `SELECT DISTINCT ticker FROM edge_history
       WHERE event_ticker IN (SELECT ticker FROM events WHERE theme_id = $theme)`
    ).all({ $theme: args.theme }) as { ticker: string }[];

    rows = themeRows
      .map((t) => getLatestEdge(db, t.ticker))
      .filter((r): r is EdgeRow => r !== null);

    rows = rows.filter((r) => r.timestamp >= sinceEpoch);
  } else {
    // Default: all latest edges
    rows = getActionableEdges(db, 'low');
    rows = rows.filter((r) => r.timestamp >= sinceEpoch);
  }

  // Sort by |edge| descending
  rows.sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge));

  if (args.minEdge != null) {
    rows = rows.filter((r) => Math.abs(r.edge) >= args.minEdge!);
  }

  return wrapSuccess('edge', rows);
}

export function formatEdgeHuman(rows: EdgeRow[]): string {
  return formatEdgeTable(rows);
}
