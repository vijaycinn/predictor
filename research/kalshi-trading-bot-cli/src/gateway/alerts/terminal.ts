import type { AlertPayload } from '../../scan/alerter.js';

function magnitudeBar(edge: number): string {
  const absEdge = Math.abs(edge);
  const pct = Math.min(absEdge * 100, 10);
  const filled = Math.round(pct);
  const empty = 10 - filled;
  const sign = edge >= 0 ? '+' : '-';
  return `[${`=`.repeat(filled)}${`-`.repeat(empty)}] ${sign}${(absEdge * 100).toFixed(1)}%`;
}

export function formatAlertForTerminal(alert: AlertPayload): string {
  const ts = new Date().toISOString().slice(11, 19);
  const bar = magnitudeBar(alert.edge);
  return `[${ts}] [${alert.alertType}] ${alert.ticker} ${bar} — ${alert.message}`;
}
