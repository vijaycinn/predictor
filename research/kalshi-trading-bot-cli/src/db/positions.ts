import type { Database } from 'bun:sqlite';
import type { EdgeRow } from './edge.js';

export interface Position {
  position_id: string;
  ticker: string;
  event_ticker: string;
  direction: string;
  size: number;
  entry_price: number;
  entry_edge?: number | null;
  entry_kelly?: number | null;
  current_pnl?: number | null;
  status?: string | null;
  opened_at?: number | null;
  closed_at?: number | null;
}

export interface PositionWithEdge extends Position {
  latest_edge?: EdgeRow | null;
}

export function openPosition(db: Database, position: Position): void {
  db.prepare(`
    INSERT INTO positions
      (position_id, ticker, event_ticker, direction, size, entry_price,
       entry_edge, entry_kelly, current_pnl, status, opened_at, closed_at)
    VALUES
      ($position_id, $ticker, $event_ticker, $direction, $size, $entry_price,
       $entry_edge, $entry_kelly, $current_pnl, $status, $opened_at, $closed_at)
  `).run({
    $position_id: position.position_id,
    $ticker: position.ticker,
    $event_ticker: position.event_ticker,
    $direction: position.direction,
    $size: position.size,
    $entry_price: position.entry_price,
    $entry_edge: position.entry_edge ?? null,
    $entry_kelly: position.entry_kelly ?? null,
    $current_pnl: position.current_pnl ?? 0,
    $status: position.status ?? 'open',
    $opened_at: position.opened_at ?? null,
    $closed_at: position.closed_at ?? null,
  });
}

export function closePosition(db: Database, positionId: string, closedAt: number): void {
  db.prepare(
    "UPDATE positions SET status = 'closed', closed_at = $closed_at WHERE position_id = $id"
  ).run({ $closed_at: closedAt, $id: positionId });
}

export function getOpenPositions(db: Database): Position[] {
  return db.query("SELECT * FROM positions WHERE status = 'open'").all() as Position[];
}

/**
 * Get a position with its latest edge_history row joined by ticker.
 */
export function getPositionWithEdge(db: Database, positionId: string): PositionWithEdge | null {
  const position = db.query('SELECT * FROM positions WHERE position_id = $id').get({
    $id: positionId,
  }) as Position | null;
  if (!position) return null;

  const latestEdge = db.query(
    'SELECT * FROM edge_history WHERE ticker = $ticker ORDER BY timestamp DESC LIMIT 1'
  ).get({ $ticker: position.ticker }) as EdgeRow | null;

  return { ...position, latest_edge: latestEdge ?? null };
}
