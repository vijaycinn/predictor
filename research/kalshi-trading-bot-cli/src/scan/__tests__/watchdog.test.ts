import { describe, test, expect, beforeEach } from 'bun:test';
import type { Database } from 'bun:sqlite';
import { createDb } from '../../db/index.js';
import { AuditTrail } from '../../audit/trail.js';
import { PositionWatchdog } from '../watchdog.js';
import { Alerter } from '../alerter.js';
import { openPosition } from '../../db/positions.js';
import { insertEdge } from '../../db/edge.js';
import { upsertEvent } from '../../db/events.js';
import { getPendingAlerts } from '../../db/alerts.js';
import { tmpdir } from 'os';
import { join } from 'path';

function makeAudit(): AuditTrail {
  return new AuditTrail(join(tmpdir(), `test-audit-${Date.now()}-${Math.random().toString(36).slice(2)}.jsonl`));
}

function insertPosition(db: Database, overrides: Record<string, unknown> = {}): void {
  openPosition(db, {
    position_id: (overrides.position_id as string) ?? 'pos-1',
    ticker: (overrides.ticker as string) ?? 'MKT-YES',
    event_ticker: (overrides.event_ticker as string) ?? 'EV-1',
    direction: (overrides.direction as string) ?? 'buy_yes',
    size: (overrides.size as number) ?? 10,
    entry_price: (overrides.entry_price as number) ?? 0.55,
    entry_edge: (overrides.entry_edge as number) ?? 0.10,
    status: 'open',
    opened_at: Math.floor(Date.now() / 1000),
  });
}

function insertEdgeRow(db: Database, overrides: Record<string, unknown> = {}): void {
  insertEdge(db, {
    ticker: (overrides.ticker as string) ?? 'MKT-YES',
    event_ticker: (overrides.event_ticker as string) ?? 'EV-1',
    timestamp: (overrides.timestamp as number) ?? Math.floor(Date.now() / 1000),
    model_prob: (overrides.model_prob as number) ?? 0.60,
    market_prob: (overrides.market_prob as number) ?? 0.55,
    edge: (overrides.edge as number) ?? 0.05,
    catalysts_json: (overrides.catalysts_json as string) ?? null,
  });
}

describe('PositionWatchdog', () => {
  let db: Database;
  let audit: AuditTrail;
  let watchdog: PositionWatchdog;

  beforeEach(() => {
    db = createDb(':memory:');
    audit = makeAudit();
    watchdog = new PositionWatchdog(audit);
  });

  test('detects CONVERGENCE when edge is near zero', () => {
    insertPosition(db, { entry_edge: 0.10 });
    insertEdgeRow(db, { edge: 0.01 });

    const alerts = watchdog.check(db);

    expect(alerts.length).toBeGreaterThanOrEqual(1);
    const convergence = alerts.find((a) => a.alertType === 'CONVERGENCE');
    expect(convergence).toBeDefined();
    expect(convergence!.ticker).toBe('MKT-YES');
    expect(convergence!.edge).toBe(0.01);
  });

  test('detects ADVERSE_MOVE when edge flips sign', () => {
    insertPosition(db, { entry_edge: 0.08, direction: 'buy_yes' });
    insertEdgeRow(db, { edge: -0.03 });

    const alerts = watchdog.check(db);

    const adverse = alerts.find((a) => a.alertType === 'ADVERSE_MOVE');
    expect(adverse).toBeDefined();
    expect(adverse!.entryEdge).toBe(0.08);
    expect(adverse!.edge).toBe(-0.03);
  });

  test('detects EXPIRY_APPROACHING when event expires within 24h', () => {
    const now = Math.floor(Date.now() / 1000);
    insertPosition(db);
    insertEdgeRow(db, { edge: 0.06 });
    upsertEvent(db, { ticker: 'EV-1', expiry: now + 20 * 3600, active: 1 });

    const alerts = watchdog.check(db, now);

    const expiry = alerts.find((a) => a.alertType === 'EXPIRY_APPROACHING');
    expect(expiry).toBeDefined();
    expect(expiry!.message).toContain('EV-1');
  });

  test('persists alerts through Alerter', async () => {
    insertPosition(db);
    insertEdgeRow(db, { edge: 0.01 });

    const alerts = watchdog.check(db);
    expect(alerts.length).toBeGreaterThan(0);

    const alerter = new Alerter(db, audit);
    for (const alert of alerts) {
      await alerter.emit({
        ticker: alert.ticker,
        alertType: alert.alertType,
        edge: alert.edge,
        message: alert.message,
        channels: ['terminal'],
      });
    }

    // Alerts should be marked as sent (not pending)
    const pending = getPendingAlerts(db);
    expect(pending).toHaveLength(0);

    // Verify alert was created by querying all alerts
    const allAlerts = db.query('SELECT * FROM alerts').all();
    expect(allAlerts.length).toBeGreaterThan(0);
  });

  test('returns no alerts for healthy position', () => {
    const now = Math.floor(Date.now() / 1000);
    insertPosition(db, { entry_edge: 0.08 });
    insertEdgeRow(db, { edge: 0.06 });
    // Event with far-off expiry
    upsertEvent(db, { ticker: 'EV-1', expiry: now + 30 * 24 * 3600, active: 1 });

    const alerts = watchdog.check(db, now);

    expect(alerts).toHaveLength(0);
  });
});
