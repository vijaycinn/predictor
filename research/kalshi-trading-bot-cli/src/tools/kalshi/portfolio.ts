import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';

export const getBalance = new DynamicStructuredTool({
  name: 'get_balance',
  description: 'Get the current Kalshi account balance.',
  schema: z.object({}),
  func: async () => {
    const data = await callKalshiApi('GET', '/portfolio/balance');
    return formatToolResult(data);
  },
});

export const getPositions = new DynamicStructuredTool({
  name: 'get_positions',
  description: 'Get current open positions in Kalshi markets.',
  schema: z.object({
    event_ticker: z.string().optional().describe('Filter by event ticker'),
    ticker: z.string().optional().describe('Filter by market ticker'),
  }),
  func: async (input) => {
    const params: Record<string, string | undefined> = {};
    if (input.event_ticker) params.event_ticker = input.event_ticker;
    if (input.ticker) params.ticker = input.ticker;
    const data = await callKalshiApi('GET', '/portfolio/positions', { params });
    return formatToolResult(data);
  },
});

export const getFills = new DynamicStructuredTool({
  name: 'get_fills',
  description: 'Get trade fills (executed orders) from the portfolio.',
  schema: z.object({
    ticker: z.string().optional().describe('Filter by market ticker'),
    order_id: z.string().optional().describe('Filter by order ID'),
    min_ts: z.number().optional().describe('Min timestamp (Unix seconds)'),
    max_ts: z.number().optional().describe('Max timestamp (Unix seconds)'),
    limit: z.number().optional().describe('Max fills to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.ticker) params.ticker = input.ticker;
    if (input.order_id) params.order_id = input.order_id;
    if (input.min_ts) params.min_ts = input.min_ts;
    if (input.max_ts) params.max_ts = input.max_ts;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/portfolio/fills', { params });
    return formatToolResult(data);
  },
});

export const getSettlements = new DynamicStructuredTool({
  name: 'get_settlements',
  description: 'Get settlement history for resolved markets.',
  schema: z.object({
    ticker: z.string().optional().describe('Filter by market ticker'),
    limit: z.number().optional().describe('Max settlements to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.ticker) params.ticker = input.ticker;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/portfolio/settlements', { params });
    return formatToolResult(data);
  },
});

export const getOrders = new DynamicStructuredTool({
  name: 'get_orders',
  description: 'Get orders from the portfolio.',
  schema: z.object({
    ticker: z.string().optional().describe('Filter by market ticker'),
    event_ticker: z.string().optional().describe('Filter by event ticker'),
    status: z.enum(['resting', 'canceled', 'executed', 'all']).optional().describe('Order status filter'),
    limit: z.number().optional().describe('Max orders to return'),
  }),
  func: async (input) => {
    const params: Record<string, string | number | undefined> = {};
    if (input.ticker) params.ticker = input.ticker;
    if (input.event_ticker) params.event_ticker = input.event_ticker;
    if (input.status) params.status = input.status;
    if (input.limit) params.limit = input.limit;
    const data = await callKalshiApi('GET', '/portfolio/orders', { params });
    return formatToolResult(data);
  },
});

export const getOrder = new DynamicStructuredTool({
  name: 'get_order',
  description: 'Get details for a specific order by order ID.',
  schema: z.object({
    order_id: z.string().describe('Order ID'),
  }),
  func: async (input) => {
    const data = await callKalshiApi('GET', `/portfolio/orders/${input.order_id}`);
    return formatToolResult(data);
  },
});
