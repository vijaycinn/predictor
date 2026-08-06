import { describe, test, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { createDb } from '../../db/index.js';
import { computeBrier, recordSettlement, getCategoryAccuracy } from '../brier.js';
import { computePerformance } from '../performance.js';
import { insertEdge } from '../../db/edge.js';

let db: Database;

beforeEach(() => {
  db = createDb(':memory:');
});

describe('computeBrier', () => {
  test('correct confident prediction has low score', () => {
    expect(computeBrier(0.8, 1)).toBeCloseTo(0.04);
  });

  test('wrong confident prediction has high score', () => {
    expect(computeBrier(0.8, 0)).toBeCloseTo(0.64);
  });

  test('perfect prediction scores zero', () => {
    expect(computeBrier(1.0, 1)).toBe(0);
  });

  test('maximally wrong prediction scores one', () => {
    expect(computeBrier(0.0, 1)).toBe(1);
  });
});

describe('recordSettlement', () => {
  test('inserts brier_scores row from edge_history', () => {
    insertEdge(db, {
      ticker: 'ABC-YES',
      event_ticker: 'POLITICS-2024-PRES',
      timestamp: Date.now(),
      model_prob: 0.7,
      market_prob: 0.5,
      edge: 0.2,
    });

    const result = recordSettlement('ABC-YES', 1, db);

    expect(result.brierScore).toBeCloseTo(0.09); // (0.7 - 1)^2

    const row = db.query('SELECT * FROM brier_scores WHERE ticker = $t')
      .get({ $t: 'ABC-YES' }) as { brier_score: number; category: string; actual_outcome: number };

    expect(row).toBeTruthy();
    expect(row.brier_score).toBeCloseTo(0.09);
    expect(row.category).toBe('POLITICS');
    expect(row.actual_outcome).toBe(1);
  });

  test('throws if no edge_history exists', () => {
    expect(() => recordSettlement('NONEXISTENT', 0, db)).toThrow(
      'No edge_history found for ticker: NONEXISTENT',
    );
  });
});

describe('getCategoryAccuracy', () => {
  test('computes correct averages across settlements', () => {
    // Insert 5 settlements for category A (good predictions)
    for (let i = 0; i < 5; i++) {
      const ticker = `T${i}-YES`;
      insertEdge(db, {
        ticker,
        event_ticker: `CATA-EVENT-${i}`,
        timestamp: Date.now() + i,
        model_prob: 0.9,
        market_prob: 0.5,
        edge: 0.4,
      });
      recordSettlement(ticker, 1, db);
    }

    // Insert 5 settlements for category B (poor predictions)
    for (let i = 0; i < 5; i++) {
      const ticker = `U${i}-YES`;
      insertEdge(db, {
        ticker,
        event_ticker: `CATB-EVENT-${i}`,
        timestamp: Date.now() + 100 + i,
        model_prob: 0.8,
        market_prob: 0.5,
        edge: 0.3,
      });
      recordSettlement(ticker, 0, db);
    }

    const catA = getCategoryAccuracy('CATA', db);
    expect(catA.count).toBe(5);
    expect(catA.avgBrier).toBeCloseTo(0.01); // (0.9-1)^2 = 0.01
    expect(catA.isUnderperforming).toBe(false);

    const catB = getCategoryAccuracy('CATB', db);
    expect(catB.count).toBe(5);
    expect(catB.avgBrier).toBeCloseTo(0.64); // (0.8-0)^2 = 0.64
    expect(catB.isUnderperforming).toBe(true);
  });
});

describe('underperforming flag', () => {
  test('triggers at Brier > 0.30', () => {
    // Model says 0.6, outcome 0 => brier = 0.36 > 0.30
    insertEdge(db, {
      ticker: 'BAD-YES',
      event_ticker: 'BADCAT-EVENT-1',
      timestamp: Date.now(),
      model_prob: 0.6,
      market_prob: 0.5,
      edge: 0.1,
    });

    const result = recordSettlement('BAD-YES', 0, db);
    expect(result.brierScore).toBeCloseTo(0.36);
    expect(result.isUnderperforming).toBe(true);
  });

  test('does not trigger at Brier <= 0.30', () => {
    insertEdge(db, {
      ticker: 'GOOD-YES',
      event_ticker: 'GOODCAT-EVENT-1',
      timestamp: Date.now(),
      model_prob: 0.8,
      market_prob: 0.5,
      edge: 0.3,
    });

    const result = recordSettlement('GOOD-YES', 1, db);
    expect(result.brierScore).toBeCloseTo(0.04);
    expect(result.isUnderperforming).toBe(false);
  });
});

describe('computePerformance', () => {
  test('returns all fields with brier_scores data', () => {
    // Set up closed positions
    db.prepare(`
      INSERT INTO positions (position_id, ticker, event_ticker, direction, size, entry_price, current_pnl, status, closed_at)
      VALUES ($id, $ticker, $et, 'yes', 10, 50, $pnl, 'closed', $at)
    `).run({ $id: 'p1', $ticker: 'T1-YES', $et: 'SPORTS-GAME-1', $pnl: 20, $at: Date.now() });

    db.prepare(`
      INSERT INTO positions (position_id, ticker, event_ticker, direction, size, entry_price, current_pnl, status, closed_at)
      VALUES ($id, $ticker, $et, 'yes', 10, 50, $pnl, 'closed', $at)
    `).run({ $id: 'p2', $ticker: 'T2-YES', $et: 'SPORTS-GAME-2', $pnl: -15, $at: Date.now() });

    // Risk snapshots for Sharpe
    db.prepare('INSERT INTO risk_snapshots (timestamp, daily_pnl) VALUES ($ts, $pnl)')
      .run({ $ts: 1000, $pnl: 10 });
    db.prepare('INSERT INTO risk_snapshots (timestamp, daily_pnl) VALUES ($ts, $pnl)')
      .run({ $ts: 2000, $pnl: -5 });
    db.prepare('INSERT INTO risk_snapshots (timestamp, daily_pnl) VALUES ($ts, $pnl)')
      .run({ $ts: 3000, $pnl: 8 });

    // Brier scores
    db.prepare(`
      INSERT INTO brier_scores (ticker, event_ticker, category, model_prob, actual_outcome, brier_score, settled_at)
      VALUES ('T1-YES', 'SPORTS-GAME-1', 'SPORTS', 0.8, 1, 0.04, ${Date.now()})
    `).run();
    db.prepare(`
      INSERT INTO brier_scores (ticker, event_ticker, category, model_prob, actual_outcome, brier_score, settled_at)
      VALUES ('T2-YES', 'SPORTS-GAME-2', 'SPORTS', 0.7, 0, 0.49, ${Date.now()})
    `).run();

    const perf = computePerformance(db);

    expect(perf.winRate).toBeCloseTo(0.5);
    expect(perf.totalPnl).toBe(5); // 20 + (-15)
    expect(perf.sharpeRatio).not.toBeNull();
    expect(perf.brierByCategory['SPORTS']).toBeDefined();
    expect(perf.brierByCategory['SPORTS']).toBeCloseTo(0.265, 2); // avg(0.04, 0.49)
    expect(perf.pnlByCategory['SPORTS']).toBe(5);
    expect(perf.underperformingCategories).toEqual([]); // 0.265 < 0.30
  });

  test('flags underperforming categories', () => {
    // Brier scores with avg > 0.30
    db.prepare(`
      INSERT INTO brier_scores (ticker, event_ticker, category, model_prob, actual_outcome, brier_score, settled_at)
      VALUES ('X1', 'BAD-E1', 'BAD', 0.6, 0, 0.36, ${Date.now()})
    `).run();
    db.prepare(`
      INSERT INTO brier_scores (ticker, event_ticker, category, model_prob, actual_outcome, brier_score, settled_at)
      VALUES ('X2', 'BAD-E2', 'BAD', 0.7, 0, 0.49, ${Date.now()})
    `).run();

    const perf = computePerformance(db);
    expect(perf.underperformingCategories).toContain('BAD');
  });
});
