import { describe, test, expect } from 'bun:test';
import { parseCommand } from '../commands/parser.js';

describe('parseCommand', () => {
  test('parses "scan" with no theme', () => {
    const result = parseCommand('scan');
    expect(result).toEqual({ type: 'scan', theme: undefined });
  });

  test('parses "scan crypto"', () => {
    const result = parseCommand('scan crypto');
    expect(result).toEqual({ type: 'scan', theme: 'crypto' });
  });

  test('parses "scan" case-insensitively', () => {
    const result = parseCommand('Scan top50');
    expect(result).toEqual({ type: 'scan', theme: 'top50' });
  });

  test('parses "edge" with no ticker', () => {
    const result = parseCommand('edge');
    expect(result).toEqual({ type: 'edge', ticker: undefined });
  });

  test('parses "edge TICKER"', () => {
    const result = parseCommand('edge KXBTC-26MAR-B80000');
    expect(result).toEqual({ type: 'edge', ticker: 'KXBTC-26MAR-B80000' });
  });

  test('parses "portfolio"', () => {
    expect(parseCommand('portfolio')).toEqual({ type: 'portfolio' });
  });

  test('parses "positions" as portfolio', () => {
    expect(parseCommand('positions')).toEqual({ type: 'portfolio' });
  });

  test('returns none for random text', () => {
    expect(parseCommand('what is the weather today?')).toEqual({ type: 'none' });
  });

  test('returns none for empty string', () => {
    expect(parseCommand('')).toEqual({ type: 'none' });
  });

  test('trims whitespace', () => {
    expect(parseCommand('  scan  crypto  ')).toEqual({ type: 'scan', theme: 'crypto' });
  });
});
