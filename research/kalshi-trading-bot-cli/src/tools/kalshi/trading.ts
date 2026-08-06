import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi, toDollarString } from './api.js';
import { formatToolResult } from '../types.js';

export const placeOrder = new DynamicStructuredTool({
  name: 'place_order',
  description: 'Place a new order on a Kalshi market.',
  schema: z.object({
    ticker: z.string().describe('Market ticker'),
    action: z.enum(['buy', 'sell']).describe('Buy or sell'),
    side: z.enum(['yes', 'no']).describe('Yes or No side'),
    type: z.enum(['limit', 'market']).describe('Order type'),
    count: z.number().int().positive().describe('Number of contracts'),
    yes_price: z.number().int().min(1).max(99).optional().describe('Price in cents (1-99) for limit orders'),
    expiration_ts: z.number().optional().describe('Order expiration Unix timestamp'),
    client_order_id: z.string().optional().describe('Optional client-provided order ID'),
  }),
  func: async (input) => {
    const body: Record<string, unknown> = {
      ticker: input.ticker,
      action: input.action,
      side: input.side,
      type: input.type,
      count: input.count,
    };
    if (input.yes_price !== undefined) {
      body.yes_price = input.yes_price;
      body.dollar_price = toDollarString(input.yes_price);
    }
    if (input.expiration_ts !== undefined) body.expiration_ts = input.expiration_ts;
    if (input.client_order_id) body.client_order_id = input.client_order_id;

    const data = await callKalshiApi('POST', '/portfolio/orders', { body });
    return formatToolResult(data);
  },
});

export const amendOrder = new DynamicStructuredTool({
  name: 'amend_order',
  description: 'Amend an existing resting order.',
  schema: z.object({
    order_id: z.string().describe('Order ID to amend'),
    count: z.number().int().positive().optional().describe('New contract count'),
    yes_price: z.number().int().min(1).max(99).optional().describe('New price in cents'),
    expiration_ts: z.number().optional().describe('New expiration timestamp'),
  }),
  func: async (input) => {
    const body: Record<string, unknown> = {};
    if (input.count !== undefined) body.count = input.count;
    if (input.yes_price !== undefined) {
      body.yes_price = input.yes_price;
      body.dollar_price = toDollarString(input.yes_price);
    }
    if (input.expiration_ts !== undefined) body.expiration_ts = input.expiration_ts;

    const data = await callKalshiApi('POST', `/portfolio/orders/${input.order_id}/amend`, { body });
    return formatToolResult(data);
  },
});

export const cancelOrder = new DynamicStructuredTool({
  name: 'cancel_order',
  description: 'Cancel an existing resting order.',
  schema: z.object({
    order_id: z.string().describe('Order ID to cancel'),
  }),
  func: async (input) => {
    const data = await callKalshiApi('DELETE', `/portfolio/orders/${input.order_id}`);
    return formatToolResult(data);
  },
});

export const cancelOrders = new DynamicStructuredTool({
  name: 'cancel_orders',
  description: 'Cancel multiple resting orders in batch.',
  schema: z.object({
    order_ids: z.array(z.string()).describe('List of order IDs to cancel'),
  }),
  func: async (input) => {
    const body = { order_ids: input.order_ids };
    const data = await callKalshiApi('DELETE', '/portfolio/orders/batched', { body });
    return formatToolResult(data);
  },
});

export const placeBatchOrders = new DynamicStructuredTool({
  name: 'place_batch_orders',
  description: 'Place multiple orders in a single batch request.',
  schema: z.object({
    orders: z
      .array(
        z.object({
          ticker: z.string(),
          action: z.enum(['buy', 'sell']),
          side: z.enum(['yes', 'no']),
          type: z.enum(['limit', 'market']),
          count: z.number().int().positive(),
          yes_price: z.number().int().min(1).max(99).optional(),
        })
      )
      .describe('List of orders to place'),
  }),
  func: async (input) => {
    const orders = input.orders.map((o) => {
      if (o.yes_price !== undefined) {
        return { ...o, dollar_price: toDollarString(o.yes_price) };
      }
      return o;
    });
    const body = { orders };
    const data = await callKalshiApi('POST', '/portfolio/orders/batched', { body });
    return formatToolResult(data);
  },
});
