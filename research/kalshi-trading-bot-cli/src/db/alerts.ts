import type { Database } from 'bun:sqlite';

export interface Alert {
  alert_id: string;
  ticker?: string | null;
  alert_type: string;
  edge?: number | null;
  message: string;
  channels?: string | null;
  status?: string | null;
  created_at?: number | null;
}

export function createAlert(db: Database, alert: Alert): void {
  db.prepare(`
    INSERT INTO alerts
      (alert_id, ticker, alert_type, edge, message, channels, status, created_at)
    VALUES
      ($alert_id, $ticker, $alert_type, $edge, $message, $channels, $status, $created_at)
  `).run({
    $alert_id: alert.alert_id,
    $ticker: alert.ticker ?? null,
    $alert_type: alert.alert_type,
    $edge: alert.edge ?? null,
    $message: alert.message,
    $channels: alert.channels ?? null,
    $status: alert.status ?? 'pending',
    $created_at: alert.created_at ?? null,
  });
}

export function getPendingAlerts(db: Database): Alert[] {
  return db.query("SELECT * FROM alerts WHERE status = 'pending'").all() as Alert[];
}

export function markAlertSent(db: Database, alertId: string): void {
  db.prepare("UPDATE alerts SET status = 'sent' WHERE alert_id = $id").run({
    $id: alertId,
  });
}

export interface AlertQueryOpts {
  ticker?: string;
  since?: number;
  status?: string;
  alertType?: string;
  limit?: number;
}

export function getAllAlerts(db: Database, opts?: AlertQueryOpts): Alert[] {
  const conditions: string[] = [];
  const params: Record<string, string | number> = {};

  if (opts?.ticker) {
    conditions.push('ticker = $ticker');
    params.$ticker = opts.ticker;
  }
  if (opts?.since) {
    conditions.push('created_at >= $since');
    params.$since = opts.since;
  }
  if (opts?.status) {
    conditions.push('status = $status');
    params.$status = opts.status;
  }
  if (opts?.alertType) {
    conditions.push('alert_type = $alertType');
    params.$alertType = opts.alertType;
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
  const limit = opts?.limit ?? 100;

  return db.prepare(
    `SELECT * FROM alerts ${where} ORDER BY created_at DESC LIMIT ${limit}`
  ).all(params) as Alert[];
}
