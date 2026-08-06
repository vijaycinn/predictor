import type { Database } from 'bun:sqlite';

export interface Theme {
  theme_id: string;
  name: string;
  filter_query?: string | null;
  tickers?: string | null;
  last_resolved_at?: number | null;
}

export function upsertTheme(db: Database, theme: Theme): void {
  db.prepare(`
    INSERT OR REPLACE INTO themes (theme_id, name, filter_query, tickers, last_resolved_at)
    VALUES ($theme_id, $name, $filter_query, $tickers, $last_resolved_at)
  `).run({
    $theme_id: theme.theme_id,
    $name: theme.name,
    $filter_query: theme.filter_query ?? null,
    $tickers: theme.tickers ?? null,
    $last_resolved_at: theme.last_resolved_at ?? null,
  });
}

export function getActiveThemes(db: Database): Theme[] {
  return db.query('SELECT * FROM themes').all() as Theme[];
}

export function getThemeTickers(db: Database, themeId: string): string[] {
  const row = db.query('SELECT tickers FROM themes WHERE theme_id = $id').get({
    $id: themeId,
  }) as { tickers: string | null } | null;
  if (!row?.tickers) return [];
  return JSON.parse(row.tickers) as string[];
}
