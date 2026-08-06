import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';

export const getHistoricalMarkets = new DynamicStructuredTool({
  name: 'get_historical_markets',
  description: 'Get historical Kalshi markets data.',
  schema: z.object({
    series_ticker: z.string().optional().describe('Filter by series ticker'),
    event_ticker: z.string().optional().describe('Filter by event ticker'),
    status: z.enum(['open', 'closed', 'settled']).optional().describe('Market status filter'),
    limit: z.number().optional().describe('Max markets to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.series_ticker) params.series_ticker = input.series_ticker;
    if (input.event_ticker) params.event_ticker = input.event_ticker;
    if (input.status) params.status = input.status;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/historical/markets', { params });
    return formatToolResult(data);
  },
});

export const getHistoricalMarket = new DynamicStructuredTool({
  name: 'get_historical_market',
  description: 'Get historical data for a specific Kalshi market.',
  schema: z.object({
    ticker: z.string().describe('Market ticker'),
  }),
  func: async (input) => {
    const data = await callKalshiApi('GET', `/historical/markets/${input.ticker}`);
    return formatToolResult(data);
  },
});

export const getHistoricalCandlesticks = new DynamicStructuredTool({
  name: 'get_historical_candlesticks',
  description: 'Get historical candlestick data for a Kalshi market.',
  schema: z.object({
    ticker: z.string().describe('Market ticker'),
    start_ts: z.number().optional().describe('Start timestamp (Unix seconds)'),
    end_ts: z.number().optional().describe('End timestamp (Unix seconds)'),
    period_interval: z.number().optional().describe('Interval in minutes'),
  }),
  func: async (input) => {
    const now = Math.floor(Date.now() / 1000);
    const params: Record<string, number | undefined> = {
      start_ts: input.start_ts ?? now - 30 * 24 * 3600,
      end_ts: input.end_ts ?? now,
      period_interval: input.period_interval,
    };
    const data = await callKalshiApi('GET', `/historical/markets/${input.ticker}/candlesticks`, { params });
    return formatToolResult(data);
  },
});

export const getHistoricalFills = new DynamicStructuredTool({
  name: 'get_historical_fills',
  description: 'Get historical fill data.',
  schema: z.object({
    ticker: z.string().optional().describe('Filter by market ticker'),
    limit: z.number().optional().describe('Max fills to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.ticker) params.ticker = input.ticker;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/historical/fills', { params });
    return formatToolResult(data);
  },
});

export const getHistoricalOrders = new DynamicStructuredTool({
  name: 'get_historical_orders',
  description: 'Get historical order data.',
  schema: z.object({
    ticker: z.string().optional().describe('Filter by market ticker'),
    limit: z.number().optional().describe('Max orders to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.ticker) params.ticker = input.ticker;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/historical/orders', { params });
    return formatToolResult(data);
  },
});
