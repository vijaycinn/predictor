import type { Database } from 'bun:sqlite';

export interface RiskSnapshot {
  id?: number;
  timestamp: number;
  cash_balance?: number | null;
  portfolio_value?: number | null;
  open_exposure?: number | null;
  available_bankroll?: number | null;
  daily_pnl?: number | null;
  drawdown_current?: number | null;
  drawdown_max?: number | null;
  correlation_max?: number | null;
  positions_count?: number | null;
  circuit_breaker_on?: number | null;
}

export function insertRiskSnapshot(db: Database, snapshot: RiskSnapshot): void {
  db.prepare(`
    INSERT INTO risk_snapshots
      (timestamp, cash_balance, portfolio_value, open_exposure, available_bankroll,
       daily_pnl, drawdown_current, drawdown_max, correlation_max, positions_count, circuit_breaker_on)
    VALUES
      ($timestamp, $cash_balance, $portfolio_value, $open_exposure, $available_bankroll,
       $daily_pnl, $drawdown_current, $drawdown_max, $correlation_max, $positions_count, $circuit_breaker_on)
  `).run({
    $timestamp: snapshot.timestamp,
    $cash_balance: snapshot.cash_balance ?? null,
    $portfolio_value: snapshot.portfolio_value ?? null,
    $open_exposure: snapshot.open_exposure ?? null,
    $available_bankroll: snapshot.available_bankroll ?? null,
    $daily_pnl: snapshot.daily_pnl ?? null,
    $drawdown_current: snapshot.drawdown_current ?? null,
    $drawdown_max: snapshot.drawdown_max ?? null,
    $correlation_max: snapshot.correlation_max ?? null,
    $positions_count: snapshot.positions_count ?? null,
    $circuit_breaker_on: snapshot.circuit_breaker_on ?? 0,
  });
}

export function getLatestSnapshot(db: Database): RiskSnapshot | null {
  return db.query(
    'SELECT * FROM risk_snapshots ORDER BY timestamp DESC LIMIT 1'
  ).get() as RiskSnapshot | null;
}

export function getDrawdownHistory(db: Database, since: number): RiskSnapshot[] {
  return db.query(
    'SELECT * FROM risk_snapshots WHERE timestamp >= $since ORDER BY timestamp ASC'
  ).all({ $since: since }) as RiskSnapshot[];
}
