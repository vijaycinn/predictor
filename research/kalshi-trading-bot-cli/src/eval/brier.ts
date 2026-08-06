import type { Database } from 'bun:sqlite';
import { auditTrail } from '../audit/index.js';

/**
 * Pure Brier score: (forecast - outcome)²
 */
export function computeBrier(modelProb: number, actualOutcome: 0 | 1): number {
  return (modelProb - actualOutcome) ** 2;
}

export interface SettlementResult {
  brierScore: number;
  isUnderperforming: boolean;
}

/**
 * Record a market settlement: compute Brier score from the latest edge_history
 * row for the ticker, persist to brier_scores, and flag underperforming categories.
 */
export function recordSettlement(
  ticker: string,
  actualOutcome: 0 | 1,
  db: Database,
): SettlementResult {
  const edge = db.query(
    'SELECT * FROM edge_history WHERE ticker = $ticker ORDER BY timestamp DESC LIMIT 1',
  ).get({ $ticker: ticker }) as {
    event_ticker: string;
    model_prob: number;
  } | null;

  if (!edge) {
    throw new Error(`No edge_history found for ticker: ${ticker}`);
  }

  const eventTicker = edge.event_ticker;
  const category = eventTicker.split('-')[0] ?? 'unknown';
  const brierScore = computeBrier(edge.model_prob, actualOutcome);

  db.prepare(`
    INSERT INTO brier_scores (ticker, event_ticker, category, model_prob, actual_outcome, brier_score, settled_at)
    VALUES ($ticker, $event_ticker, $category, $model_prob, $actual_outcome, $brier_score, $settled_at)
  `).run({
    $ticker: ticker,
    $event_ticker: eventTicker,
    $category: category,
    $model_prob: edge.model_prob,
    $actual_outcome: actualOutcome,
    $brier_score: brierScore,
    $settled_at: Date.now(),
  });

  const accuracy = getCategoryAccuracy(category, db);

  if (accuracy.isUnderperforming) {
    auditTrail.log({
      type: 'CONFIG_CHANGE',
      category,
      avg_brier: accuracy.avgBrier,
      trigger: 'auto_calibration',
      recommendation: `Category "${category}" avg Brier ${accuracy.avgBrier.toFixed(3)} > 0.30 threshold — review model inputs`,
    });
  }

  return { brierScore, isUnderperforming: accuracy.isUnderperforming };
}

export interface CategoryAccuracy {
  avgBrier: number;
  count: number;
  isUnderperforming: boolean;
}

/**
 * Aggregate Brier score stats for a category.
 */
export function getCategoryAccuracy(category: string, db: Database): CategoryAccuracy {
  const row = db.query(
    'SELECT AVG(brier_score) as avg_brier, COUNT(*) as count FROM brier_scores WHERE category = $category',
  ).get({ $category: category }) as { avg_brier: number | null; count: number };

  const avgBrier = row.avg_brier ?? 0;
  const count = row.count;

  return {
    avgBrier,
    count,
    isUnderperforming: avgBrier > 0.30,
  };
}
