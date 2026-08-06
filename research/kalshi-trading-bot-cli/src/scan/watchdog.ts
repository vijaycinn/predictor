import type { Database } from 'bun:sqlite';
import type { AuditTrail } from '../audit/trail.js';
import type { Position } from '../db/positions.js';
import type { Catalyst } from './types.js';
import { getOpenPositions } from '../db/positions.js';
import { getLatestEdge } from '../db/edge.js';
import { getEvent } from '../db/events.js';

export type WatchdogAlertType =
  | 'CONVERGENCE'
  | 'ADVERSE_MOVE'
  | 'EXPIRY_APPROACHING'
  | 'CATALYST_APPROACHING';

export interface WatchdogAlert {
  ticker: string;
  alertType: WatchdogAlertType;
  edge: number;
  entryEdge: number;
  message: string;
  position: Position;
}

const CONVERGENCE_THRESHOLD = 0.02;
const EXPIRY_WINDOW = 24 * 3600;
const CATALYST_WINDOW = 24 * 3600;

export class PositionWatchdog {
  private audit: AuditTrail;

  constructor(audit: AuditTrail) {
    this.audit = audit;
  }

  check(db: Database, now?: number): WatchdogAlert[] {
    const currentTime = now ?? Math.floor(Date.now() / 1000);
    const positions = getOpenPositions(db);
    const alerts: WatchdogAlert[] = [];

    for (const position of positions) {
      const edgeRow = getLatestEdge(db, position.ticker);
      if (!edgeRow) continue;

      const currentEdge = edgeRow.edge;
      const entryEdge = position.entry_edge ?? 0;
      const statuses: string[] = [];

      // CONVERGENCE: edge has shrunk to near zero
      if (Math.abs(currentEdge) < CONVERGENCE_THRESHOLD) {
        statuses.push('CONVERGENCE');
        alerts.push({
          ticker: position.ticker,
          alertType: 'CONVERGENCE',
          edge: currentEdge,
          entryEdge,
          message: `Edge converged to ${currentEdge.toFixed(4)} (threshold ${CONVERGENCE_THRESHOLD})`,
          position,
        });
      }

      // ADVERSE_MOVE: edge flipped sign from entry
      if (entryEdge * currentEdge < 0) {
        statuses.push('ADVERSE_MOVE');
        alerts.push({
          ticker: position.ticker,
          alertType: 'ADVERSE_MOVE',
          edge: currentEdge,
          entryEdge,
          message: `Edge flipped sign: entry=${entryEdge.toFixed(4)}, current=${currentEdge.toFixed(4)}`,
          position,
        });
      }

      // EXPIRY_APPROACHING: event expires within 24h
      const event = getEvent(db, position.event_ticker);
      if (event?.expiry && event.expiry - currentTime < EXPIRY_WINDOW) {
        statuses.push('EXPIRY_APPROACHING');
        const hoursLeft = Math.max(0, (event.expiry - currentTime) / 3600);
        alerts.push({
          ticker: position.ticker,
          alertType: 'EXPIRY_APPROACHING',
          edge: currentEdge,
          entryEdge,
          message: `Event ${position.event_ticker} expires in ${hoursLeft.toFixed(1)}h`,
          position,
        });
      }

      // CATALYST_APPROACHING: high-impact catalyst within 24h
      if (edgeRow.catalysts_json) {
        try {
          const catalysts: Catalyst[] = JSON.parse(edgeRow.catalysts_json);
          for (const catalyst of catalysts) {
            if (catalyst.impact === 'high') {
              const catalystTime = new Date(catalyst.date).getTime() / 1000;
              if (catalystTime - currentTime > 0 && catalystTime - currentTime < CATALYST_WINDOW) {
                statuses.push('CATALYST_APPROACHING');
                alerts.push({
                  ticker: position.ticker,
                  alertType: 'CATALYST_APPROACHING',
                  edge: currentEdge,
                  entryEdge,
                  message: `High-impact catalyst "${catalyst.event}" approaching: ${catalyst.date}`,
                  position,
                });
              }
            }
          }
        } catch {
          // Ignore malformed catalysts JSON
        }
      }

      const status = statuses.length > 0 ? statuses.join(',') : 'healthy';
      this.audit.log({
        type: 'WATCHDOG_CHECK',
        ticker: position.ticker,
        entry_edge: entryEdge,
        current_edge: currentEdge,
        status,
      });
    }

    return alerts;
  }
}
