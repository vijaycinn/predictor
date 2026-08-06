import { describe, test, expect, beforeEach, afterEach, mock } from 'bun:test';
import { handleCommand } from '../commands/handler.js';
import { AlertRouter } from '../alerts/router.js';
import type { CommandIntent } from '../commands/parser.js';

// Mock the CLI handlers by intercepting fetch (they all go through Kalshi API + DB)
// For unit testing, we mock at the module boundary

describe('handleCommand', () => {
  let router: AlertRouter;
  const sessionKey = 'wa:default:+15551234567';

  beforeEach(() => {
    router = new AlertRouter();
  });

  test('returns null for none intent', async () => {
    const result = await handleCommand({ type: 'none' }, router, sessionKey);
    expect(result).toBeNull();
  });

});
