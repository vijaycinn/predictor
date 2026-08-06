import type { AlertPayload } from '../../scan/alerter.js';

function magnitudeBar(edge: number): string {
  const absEdge = Math.abs(edge);
  const pct = Math.min(absEdge * 100, 10);
  const filled = Math.round(pct);
  const empty = 10 - filled;
  const sign = edge >= 0 ? '+' : '-';
  return `[${`=`.repeat(filled)}${`-`.repeat(empty)}] ${sign}${(absEdge * 100).toFixed(1)}%`;
}

function formatEdgeAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`🔔 *EDGE DETECTED*`);
  lines.push('');
  lines.push(`*${alert.ticker}*`);
  lines.push(magnitudeBar(alert.edge));
  lines.push('');
  lines.push(alert.message);
  lines.push('');
  lines.push(`Reply *YES* to get a recommendation`);
  return lines.join('\n');
}

function formatConvergenceAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`⚠️ *CONVERGENCE*`);
  lines.push('');
  lines.push(`*${alert.ticker}*`);
  lines.push(alert.message);
  lines.push('');
  lines.push(`Edge narrowed to ${(Math.abs(alert.edge) * 100).toFixed(1)}%`);
  return lines.join('\n');
}

function formatAdverseMoveAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`🚨 *ADVERSE MOVE*`);
  lines.push('');
  lines.push(`*${alert.ticker}*`);
  lines.push(alert.message);
  return lines.join('\n');
}

function formatExpiryAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`⏰ *EXPIRY APPROACHING*`);
  lines.push('');
  lines.push(`*${alert.ticker}*`);
  lines.push(alert.message);
  return lines.join('\n');
}

function formatCatalystAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`📅 *CATALYST APPROACHING*`);
  lines.push('');
  lines.push(`*${alert.ticker}*`);
  lines.push(alert.message);
  return lines.join('\n');
}

function formatCircuitBreakerAlert(alert: AlertPayload): string {
  const lines: string[] = [];
  lines.push(`🛑 *CIRCUIT BREAKER*`);
  lines.push('');
  lines.push(alert.message);
  lines.push('');
  lines.push(`All new positions paused until risk clears.`);
  return lines.join('\n');
}

export function formatAlertForWhatsApp(alert: AlertPayload): string {
  switch (alert.alertType) {
    case 'EDGE_DETECTED':
      return formatEdgeAlert(alert);
    case 'CONVERGENCE':
      return formatConvergenceAlert(alert);
    case 'ADVERSE_MOVE':
      return formatAdverseMoveAlert(alert);
    case 'EXPIRY_APPROACHING':
      return formatExpiryAlert(alert);
    case 'CATALYST_APPROACHING':
      return formatCatalystAlert(alert);
    case 'CIRCUIT_BREAKER':
      return formatCircuitBreakerAlert(alert);
    default:
      return `*ALERT* ${alert.ticker}: ${alert.message}`;
  }
}
