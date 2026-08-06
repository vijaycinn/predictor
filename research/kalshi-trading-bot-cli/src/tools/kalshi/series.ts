import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';

export const getSeries = new DynamicStructuredTool({
  name: 'get_series',
  description: 'Get details for a Kalshi series by series ticker.',
  schema: z.object({
    series_ticker: z.string().describe('Series ticker (e.g. KXBTC)'),
  }),
  func: async (input) => {
    const data = await callKalshiApi('GET', `/series/${input.series_ticker}`);
    return formatToolResult(data);
  },
});
