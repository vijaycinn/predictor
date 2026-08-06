import { describe, test, expect } from 'bun:test';
import { clusterBootstrapCI, bootstrapCI, computeMetrics } from '../metrics.js';
import type { ScoredSignal } from '../types.js';

function signal(o: Partial<ScoredSignal>): ScoredSignal {
  return {
    event_ticker: 'KX-EVT',
    market_ticker: 'KX-EVT-A',
    series_category: 'Test',
    model_prob: 60,
    market_then: 50,
    market_now: 100,
    resolved: true,
    edge_pp: 10,
    pnl: 0.5,
    capital: 0.5,
    edge_bucket: '5-10%',
    confidence_score: 5,
    close_time: '2026-06-01T00:00:00Z',
    ...o,
  };
}

describe('clusterBootstrapCI', () => {
  test('returns [0, 0] for empty groups', () => {
    expect(clusterBootstrapCI([], () => 0.5)).toEqual([0, 0]);
  });

  test('equivalent to row bootstrap when each group has exactly one row', () => {
    const rows = [0, 1, 1, 0, 1, 0, 1, 1, 1, 0];
    const oneToOne = rows.map((_, i) => [i]);
    const mean = (s: number[]) => s.reduce((a, b) => a + b, 0) / s.length;
    // Compare distributions roughly — both should converge near the row mean
    const rowCI = bootstrapCI(rows, mean, 5000);
    const clusterCI = clusterBootstrapCI(oneToOne, (sample) => mean(sample.map((i) => rows[i])), 5000);
    // Both intervals should bracket the true mean (0.6)
    expect(rowCI[0]).toBeLessThan(0.7);
    expect(rowCI[1]).toBeGreaterThan(0.4);
    expect(clusterCI[0]).toBeLessThan(0.7);
    expect(clusterCI[1]).toBeGreaterThan(0.4);
  });

  test('cluster bootstrap CI is wider than row bootstrap when groups are perfectly correlated', () => {
    // Construct a perfectly-correlated dataset: 20 events, each with 5
    // contracts that all share the same outcome (all hit OR all miss).
    // The TRUE number of independent observations is 20, not 100. The
    // cluster bootstrap should produce a wider CI than the row bootstrap.
    const N_EVENTS = 20;
    const PER_EVENT = 5;
    const rows: number[] = [];
    const groups: number[][] = [];
    for (let e = 0; e < N_EVENTS; e++) {
      const outcome = e % 2 === 0 ? 1 : 0;        // alternating hits/misses → mean 0.5
      const grp: number[] = [];
      for (let c = 0; c < PER_EVENT; c++) {
        grp.push(rows.length);
        rows.push(outcome);
      }
      groups.push(grp);
    }
    const mean = (s: number[]) => s.reduce((a, b) => a + b, 0) / s.length;
    const rowCI = bootstrapCI(rows, mean, 5000);
    const clusterCI = clusterBootstrapCI(groups, (sample) => mean(sample.map((i) => rows[i])), 5000);
    const rowWidth = rowCI[1] - rowCI[0];
    const clusterWidth = clusterCI[1] - clusterCI[0];
    // Cluster CI must be substantially wider — the row bootstrap thinks N=100
    // when the honest N is 20.
    expect(clusterWidth).toBeGreaterThan(rowWidth * 1.5);
  });
});

describe('computeMetrics — uses event-clustered CIs', () => {
  test('hit-rate CI matches the cluster bootstrap on the same data (smoke test)', () => {
    // Two events, multi-contract; the hit-rate CI should now reflect
    // event-level resampling. Just verifies the wiring fires.
    const sigs: ScoredSignal[] = [
      signal({ event_ticker: 'EV-A', market_ticker: 'EV-A-1', edge_pp: -5, market_then: 30, market_now: 0, pnl: 0.3, capital: 0.7 }),
      signal({ event_ticker: 'EV-A', market_ticker: 'EV-A-2', edge_pp: -5, market_then: 25, market_now: 0, pnl: 0.25, capital: 0.75 }),
      signal({ event_ticker: 'EV-B', market_ticker: 'EV-B-1', edge_pp: -5, market_then: 40, market_now: 0, pnl: 0.4, capital: 0.6 }),
      signal({ event_ticker: 'EV-B', market_ticker: 'EV-B-2', edge_pp: -5, market_then: 35, market_now: 0, pnl: 0.35, capital: 0.65 }),
    ];
    const m = computeMetrics(sigs);
    // All four signals are hits → hit rate must be 1.0
    expect(m.edge_hit_rate).toBe(1);
    // CI upper bound should be 1 (cluster resampling can only see hits)
    expect(m.hit_rate_ci[1]).toBeCloseTo(1, 5);
  });
});
