import { describe, test, expect, afterEach } from 'bun:test';
import { join } from 'path';
import { tmpdir } from 'os';
import { unlinkSync, existsSync, readFileSync } from 'fs';
import { AuditTrail } from '../trail.js';
import { readAuditLog } from '../reader.js';
import type { AuditEvent } from '../types.js';

function tmpFile(): string {
  return join(tmpdir(), `audit-test-${Date.now()}-${Math.random().toString(36).slice(2)}.jsonl`);
}

let cleanupPaths: string[] = [];

afterEach(() => {
  for (const p of cleanupPaths) {
    if (existsSync(p)) unlinkSync(p);
  }
  cleanupPaths = [];
});

describe('AuditTrail', () => {
  test('logs 5 different event types and reads them back', () => {
    const path = tmpFile();
    cleanupPaths.push(path);
    const trail = new AuditTrail(path);

    trail.log({ type: 'SCAN_START', theme: 'crypto', events_count: 10 });
    trail.log({ type: 'OCTAGON_CALL', ticker: 'KXBTC-26MAR', variant: 'base', cache_hit: false, credits_used: 1 });
    trail.log({ type: 'EDGE_DETECTED', ticker: 'KXBTC-26MAR', model_prob: 0.65, market_prob: 0.5, edge: 0.15, confidence: 'high', drivers: ['momentum'] });
    trail.log({ type: 'TRADE_EXECUTED', ticker: 'KXBTC-26MAR', order_id: 'ord-123', fill_price: 0.55, size: 100 });
    trail.log({ type: 'ALERT_SENT', alert_id: 'alert-1', channels: ['slack', 'email'] });
    trail.close();

    const events = readAuditLog({ filePath: path });
    expect(events).toHaveLength(5);
    expect(events.map((e) => e.type)).toEqual([
      'SCAN_START',
      'OCTAGON_CALL',
      'EDGE_DETECTED',
      'TRADE_EXECUTED',
      'ALERT_SENT',
    ]);
  });

  test('filters by type', () => {
    const path = tmpFile();
    cleanupPaths.push(path);
    const trail = new AuditTrail(path);

    trail.log({ type: 'SCAN_START', theme: 'crypto', events_count: 5 });
    trail.log({ type: 'OCTAGON_CALL', ticker: 'KXBTC-26MAR', variant: 'base', cache_hit: false, credits_used: 1 });
    trail.log({ type: 'OCTAGON_CALL', ticker: 'KXETH-26MAR', variant: 'bull', cache_hit: true, credits_used: 0 });
    trail.log({ type: 'EDGE_DETECTED', ticker: 'KXBTC-26MAR', model_prob: 0.7, market_prob: 0.5, edge: 0.2, confidence: 'very_high', drivers: ['vol'] });
    trail.close();

    const octagonEvents = readAuditLog({ filePath: path, type: 'OCTAGON_CALL' });
    expect(octagonEvents).toHaveLength(2);
    expect(octagonEvents.every((e) => e.type === 'OCTAGON_CALL')).toBe(true);
  });

  test('filters by ticker', () => {
    const path = tmpFile();
    cleanupPaths.push(path);
    const trail = new AuditTrail(path);

    trail.log({ type: 'OCTAGON_CALL', ticker: 'KXBTC-26MAR', variant: 'base', cache_hit: false, credits_used: 1 });
    trail.log({ type: 'OCTAGON_CALL', ticker: 'KXETH-26MAR', variant: 'bull', cache_hit: true, credits_used: 0 });
    trail.log({ type: 'SCAN_START', theme: 'crypto', events_count: 3 });
    trail.log({ type: 'TRADE_EXECUTED', ticker: 'KXBTC-26MAR', order_id: 'ord-456', fill_price: 0.6, size: 50 });
    trail.close();

    const btcEvents = readAuditLog({ filePath: path, ticker: 'KXBTC-26MAR' });
    expect(btcEvents).toHaveLength(2);
    expect(btcEvents.every((e) => 'ticker' in e && (e as any).ticker === 'KXBTC-26MAR')).toBe(true);
  });

  test('each line is valid independent JSON', () => {
    const path = tmpFile();
    cleanupPaths.push(path);
    const trail = new AuditTrail(path);

    trail.log({ type: 'SCAN_START', theme: 'politics', events_count: 20 });
    trail.log({ type: 'RECOMMENDATION', ticker: 'KXPRES', action: 'BUY_YES', size: 200, kelly: 0.12, risk_gate: 'PASS' });
    trail.log({ type: 'WATCHDOG_CHECK', ticker: 'KXPRES', entry_edge: 0.15, current_edge: 0.08, status: 'HOLD' });
    trail.close();

    const content = readFileSync(path, 'utf-8');
    const lines = content.split('\n').filter((l) => l.length > 0);
    expect(lines).toHaveLength(3);

    for (const line of lines) {
      const parsed = JSON.parse(line);
      expect(parsed.ts).toBeDefined();
      expect(parsed.type).toBeDefined();
    }
  });

  test('returns empty array for non-existent file', () => {
    const events = readAuditLog({ filePath: '/tmp/does-not-exist.jsonl' });
    expect(events).toEqual([]);
  });
});
