import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';

export const getExchangeStatus = new DynamicStructuredTool({
  name: 'get_exchange_status',
  description: 'Get the current status of the Kalshi exchange (active/paused).',
  schema: z.object({}),
  func: async () => {
    const data = await callKalshiApi('GET', '/exchange/status');
    return formatToolResult(data);
  },
});

export const getExchangeSchedule = new DynamicStructuredTool({
  name: 'get_exchange_schedule',
  description: 'Get the Kalshi exchange trading schedule including maintenance windows.',
  schema: z.object({}),
  func: async () => {
    const data = await callKalshiApi('GET', '/exchange/schedule');
    return formatToolResult(data);
  },
});
