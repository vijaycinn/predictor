import { appendFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import type { AuditEvent, DistributiveOmit } from './types.js';
import { appPath } from '../utils/paths.js';

const DEFAULT_PATH = appPath('audit.jsonl');

export class AuditTrail {
  private filePath: string;
  private dirCreated = false;

  constructor(filePath?: string) {
    this.filePath = filePath ?? DEFAULT_PATH;
  }

  log(event: DistributiveOmit<AuditEvent, 'ts'>): void {
    if (!this.dirCreated) {
      mkdirSync(dirname(this.filePath), { recursive: true });
      this.dirCreated = true;
    }

    const record = { ts: new Date().toISOString(), ...event };
    appendFileSync(this.filePath, JSON.stringify(record) + '\n');
  }

  close(): void {
    // No-op for sync I/O — included for interface symmetry
  }
}
