import { callKalshiApi } from '../tools/kalshi/api.js';

/**
 * Parse a market quote from API response, handling both cent and dollar-string fields.
 * Returns cents (1-99) or NaN if no valid quote found.
 */
function parseQuoteCents(market: Record<string, unknown>, field: 'yes_ask' | 'yes_bid' | 'no_ask' | 'no_bid'): number {
  // Try dollar-string fields first (new API: yes_ask_dollars, legacy: dollar_yes_ask)
  const dollarKey = `${field}_dollars`;      // e.g. yes_ask_dollars
  const legacyDollarKey = `dollar_${field}`;  // e.g. dollar_yes_ask

  const dollarStr = market[dollarKey] as string | undefined;
  const legacyStr = market[legacyDollarKey] as string | undefined;

  const d = dollarStr != null ? parseFloat(dollarStr) : legacyStr != null ? parseFloat(legacyStr) : NaN;
  if (Number.isFinite(d) && d > 0) return Math.round(d * 100);

  // Fall back to cent field
  const cents = Number(market[field] ?? 0);
  if (Number.isFinite(cents) && cents > 0) return cents;

  return NaN;
}

/**
 * Fetch the best available quote for a market order.
 * Returns cents for the appropriate side/action, or an error message.
 */
export async function fetchMarketQuote(
  ticker: string,
  action: 'buy' | 'sell',
  side: 'yes' | 'no' = 'yes',
): Promise<{ cents: number } | { error: string }> {
  const marketData = await callKalshiApi('GET', `/markets/${ticker}`) as Record<string, unknown>;
  const market = (marketData.market ?? marketData) as Record<string, unknown>;

  const field = side === 'no'
    ? (action === 'sell' ? 'no_bid' : 'no_ask')
    : (action === 'sell' ? 'yes_bid' : 'yes_ask');
  const cents = parseQuoteCents(market, field);

  if (!Number.isFinite(cents) || cents <= 0) {
    const label = action === 'sell' ? 'bid' : 'ask';
    return { error: `No ${label} available for ${ticker} — cannot place market order. Specify a price.` };
  }

  return { cents };
}
