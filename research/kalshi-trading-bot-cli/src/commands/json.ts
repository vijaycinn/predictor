export interface CLIResponse<T> {
  ok: boolean;
  command: string;
  timestamp: string;
  data: T;
  meta?: {
    scan_id?: string;
    theme?: string;
    events_scanned?: number;
    actionable?: number;
    octagon_cache_hits?: number;
    octagon_fresh_reports?: number;
    octagon_credits_used?: number;
    bankroll?: {
      cash_balance: number;
      portfolio_value: number;
      open_exposure: number;
      available: number;
      positions_count: number;
    };
  };
  error?: { code: string; message: string };
}

export function wrapSuccess<T>(command: string, data: T, meta?: CLIResponse<T>['meta']): CLIResponse<T> {
  return {
    ok: true,
    command,
    timestamp: new Date().toISOString(),
    data,
    ...(meta ? { meta } : {}),
  };
}

export function wrapError(command: string, code: string, message: string): CLIResponse<never> {
  return {
    ok: false,
    command,
    timestamp: new Date().toISOString(),
    data: undefined as never,
    error: { code, message },
  };
}
