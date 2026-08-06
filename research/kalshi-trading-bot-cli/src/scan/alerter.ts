import type { Database } from 'bun:sqlite';
import type { AuditTrail } from '../audit/trail.js';
import { createAlert, markAlertSent } from '../db/alerts.js';

export type AlertType =
  | 'EDGE_DETECTED'
  | 'CONVERGENCE'
  | 'ADVERSE_MOVE'
  | 'EXPIRY_APPROACHING'
  | 'CATALYST_APPROACHING'
  | 'CIRCUIT_BREAKER';

export interface AlertPayload {
  ticker: string;
  alertType: AlertType;
  edge: number;
  message: string;
  channels: string[];
}

export type AlertChannelDispatch = (channel: string, alert: AlertPayload) => Promise<void>;

export class Alerter {
  private db: Database;
  private audit: AuditTrail;
  private dispatch?: AlertChannelDispatch;

  constructor(db: Database, audit: AuditTrail, dispatch?: AlertChannelDispatch) {
    this.db = db;
    this.audit = audit;
    this.dispatch = dispatch;
  }

  async emit(alert: AlertPayload): Promise<void> {
    const alertId = crypto.randomUUID();

    createAlert(this.db, {
      alert_id: alertId,
      ticker: alert.ticker,
      alert_type: alert.alertType,
      edge: alert.edge,
      message: alert.message,
      channels: JSON.stringify(alert.channels),
      status: 'pending',
      created_at: Math.floor(Date.now() / 1000),
    });

    for (const channel of alert.channels) {
      if (this.dispatch) {
        await this.dispatch(channel, alert);
      } else if (channel === 'terminal') {
        console.log(`[ALERT] [${alert.alertType}] ${alert.ticker}: ${alert.message} (edge=${alert.edge.toFixed(4)})`);
      }
    }

    markAlertSent(this.db, alertId);

    this.audit.log({
      type: 'ALERT_SENT',
      alert_id: alertId,
      channels: alert.channels,
    });
  }
}
