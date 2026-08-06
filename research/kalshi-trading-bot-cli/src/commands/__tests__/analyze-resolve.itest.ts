/**
 * Integration test: verify that resolveMarket resolves event and series tickers to markets.
 */
import { describe, test, expect } from 'bun:test';
import { resolveMarket } from '../analyze.js';

describe('resolveMarket ticker resolution', () => {
  test('resolves a series ticker (e.g. KXSENATETXR) to a market', async () => {
    const market = await resolveMarket('KXSENATETXR');
    expect(market.ticker).toBeTruthy();
    expect(market.event_ticker).toBeTruthy();
  }, 60_000);

  test('resolves an event ticker to a market', async () => {
    const market = await resolveMarket('KXSENATETXR-26');
    expect(market.ticker).toBeTruthy();
    expect(market.event_ticker).toBeTruthy();
  }, 60_000);
});
