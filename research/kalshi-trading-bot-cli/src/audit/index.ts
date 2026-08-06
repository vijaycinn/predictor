export { AuditTrail } from './trail.js';
export { readAuditLog } from './reader.js';
export type { ReadAuditLogOpts } from './reader.js';
export type {
  AuditEvent,
  AuditEventType,
  AuditBase,
  DistributiveOmit,
  ScanStartEvent,
  ScanCompleteEvent,
  OctagonCallEvent,
  EdgeDetectedEvent,
  RecommendationEvent,
  TradeExecutedEvent,
  AlertSentEvent,
  WatchdogCheckEvent,
  ApiRetryEvent,
  DlqEntryEvent,
  ConfigChangeEvent,
  ConfigSetEvent,
} from './types.js';

import { AuditTrail } from './trail.js';

export const auditTrail = new AuditTrail();
