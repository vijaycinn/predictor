import type { Database } from 'bun:sqlite';

export interface Event {
  ticker: string;
  category?: string | null;
  expiry?: number | null;
  vol_24h?: number | null;
  theme_id?: string | null;
  active?: number | null;
  updated_at?: number | null;
}

export function upsertEvent(db: Database, event: Event): void {
  db.prepare(`
    INSERT OR REPLACE INTO events (ticker, category, expiry, vol_24h, theme_id, active, updated_at)
    VALUES ($ticker, $category, $expiry, $vol_24h, $theme_id, $active, $updated_at)
  `).run({
    $ticker: event.ticker,
    $category: event.category ?? null,
    $expiry: event.expiry ?? null,
    $vol_24h: event.vol_24h ?? null,
    $theme_id: event.theme_id ?? null,
    $active: event.active ?? 1,
    $updated_at: event.updated_at ?? null,
  });
}

export function getActiveEvents(db: Database): Event[] {
  return db.query('SELECT * FROM events WHERE active = 1').all() as Event[];
}

export function getEvent(db: Database, ticker: string): Event | null {
  return db.query('SELECT * FROM events WHERE ticker = $ticker').get({ $ticker: ticker }) as Event | null;
}

export function deactivateExpired(db: Database, cutoffTimestamp: number): number {
  const result = db.prepare(
    'UPDATE events SET active = 0 WHERE expiry < $cutoff AND active = 1'
  ).run({ $cutoff: cutoffTimestamp });
  return result.changes;
}
