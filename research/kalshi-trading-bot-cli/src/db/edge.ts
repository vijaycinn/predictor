import type { Database } from 'bun:sqlite';

export interface EdgeRow {
  id?: number;
  ticker: string;
  event_ticker: string;
  timestamp: number;
  model_prob: number;
  market_prob: number;
  edge: number;
  octagon_report_id?: string | null;
  drivers_json?: string | null;
  sources_json?: string | null;
  catalysts_json?: string | null;
  cache_hit?: number | null;
  cache_miss?: number | null;
  confidence?: string | null;
}

const CONFIDENCE_RANK: Record<string, number> = {
  low: 0,
  moderate: 1,
  high: 2,
  very_high: 3,
};

export function insertEdge(db: Database, edge: EdgeRow): void {
  db.prepare(`
    INSERT INTO edge_history
      (ticker, event_ticker, timestamp, model_prob, market_prob, edge,
       octagon_report_id, drivers_json, sources_json, catalysts_json, cache_hit, cache_miss, confidence)
    VALUES
      ($ticker, $event_ticker, $timestamp, $model_prob, $market_prob, $edge,
       $octagon_report_id, $drivers_json, $sources_json, $catalysts_json, $cache_hit, $cache_miss, $confidence)
  `).run({
    $ticker: edge.ticker,
    $event_ticker: edge.event_ticker,
    $timestamp: edge.timestamp,
    $model_prob: edge.model_prob,
    $market_prob: edge.market_prob,
    $edge: edge.edge,
    $octagon_report_id: edge.octagon_report_id ?? null,
    $drivers_json: edge.drivers_json ?? null,
    $sources_json: edge.sources_json ?? null,
    $catalysts_json: edge.catalysts_json ?? null,
    $cache_hit: edge.cache_hit ?? 0,
    $cache_miss: edge.cache_miss ?? 0,
    $confidence: edge.confidence ?? null,
  });
}

export function getLatestEdge(db: Database, ticker: string): EdgeRow | null {
  return db.query(
    'SELECT * FROM edge_history WHERE ticker = $ticker ORDER BY timestamp DESC LIMIT 1'
  ).get({ $ticker: ticker }) as EdgeRow | null;
}

export function getEdgeHistory(db: Database, ticker: string, since: number): EdgeRow[] {
  return db.query(
    'SELECT * FROM edge_history WHERE ticker = $ticker AND timestamp >= $since ORDER BY timestamp ASC'
  ).all({ $ticker: ticker, $since: since }) as EdgeRow[];
}

/**
 * Returns the latest edge per ticker where confidence >= minConfidence.
 * Confidence levels: low < moderate < high < very_high
 */
export function getActionableEdges(db: Database, minConfidence: string): EdgeRow[] {
  const minRank = CONFIDENCE_RANK[minConfidence];
  if (minRank === undefined) return [];

  const allowedLevels = Object.entries(CONFIDENCE_RANK)
    .filter(([, rank]) => rank >= minRank)
    .map(([level]) => level);

  // Get the latest edge per ticker, then filter to only those with qualifying confidence.
  // This ensures we don't return stale high-confidence edges when a newer low-confidence one exists.
  const placeholders = allowedLevels.map(() => '?').join(', ');
  return db.query(`
    SELECT e.* FROM edge_history e
    INNER JOIN (
      SELECT ticker, MAX(timestamp) as max_ts
      FROM edge_history
      GROUP BY ticker
    ) latest ON e.ticker = latest.ticker AND e.timestamp = latest.max_ts
    WHERE e.confidence IN (${placeholders})
    ORDER BY e.timestamp DESC
  `).all(...allowedLevels) as EdgeRow[];
}

/**
 * Returns the latest edge per ticker where confidence is exactly the given level.
 */
export function getEdgesByExactConfidence(db: Database, confidence: string): EdgeRow[] {
  return db.query(`
    SELECT e.* FROM edge_history e
    INNER JOIN (
      SELECT ticker, MAX(timestamp) as max_ts
      FROM edge_history
      GROUP BY ticker
    ) latest ON e.ticker = latest.ticker AND e.timestamp = latest.max_ts
    WHERE e.confidence = ?
    ORDER BY e.timestamp DESC
  `).all(confidence) as EdgeRow[];
}
