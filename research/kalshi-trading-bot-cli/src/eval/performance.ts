import type { Database } from 'bun:sqlite';

export interface PerformanceStats {
  sharpeRatio: number | null;
  winRate: number | null;
  totalPnl: number;
  brierByCategory: Record<string, number>;
  pnlByCategory: Record<string, number>;
  underperformingCategories: string[];
}

export function computePerformance(db: Database): PerformanceStats {
  // Closed positions for win rate / P&L
  const closedPositions = db.query(
    "SELECT * FROM positions WHERE status = 'closed'",
  ).all() as Array<{ current_pnl: number | null; event_ticker: string }>;

  const wins = closedPositions.filter((p) => (p.current_pnl ?? 0) > 0).length;
  const winRate = closedPositions.length > 0 ? wins / closedPositions.length : null;
  const totalPnl = closedPositions.reduce((sum, p) => sum + (p.current_pnl ?? 0), 0);

  // P&L by category
  const pnlByCategory: Record<string, number> = {};
  for (const p of closedPositions) {
    const cat = p.event_ticker.split('-')[0] ?? 'unknown';
    pnlByCategory[cat] = (pnlByCategory[cat] ?? 0) + (p.current_pnl ?? 0);
  }

  // Sharpe from risk snapshots
  const snapshots = db.query(
    'SELECT daily_pnl FROM risk_snapshots WHERE daily_pnl IS NOT NULL ORDER BY timestamp ASC',
  ).all() as Array<{ daily_pnl: number }>;

  let sharpeRatio: number | null = null;
  if (snapshots.length >= 2) {
    const pnls = snapshots.map((s) => s.daily_pnl);
    const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length;
    const variance = pnls.reduce((sum, p) => sum + (p - mean) ** 2, 0) / pnls.length;
    const std = Math.sqrt(variance);
    if (std > 0) {
      sharpeRatio = (mean / std) * Math.sqrt(252); // annualized
    }
  }

  // Brier scores by category — prefer brier_scores table, fall back to edge_history proxy
  const brierByCategory: Record<string, number> = {};
  const underperformingCategories: string[] = [];

  const brierRows = db.query(
    'SELECT category, AVG(brier_score) as avg_brier FROM brier_scores GROUP BY category',
  ).all() as Array<{ category: string; avg_brier: number }>;

  if (brierRows.length > 0) {
    for (const row of brierRows) {
      brierByCategory[row.category] = Math.round(row.avg_brier * 1000) / 1000;
      if (row.avg_brier > 0.30) {
        underperformingCategories.push(row.category);
      }
    }
  } else {
    // Fallback: derive from edge_history + positions (P&L proxy)
    const resolvedEdges = db.query(`
      SELECT eh.model_prob, eh.event_ticker, p.current_pnl
      FROM edge_history eh
      JOIN positions p ON eh.ticker = p.ticker
      WHERE p.status = 'closed'
    `).all() as Array<{ model_prob: number; event_ticker: string; current_pnl: number }>;

    const catGroups: Record<string, Array<{ modelProb: number; outcome: number }>> = {};
    for (const row of resolvedEdges) {
      const cat = row.event_ticker.split('-')[0] ?? 'unknown';
      if (!catGroups[cat]) catGroups[cat] = [];
      const outcome = (row.current_pnl ?? 0) > 0 ? 1 : 0;
      catGroups[cat].push({ modelProb: row.model_prob, outcome });
    }

    for (const [cat, entries] of Object.entries(catGroups)) {
      const brier = entries.reduce((sum, e) => sum + (e.modelProb - e.outcome) ** 2, 0) / entries.length;
      brierByCategory[cat] = Math.round(brier * 1000) / 1000;
      if (brier > 0.30) {
        underperformingCategories.push(cat);
      }
    }
  }

  return { sharpeRatio, winRate, totalPnl, brierByCategory, pnlByCategory, underperformingCategories };
}
