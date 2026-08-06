import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';

export const getMarkets = new DynamicStructuredTool({
  name: 'get_markets',
  description: 'Get a list of Kalshi markets, optionally filtered by event ticker, series ticker, status, or specific tickers.',
  schema: z.object({
    event_ticker: z.string().optional().describe('Filter by event ticker'),
    series_ticker: z.string().optional().describe('Filter by series ticker'),
    status: z.enum(['open', 'closed', 'settled']).optional().describe('Market status filter'),
    tickers: z.array(z.string()).optional().describe('Specific market tickers to fetch'),
    limit: z.number().optional().describe('Max markets to return (default 100)'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.event_ticker) params.event_ticker = input.event_ticker;
    if (input.series_ticker) params.series_ticker = input.series_ticker;
    if (input.status) params.status = input.status;
    if (input.tickers?.length) params.tickers = input.tickers.join(',');
    if (input.limit) params.limit = input.limit;

    const data = await callKalshiApi('GET', '/markets', { params });
    return formatToolResult(data);
  },
});

export const getMarket = new DynamicStructuredTool({
  name: 'get_market',
  description: 'Get details for a specific Kalshi market by ticker.',
  schema: z.object({
    ticker: z.string().describe('Market ticker (e.g. KXBTC-26MAR-B50000)'),
  }),
  func: async (input) => {
    const data = await callKalshiApi('GET', `/markets/${input.ticker}`);
    return formatToolResult(data);
  },
});

export const getMarketOrderbook = new DynamicStructuredTool({
  name: 'get_market_orderbook',
  description: 'Get the current orderbook for a Kalshi market.',
  schema: z.object({
    ticker: z.string().describe('Market ticker'),
    depth: z.number().optional().describe('Number of price levels to return'),
  }),
  func: async (input) => {
    const params: Record<string, number | undefined> = {};
    if (input.depth) params.depth = input.depth;
    const data = await callKalshiApi('GET', `/markets/${input.ticker}/orderbook`, { params });
    return formatToolResult(data);
  },
});

export const getMarketCandlesticks = new DynamicStructuredTool({
  name: 'get_market_candlesticks',
  description: 'Get candlestick price data for a Kalshi market.',
  schema: z.object({
    ticker: z.string().describe('Market ticker'),
    start_ts: z.number().optional().describe('Start timestamp (Unix seconds)'),
    end_ts: z.number().optional().describe('End timestamp (Unix seconds)'),
    period_interval: z.number().optional().describe('Candlestick interval in minutes (default 60)'),
  }),
  func: async (input) => {
    const now = Math.floor(Date.now() / 1000);
    const params: Record<string, string | number | undefined> = {
      market_tickers: input.ticker,
      start_ts: input.start_ts ?? now - 7 * 24 * 3600,
      end_ts: input.end_ts ?? now,
      period_interval: input.period_interval,
    };
    const data = await callKalshiApi('GET', '/markets/candlesticks', { params });
    return formatToolResult(data);
  },
});
