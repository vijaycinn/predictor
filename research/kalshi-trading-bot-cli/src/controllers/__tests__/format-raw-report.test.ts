import { describe, expect, it } from 'bun:test';
import { formatRawReport } from '../browse';

describe('formatRawReport', () => {
  const ticker = 'KXBTC-26MAR-B80000';

  describe('JSON parsing path', () => {
    it('extracts fields from a full JSON report', () => {
      const raw = JSON.stringify({
        model_probability: 0.72,
        market_probability: 0.58,
        mispricing_signal: 'strong_buy',
        key_takeaway: 'Bitcoin ETF inflows accelerating',
        resolution_history: '3 of 5 similar markets resolved YES',
        drivers: [
          { impact: 'high', claim: 'ETF inflows' },
          { impact: 'medium', description: 'Macro tailwinds' },
        ],
        catalysts: [
          { date: '2026-03-28', event: 'Options expiry' },
        ],
        sources: [
          { title: 'Bloomberg', url: 'https://bloomberg.com/article' },
          { url: 'https://example.com' },
        ],
      });

      const result = formatRawReport(raw, ticker);

      expect(result).toContain(`── Octagon Report: ${ticker} ──`);
      expect(result).toContain('Model Probability: 0.72');
      expect(result).toContain('Market Probability: 0.58');
      expect(result).toContain('Signal: strong_buy');
      expect(result).toContain('Key Takeaway: Bitcoin ETF inflows accelerating');
      expect(result).toContain('Resolution History:');
      expect(result).toContain('3 of 5 similar markets resolved YES');
      expect(result).toContain('  • [high] ETF inflows');
      expect(result).toContain('  • [medium] Macro tailwinds');
      expect(result).toContain('  • 2026-03-28 — Options expiry');
      expect(result).toContain('  • Bloomberg: https://bloomberg.com/article');
      expect(result).toContain('  • https://example.com');
    });

    it('uses versions[0] when present', () => {
      const raw = JSON.stringify({
        versions: [
          { model_probability: 0.65, mispricing_signal: 'hold' },
        ],
      });

      const result = formatRawReport(raw, ticker);
      expect(result).toContain('Model Probability: 0.65');
      expect(result).toContain('Signal: hold');
    });

    it('falls back to pretty JSON when few fields are extracted', () => {
      const raw = JSON.stringify({ some_unknown_field: 'value' });
      const result = formatRawReport(raw, ticker);

      // Should contain pretty-printed JSON since only header + blank line are in lines (<=3)
      expect(result).toContain(`── Octagon Report: ${ticker} ──`);
      expect(result).toContain('"some_unknown_field": "value"');
    });

    it('handles outcome_probabilities_json as a string', () => {
      const raw = JSON.stringify({
        model_probability: 0.72,
        outcome_probabilities_json: JSON.stringify([
          { market_ticker: 'KXBTC-A', model_probability: 0.72 },
          { market_ticker: 'KXBTC-B', model_probability: 0.28 },
        ]),
      });

      const result = formatRawReport(raw, ticker);
      expect(result).toContain('Outcome Probabilities:');
      expect(result).toContain('  • KXBTC-A: 0.72');
      expect(result).toContain('  • KXBTC-B: 0.28');
    });

    it('handles outcome_probabilities_json as an array', () => {
      const raw = JSON.stringify({
        model_probability: 0.72,
        outcome_probabilities_json: [
          { market_ticker: 'KXBTC-A', model_probability: 0.72 },
        ],
      });

      const result = formatRawReport(raw, ticker);
      expect(result).toContain('  • KXBTC-A: 0.72');
    });

    it('handles drivers with missing fields gracefully', () => {
      const raw = JSON.stringify({
        model_probability: 0.5,
        drivers: [
          { impact: null, claim: null, description: null },
        ],
      });

      const result = formatRawReport(raw, ticker);
      expect(result).toContain('  • [?]');
    });
  });

  describe('non-JSON fallback path', () => {
    it('returns plain text with header', () => {
      const raw = '# Analysis\n\nBitcoin is trending up.';
      const result = formatRawReport(raw, ticker);

      expect(result).toContain(`── Octagon Report: ${ticker} ──`);
      expect(result).toContain('# Analysis');
      expect(result).toContain('Bitcoin is trending up.');
    });

    it('replaces relative /markets/ links with absolute URLs', () => {
      const raw = 'See report: /markets/KXBTC and also: /markets/KXETH for details';
      const result = formatRawReport(raw, ticker);

      expect(result).toContain('https://octagonai.co/markets/KXBTC');
      expect(result).toContain('https://octagonai.co/markets/KXETH');
    });

    it('strips a "Why This Matters (GEO)" section (h3)', () => {
      const raw = [
        '## Analysis',
        'Main content here.',
        '### Why This Matters (GEO)',
        'Some SEO boilerplate text.',
        'More boilerplate.',
        '## Next Section',
        'Preserved content.',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).toContain('Main content here.');
      expect(result).not.toContain('Why This Matters (GEO)');
      expect(result).not.toContain('Some SEO boilerplate text.');
      expect(result).toContain('## Next Section');
      expect(result).toContain('Preserved content.');
    });

    it('strips a "Why This Matters (GEO)" section (h2)', () => {
      const raw = [
        'Intro text.',
        '## Why This Matters (GEO)',
        'Boilerplate.',
        '## Another Section',
        'Kept.',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).toContain('Intro text.');
      expect(result).not.toContain('Why This Matters (GEO)');
      expect(result).not.toContain('Boilerplate.');
      expect(result).toContain('## Another Section');
    });

    it('strips "Why This Matters (GEO)" at end of document', () => {
      const raw = [
        'Content.',
        '### Why This Matters (GEO)',
        'Trailing boilerplate.',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).toContain('Content.');
      expect(result).not.toContain('Why This Matters (GEO)');
      expect(result).not.toContain('Trailing boilerplate.');
    });

    it('handles extra whitespace around "Why This Matters (GEO)"', () => {
      const raw = [
        'Content.',
        '###  Why This Matters  (GEO) ',
        'Boilerplate here.',
        '## Next',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).not.toContain('Why This Matters');
      expect(result).not.toContain('Boilerplate here.');
      expect(result).toContain('## Next');
    });

    it('strips all occurrences of "Why This Matters (GEO)"', () => {
      const raw = [
        '## Section A',
        '### Why This Matters (GEO)',
        'First boilerplate.',
        '## Section B',
        '### Why This Matters (GEO)',
        'Second boilerplate.',
        '## Section C',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).toContain('## Section A');
      expect(result).not.toContain('First boilerplate.');
      expect(result).toContain('## Section B');
      expect(result).not.toContain('Second boilerplate.');
      expect(result).toContain('## Section C');
    });

    it('handles both link replacement and GEO stripping together', () => {
      const raw = [
        'See: /markets/KXBTC for analysis.',
        '### Why This Matters (GEO)',
        'SEO junk.',
        '## Conclusion',
      ].join('\n');

      const result = formatRawReport(raw, ticker);

      expect(result).toContain('https://octagonai.co/markets/KXBTC');
      expect(result).not.toContain('Why This Matters');
      expect(result).toContain('## Conclusion');
    });
  });
});
