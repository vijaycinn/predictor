import type { AlertPayload } from '../../scan/alerter.js';
import type { AlertChannelHandler, PendingApproval } from './types.js';

export class AlertRouter {
  private handlers = new Map<string, AlertChannelHandler>();
  private pending = new Map<string, PendingApproval>();

  registerChannel(name: string, handler: AlertChannelHandler): void {
    this.handlers.set(name, handler);
  }

  async route(alert: AlertPayload, target?: string): Promise<void> {
    for (const channel of alert.channels) {
      const handler = this.handlers.get(channel);
      if (handler) {
        await handler(alert, target ?? '');
      }
    }
  }

  setPending(sessionKey: string, approval: PendingApproval): void {
    this.pending.set(sessionKey, approval);
  }

  getPending(sessionKey: string): PendingApproval | undefined {
    return this.pending.get(sessionKey);
  }

  clearPending(sessionKey: string): void {
    this.pending.delete(sessionKey);
  }
}
