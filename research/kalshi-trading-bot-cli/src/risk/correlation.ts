import type { Database } from 'bun:sqlite';

/**
 * Count open positions per event category by joining positions (status='open')
 * with events on event_ticker.
 */
export function getCorrelationByCategory(db: Database): Map<string, number> {
  const rows = db.query(`
    SELECT e.category, COUNT(*) as cnt
    FROM positions p
    JOIN events e ON p.event_ticker = e.ticker
    WHERE p.status = 'open' AND e.category IS NOT NULL
    GROUP BY e.category
  `).all() as Array<{ category: string; cnt: number }>;

  const map = new Map<string, number>();
  for (const row of rows) {
    map.set(row.category, row.cnt);
  }
  return map;
}

/**
 * Check if adding a position to the given event's category would exceed the limit.
 */
export function isCorrelated(
  eventTicker: string,
  db: Database,
  maxPerCategory = 3
): boolean {
  const event = db.query('SELECT category FROM events WHERE ticker = $ticker').get({
    $ticker: eventTicker,
  }) as { category: string | null } | null;

  if (!event?.category) return false;

  const counts = getCorrelationByCategory(db);
  const current = counts.get(event.category) ?? 0;
  return current >= maxPerCategory;
}
