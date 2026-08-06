import type { Database } from 'bun:sqlite';
import type { KalshiMarket } from '../tools/kalshi/types.js';
import type { KellyResult } from './kelly.js';
import { getSpreadCents, getVolume24h } from './kelly.js';
import { isCorrelated } from './correlation.js';
import { getOpenPositions } from '../db/positions.js';
import { getLatestSnapshot } from '../db/risk.js';
import { getBotSetting } from '../utils/bot-config.js';

export interface RiskConfig {
  maxSpreadCents?: number;     // default 5
  minVolume24h?: number;       // default 500
  maxPerCategory?: number;     // default 3
  maxTotalPositions?: number;  // default 10
  maxDrawdownPct?: number;     // default 0.20
  maxPositionPct?: number;     // default 0.10
}

export interface RiskGateParams {
  ticker: string;
  eventTicker: string;
  kelly: KellyResult;
  market: KalshiMarket;
  db: Database;
  config?: RiskConfig;
}

export interface RiskCheck {
  name: string;
  passed: boolean;
  reason: string;
}

export interface RiskGateResult {
  passed: boolean;
  checks: RiskCheck[];
}

/**
 * 5-check pre-execution risk gate. All checks must pass.
 */
export function riskGate(params: RiskGateParams): RiskGateResult {
  const { ticker, eventTicker, kelly, market, db, config } = params;

  const maxSpreadCents = config?.maxSpreadCents ?? (getBotSetting('risk.max_spread_cents') as number);
  const minVolume24h = config?.minVolume24h ?? (getBotSetting('risk.min_volume_24h') as number);
  const maxPerCategory = config?.maxPerCategory ?? (getBotSetting('risk.max_per_category') as number);
  const maxTotalPositions = config?.maxTotalPositions ?? (getBotSetting('risk.max_positions') as number);
  const maxDrawdownPct = config?.maxDrawdownPct ?? (getBotSetting('risk.max_drawdown') as number);
  const maxPositionPct = config?.maxPositionPct ?? (getBotSetting('risk.max_position_pct') as number);

  const checks: RiskCheck[] = [];

  // 1. Kelly check — contracts > 0 and dollar amount within position limit
  // Re-check against maxPositionPct independently (kelly.ts uses its own default which may differ)
  const kellyMaxDollar = Math.floor(kelly.availableBankroll * maxPositionPct);
  const kellyWithinLimit = kelly.dollarAmountCents <= kellyMaxDollar;
  const kellyPassed = kelly.contracts > 0 && kellyWithinLimit;
  checks.push({
    name: 'kelly',
    passed: kellyPassed,
    reason: kelly.contracts === 0
      ? (kelly.skippedReason
        ? `Kelly produced 0 contracts: ${kelly.skippedReason}`
        : `Kelly produced 0 contracts for ${ticker}`)
      : !kellyWithinLimit
        ? `Dollar amount $${(kelly.dollarAmountCents / 100).toFixed(2)} exceeds ${maxPositionPct * 100}% of bankroll $${(kelly.availableBankroll / 100).toFixed(2)}`
        : `${kelly.contracts} ${kelly.side.toUpperCase()} contracts, $${(kelly.dollarAmountCents / 100).toFixed(2)} within limits`,
  });

  // 2. Liquidity check — spread and volume (using dollar-aware spread)
  const spreadCents = getSpreadCents(market);
  const spreadOk = spreadCents < maxSpreadCents;
  const vol24h = getVolume24h(market);
  const volumeOk = vol24h >= minVolume24h;
  const liquidityPassed = spreadOk && volumeOk;
  checks.push({
    name: 'liquidity',
    passed: liquidityPassed,
    reason: !spreadOk
      ? `Spread ${spreadCents}¢ >= max ${maxSpreadCents}¢`
      : !volumeOk
        ? `24h volume ${vol24h} < min ${minVolume24h}`
        : `Spread ${spreadCents}¢, volume ${vol24h} OK`,
  });

  // 3. Correlation check — category concentration
  const correlated = isCorrelated(eventTicker, db, maxPerCategory);
  checks.push({
    name: 'correlation',
    passed: !correlated,
    reason: correlated
      ? `Category for ${eventTicker} already has ${maxPerCategory}+ open positions`
      : `Category concentration within limit`,
  });

  // 4. Concentration check — total open positions
  const openPositions = getOpenPositions(db);
  const concentrationPassed = openPositions.length < maxTotalPositions;
  checks.push({
    name: 'concentration',
    passed: concentrationPassed,
    reason: concentrationPassed
      ? `${openPositions.length} open positions < max ${maxTotalPositions}`
      : `${openPositions.length} open positions >= max ${maxTotalPositions}`,
  });

  // 5. Drawdown check — current drawdown vs limit
  const snapshot = getLatestSnapshot(db);
  const drawdownPassed = snapshot?.drawdown_current == null || snapshot.drawdown_current < maxDrawdownPct;
  checks.push({
    name: 'drawdown',
    passed: drawdownPassed,
    reason: snapshot?.drawdown_current == null
      ? 'No snapshot yet — first trade allowed'
      : snapshot.drawdown_current < maxDrawdownPct
        ? `Drawdown ${(snapshot.drawdown_current * 100).toFixed(1)}% < max ${maxDrawdownPct * 100}%`
        : `Drawdown ${(snapshot.drawdown_current * 100).toFixed(1)}% >= max ${maxDrawdownPct * 100}%`,
  });

  return {
    passed: checks.every((c) => c.passed),
    checks,
  };
}
