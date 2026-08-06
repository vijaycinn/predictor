import { describe, test, expect } from 'bun:test';
import { parseArgs } from '../parse-args.js';

describe('backtest flags — --universe and --fees', () => {
  test('--universe api / local accepted', () => {
    const a = parseArgs(['backtest', '--universe', 'api']);
    expect(a.parseErrors).toEqual([]);
    expect(a.backtestUniverse).toBe('api');
    const b = parseArgs(['backtest', '--universe', 'local']);
    expect(b.parseErrors).toEqual([]);
    expect(b.backtestUniverse).toBe('local');
  });

  test('--universe rejects invalid values', () => {
    const a = parseArgs(['backtest', '--universe', 'cloud']);
    expect(a.parseErrors.length).toBe(1);
    expect(a.parseErrors[0]).toContain('Invalid --universe');
  });

  test('--fees none / taker / maker accepted', () => {
    for (const v of ['none', 'taker', 'maker'] as const) {
      const a = parseArgs(['backtest', '--fees', v]);
      expect(a.parseErrors).toEqual([]);
      expect(a.backtestFees).toBe(v);
    }
  });

  test('--fees rejects invalid values', () => {
    const a = parseArgs(['backtest', '--fees', 'platinum']);
    expect(a.parseErrors.length).toBe(1);
    expect(a.parseErrors[0]).toContain('Invalid --fees');
  });

  test('flags missing → undefined (default behavior unchanged)', () => {
    const a = parseArgs(['backtest']);
    expect(a.parseErrors).toEqual([]);
    expect(a.backtestUniverse).toBeUndefined();
    expect(a.backtestFees).toBeUndefined();
  });

  test('--universe at end of argv → error mentions required value, not "undefined"', () => {
    const a = parseArgs(['backtest', '--universe']);
    expect(a.parseErrors.length).toBe(1);
    expect(a.parseErrors[0]).toContain('--universe requires a value');
    expect(a.parseErrors[0]).not.toContain('undefined');
    expect(a.backtestUniverse).toBeUndefined();
  });

  test('--fees at end of argv → error mentions required value, not "undefined"', () => {
    const a = parseArgs(['backtest', '--fees']);
    expect(a.parseErrors.length).toBe(1);
    expect(a.parseErrors[0]).toContain('--fees requires a value');
    expect(a.parseErrors[0]).not.toContain('undefined');
    expect(a.backtestFees).toBeUndefined();
  });
});
