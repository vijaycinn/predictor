import type { Database } from 'bun:sqlite';
import type { AuditTrail } from '../audit/trail.js';
import { callKalshiApi, fetchAllPages } from '../tools/kalshi/api.js';
import type { KalshiEvent, KalshiMarket, KalshiSeries } from '../tools/kalshi/types.js';
import { ensureIndex, getRefreshPromise } from '../tools/kalshi/search-index.js';
import { upsertEvent, deactivateExpired } from '../db/events.js';
import { getThemeTickers } from '../db/themes.js';

/** Maps lowercase theme IDs → exact Kalshi category labels */
export const CATEGORY_MAP: Record<string, string> = {
  'climate': 'Climate and Weather',
  'companies': 'Companies',
  'crypto': 'Crypto',
  'economics': 'Economics',
  'elections': 'Elections',
  'entertainment': 'Entertainment',
  'financials': 'Financials',
  'health': 'Health',
  'mentions': 'Mentions',
  'politics': 'Politics',
  'science': 'Science and Technology',
  'social': 'Social',
  'sports': 'Sports',
  'transportation': 'Transportation',
  'world': 'World',
};

/**
 * Fetch all series from Kalshi and build a map of category → sorted subcategory tags.
 * Each series has a `tags` field; we collect unique tags per category.
 */
export async function fetchSubcategories(): Promise<Record<string, string[]>> {
  const allSeries = await fetchAllPages<KalshiSeries>('/series', {}, 'series', 50);
  const catTags: Record<string, Set<string>> = {};

  for (const s of allSeries) {
    const cat = s.category;
    if (!cat) continue;
    if (!catTags[cat]) catTags[cat] = new Set();
    for (const tag of s.tags ?? []) {
      catTags[cat].add(tag);
    }
  }

  const result: Record<string, string[]> = {};
  for (const [cat, tags] of Object.entries(catTags)) {
    result[cat] = [...tags].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  }
  return result;
}

export class ThemeResolver {
  private db: Database;
  private audit: AuditTrail;

  constructor(db: Database, audit: AuditTrail) {
    this.db = db;
    this.audit = audit;
  }

  async resolve(themeName: string): Promise<string[]> {
    const now = Math.floor(Date.now() / 1000);
    let eventTickers: string[];

    if (themeName === 'top50') {
      eventTickers = await this.resolveTop50();
    } else if (themeName.includes(':')) {
      // Subcategory filter: "crypto:btc", "sports:football"
      eventTickers = await this.resolveSubcategory(themeName);
    } else if (CATEGORY_MAP[themeName]) {
      eventTickers = await this.resolveCategory(themeName);
    } else {
      eventTickers = getThemeTickers(this.db, themeName);
    }

    // Upsert resolved events
    for (const ticker of eventTickers) {
      upsertEvent(this.db, { ticker, active: 1, updated_at: now });
    }

    // Deactivate expired events
    deactivateExpired(this.db, now);

    // Audit log
    this.audit.log({
      type: 'SCAN_START',
      theme: themeName,
      events_count: eventTickers.length,
    });

    return eventTickers;
  }

  private async resolveTop50(): Promise<string[]> {
    const markets = await fetchAllPages<KalshiMarket>(
      '/markets',
      { status: 'open', limit: 200 },
      'markets',
      3
    );

    // Sort by volume_24h descending
    markets.sort((a, b) => (b.volume_24h ?? 0) - (a.volume_24h ?? 0));

    // Take top 50 unique event tickers
    const seen = new Set<string>();
    const result: string[] = [];
    for (const m of markets) {
      if (!seen.has(m.event_ticker)) {
        seen.add(m.event_ticker);
        result.push(m.event_ticker);
        if (result.length >= 50) break;
      }
    }
    return result;
  }

  private async resolveCategory(themeName: string): Promise<string[]> {
    const categoryLabel = CATEGORY_MAP[themeName];
    // Kalshi /events API does not support server-side category filtering,
    // so query the local SQLite index instead of fetching all open events
    await ensureIndex();
    // If ensureIndex kicked off a background refresh (first run / empty index),
    // await it so we don't query an unpopulated event_index table
    const pending = getRefreshPromise();
    if (pending) await pending;
    const rows = this.db.query(
      `SELECT event_ticker FROM event_index WHERE category = ?`,
    ).all(categoryLabel) as { event_ticker: string }[];
    return rows.map((r) => r.event_ticker);
  }

  private async resolveSubcategory(themeName: string): Promise<string[]> {
    const [catKey, ...subParts] = themeName.split(':');
    const subTag = subParts.join(':').toLowerCase();
    const categoryLabel = CATEGORY_MAP[catKey];
    if (!categoryLabel) return [];

    // Find series in this category with matching tag
    const allSeries = await fetchAllPages<KalshiSeries>('/series', { category: categoryLabel }, 'series', 50);
    const matchingSeries = new Set<string>();
    for (const s of allSeries) {
      if (s.category !== categoryLabel) continue;
      const hasTag = (s.tags ?? []).some((t) => {
        const tagLower = t.toLowerCase();
        const tagKebab = tagLower.replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        return tagLower === subTag || tagKebab === subTag;
      });
      if (hasTag) matchingSeries.add(s.ticker);
    }

    if (matchingSeries.size === 0) return [];

    // Fetch open events for matching series in parallel (server-side filtered)
    const results = await Promise.all(
      [...matchingSeries].map((seriesTicker) =>
        fetchAllPages<KalshiEvent>(
          '/events',
          { status: 'open', series_ticker: seriesTicker },
          'events',
          50
        )
      )
    );

    const seen = new Set<string>();
    const eventTickers: string[] = [];
    for (const events of results) {
      for (const e of events) {
        if (!seen.has(e.event_ticker)) {
          seen.add(e.event_ticker);
          eventTickers.push(e.event_ticker);
        }
      }
    }

    return eventTickers;
  }
}
