import { DynamicStructuredTool } from '@langchain/core/tools';
import { z } from 'zod';
import { callKalshiApi } from './api.js';
import { formatToolResult } from '../types.js';
import { getDb } from '../../db/index.js';
import { searchEventIndex } from '../../db/event-index.js';
import { ensureIndex } from './search-index.js';

export const getEvents = new DynamicStructuredTool({
  name: 'get_events',
  description: 'Get Kalshi events, optionally filtered by status, series ticker, or title keyword search.',
  schema: z.object({
    status: z.enum(['open', 'closed', 'settled']).optional().describe('Event status filter'),
    series_ticker: z.string().optional().describe('Filter by series ticker'),
    title: z.string().optional().describe('Filter events by title keyword (case-insensitive substring match). Use short keywords like "tesla", "fed decision", "bitcoin"'),
    with_nested_markets: z.boolean().optional().describe('Include nested market data'),
    limit: z.number().optional().describe('Max events to return'),
  }),
  func: async (input) => {
    // Try local index first for title-based searches
    if (input.title) {
      try {
        await ensureIndex();
        const results = searchEventIndex(getDb(), input.title, input.limit ?? 50);
        if (results.length > 0) {
          // Reconstruct events in the same shape the API returns
          const events = results.map((r) => ({
            event_ticker: r.event_ticker,
            series_ticker: r.series_ticker,
            title: r.title,
            category: r.category,
            strike_date: r.strike_date,
            sub_title: r.sub_title,
            markets: r.markets_json ? JSON.parse(r.markets_json) : undefined,
          }));
          return formatToolResult({ events, cursor: null, _source: 'local_index' });
        }
      } catch {
        // Fall through to API on any index error
      }
    }

    const params: Record<string, string | number | boolean | undefined> = {};
    if (input.status) params.status = input.status;
    if (input.series_ticker) params.series_ticker = input.series_ticker;
    if (input.with_nested_markets !== undefined) params.with_nested_markets = input.with_nested_markets;
    if (input.limit) params.limit = input.limit ?? 200;

    const data = await callKalshiApi('GET', '/events', { params });

    // Client-side title filtering (Kalshi API doesn't support server-side title search)
    if (input.title && data && typeof data === 'object') {
      const d = data as Record<string, unknown>;
      const events = d.events as Array<Record<string, unknown>> | undefined;
      if (Array.isArray(events)) {
        const keywords = input.title.toLowerCase().split(/\s+/);
        d.events = events.filter((e) => {
          const title = String(e.title ?? '').toLowerCase();
          const ticker = String(e.event_ticker ?? '').toLowerCase();
          const category = String(e.category ?? '').toLowerCase();
          const text = `${title} ${ticker} ${category}`;
          return keywords.every((kw) => text.includes(kw));
        });
      }
    }

    return formatToolResult(data);
  },
});

export const getEvent = new DynamicStructuredTool({
  name: 'get_event',
  description: 'Get details for a specific Kalshi event by event ticker.',
  schema: z.object({
    event_ticker: z.string().describe('Event ticker (e.g. KXBTC-26MAR)'),
    with_nested_markets: z.boolean().optional().describe('Include nested market data'),
  }),
  func: async (input) => {
    const params: Record<string, boolean | undefined> = {};
    if (input.with_nested_markets !== undefined) params.with_nested_markets = input.with_nested_markets;
    const data = await callKalshiApi('GET', `/events/${input.event_ticker}`, { params });
    return formatToolResult(data);
  },
});
