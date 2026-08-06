import { describe, test, expect } from 'bun:test';
import { normalizeKalshiInput } from '../analyze.js';

describe('normalizeKalshiInput', () => {
  test('passes through uppercase ticker unchanged', () => {
    expect(normalizeKalshiInput('KXMEASLES-26')).toBe('KXMEASLES-26');
    expect(normalizeKalshiInput('KXBTCD-26DEC31-T100000')).toBe('KXBTCD-26DEC31-T100000');
  });

  test('uppercases lowercase / mixed-case input', () => {
    // Kalshi's REST API is case-sensitive on the path: /markets/kxmeasles-26
    // 404s even though the ticker exists. We always uppercase.
    expect(normalizeKalshiInput('kxmeasles-26')).toBe('KXMEASLES-26');
    expect(normalizeKalshiInput('KxMeAsLeS-26')).toBe('KXMEASLES-26');
    expect(normalizeKalshiInput('  kxbtc-26apr  ')).toBe('KXBTC-26APR');
  });

  test('extracts ticker from full Kalshi URL', () => {
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/kxmeasles/measles-cases/kxmeasles-26'),
    ).toBe('KXMEASLES-26');
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/KXBTCD-26DEC31-T100000'),
    ).toBe('KXBTCD-26DEC31-T100000');
  });

  test('extracts ticker from URL without protocol', () => {
    expect(
      normalizeKalshiInput('kalshi.com/markets/kxmeasles/measles-cases/kxmeasles-26'),
    ).toBe('KXMEASLES-26');
    expect(
      normalizeKalshiInput('www.kalshi.com/markets/kxmeasles-26'),
    ).toBe('KXMEASLES-26');
  });

  test('strips query string and fragment', () => {
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/kxmeasles-26?ref=share'),
    ).toBe('KXMEASLES-26');
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/kxmeasles-26#yes'),
    ).toBe('KXMEASLES-26');
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/kxmeasles-26/?ref=share#yes'),
    ).toBe('KXMEASLES-26');
  });

  test('strips trailing slash', () => {
    expect(normalizeKalshiInput('https://kalshi.com/markets/kxmeasles-26/')).toBe('KXMEASLES-26');
    expect(normalizeKalshiInput('https://kalshi.com/markets/kxmeasles-26//')).toBe('KXMEASLES-26');
  });

  test('handles series-only URL (no event)', () => {
    // https://kalshi.com/markets/kxmeasles → last segment is the series ticker.
    // Falls through to the series branch of resolveMarket.
    expect(normalizeKalshiInput('https://kalshi.com/markets/kxmeasles')).toBe('KXMEASLES');
  });

  test('handles URL that ends in a slug rather than a ticker', () => {
    // Best we can do — pull the last segment. resolveMarket then 404s and
    // emits the standard "could not find" error with the normalized input.
    expect(
      normalizeKalshiInput('https://kalshi.com/markets/kxmeasles/measles-cases/'),
    ).toBe('MEASLES-CASES');
  });

  test('empty / whitespace input is left as empty', () => {
    expect(normalizeKalshiInput('')).toBe('');
    expect(normalizeKalshiInput('   ')).toBe('');
  });
});
