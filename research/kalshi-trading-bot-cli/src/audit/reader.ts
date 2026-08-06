import { readFileSync, existsSync } from 'fs';
import type { AuditEvent } from './types.js';
import { appPath } from '../utils/paths.js';

const DEFAULT_PATH = appPath('audit.jsonl');

export interface ReadAuditLogOpts {
  filePath?: string;
  since?: Date;
  type?: string;
  ticker?: string;
  limit?: number;
}

export function readAuditLog(opts: ReadAuditLogOpts = {}): AuditEvent[] {
  const filePath = opts.filePath ?? DEFAULT_PATH;

  if (!existsSync(filePath)) return [];

  const content = readFileSync(filePath, 'utf-8');
  const lines = content.split('\n').filter((line) => line.length > 0);

  let events: AuditEvent[] = lines.map((line) => JSON.parse(line));

  if (opts.since) {
    const sinceIso = opts.since.toISOString();
    events = events.filter((e) => e.ts >= sinceIso);
  }

  if (opts.type) {
    events = events.filter((e) => e.type === opts.type);
  }

  if (opts.ticker) {
    events = events.filter((e) => 'ticker' in e && (e as any).ticker === opts.ticker);
  }

  if (opts.limit !== undefined) {
    events = events.slice(0, opts.limit);
  }

  return events;
}
