export type { AlertType, AlertPayload } from '../../scan/alerter.js';

export type AlertChannelHandler = (alert: import('../../scan/alerter.js').AlertPayload, target: string) => Promise<void>;

export type AlertChannelDispatch = (channel: string, alert: import('../../scan/alerter.js').AlertPayload) => Promise<void>;

export interface PendingApproval {
  ticker: string;
  alertId: string;
  edge: number;
  createdAt: number;
  sessionKey: string;
}
