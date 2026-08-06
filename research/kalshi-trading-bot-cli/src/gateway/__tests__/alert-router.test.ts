import { describe, test, expect, mock } from 'bun:test';
import { AlertRouter } from '../alerts/router.js';
import type { AlertPayload } from '../../scan/alerter.js';

function makeAlert(channels: string[]): AlertPayload {
  return {
    ticker: 'TEST-TICKER',
    alertType: 'EDGE_DETECTED',
    edge: 0.08,
    message: 'Test alert',
    channels,
  };
}

describe('AlertRouter', () => {
  test('routes to correct channel handler', async () => {
    const router = new AlertRouter();
    const terminalHandler = mock(async () => {});
    const whatsappHandler = mock(async () => {});

    router.registerChannel('terminal', terminalHandler);
    router.registerChannel('whatsapp', whatsappHandler);

    await router.route(makeAlert(['terminal']));

    expect(terminalHandler).toHaveBeenCalledTimes(1);
    expect(whatsappHandler).not.toHaveBeenCalled();
  });

  test('routes to multiple channels', async () => {
    const router = new AlertRouter();
    const terminalHandler = mock(async () => {});
    const whatsappHandler = mock(async () => {});

    router.registerChannel('terminal', terminalHandler);
    router.registerChannel('whatsapp', whatsappHandler);

    await router.route(makeAlert(['terminal', 'whatsapp']), '+15551234567');

    expect(terminalHandler).toHaveBeenCalledTimes(1);
    expect(whatsappHandler).toHaveBeenCalledTimes(1);
  });

  test('ignores unregistered channels', async () => {
    const router = new AlertRouter();
    const terminalHandler = mock(async () => {});
    router.registerChannel('terminal', terminalHandler);

    // Should not throw
    await router.route(makeAlert(['slack']));

    expect(terminalHandler).not.toHaveBeenCalled();
  });

  test('passes target to handler', async () => {
    const router = new AlertRouter();
    const handler = mock(async (_alert: AlertPayload, _target: string) => {});
    router.registerChannel('whatsapp', handler);

    await router.route(makeAlert(['whatsapp']), '+15551234567');

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: 'TEST-TICKER' }),
      '+15551234567',
    );
  });

  test('pending approval set/get/clear lifecycle', () => {
    const router = new AlertRouter();
    const sessionKey = 'wa:default:+15551234567';

    expect(router.getPending(sessionKey)).toBeUndefined();

    router.setPending(sessionKey, {
      ticker: 'TEST-TICKER',
      alertId: 'alert-1',
      edge: 0.08,
      createdAt: Date.now(),
      sessionKey,
    });

    const pending = router.getPending(sessionKey);
    expect(pending).toBeDefined();
    expect(pending!.ticker).toBe('TEST-TICKER');

    router.clearPending(sessionKey);
    expect(router.getPending(sessionKey)).toBeUndefined();
  });

  test('pending approval overwrites previous for same session', () => {
    const router = new AlertRouter();
    const sessionKey = 'wa:default:+15551234567';

    router.setPending(sessionKey, {
      ticker: 'FIRST',
      alertId: 'alert-1',
      edge: 0.05,
      createdAt: Date.now(),
      sessionKey,
    });

    router.setPending(sessionKey, {
      ticker: 'SECOND',
      alertId: 'alert-2',
      edge: 0.10,
      createdAt: Date.now(),
      sessionKey,
    });

    expect(router.getPending(sessionKey)!.ticker).toBe('SECOND');
  });
});
