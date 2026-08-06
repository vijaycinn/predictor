import type { ParsedArgs } from './parse-args.js';
import type { CLIResponse } from './json.js';
import { wrapSuccess, wrapError } from './json.js';
import { formatTable } from './scan-formatters.js';
import { auditTrail } from '../audit/index.js';
import {
  getAllSettings,
  getBotSetting,
  setBotSetting,
  type FlatSetting,
} from '../utils/bot-config.js';

export interface ConfigEntry {
  key: string;
  value: unknown;
  default: unknown;
  isDefault: boolean;
}

export interface ConfigListData {
  mode: 'list';
  entries: ConfigEntry[];
}

export interface ConfigGetData {
  mode: 'get';
  entry: ConfigEntry;
}

export interface ConfigSetData {
  mode: 'set';
  key: string;
  oldValue: unknown;
  newValue: unknown;
}

export type ConfigData = ConfigListData | ConfigGetData | ConfigSetData;

function toEntry(s: FlatSetting): ConfigEntry {
  return { key: s.key, value: s.value, default: s.default, isDefault: s.isDefault };
}

export async function handleConfig(args: ParsedArgs): Promise<CLIResponse<ConfigData>> {
  const positional = args.positionalArgs;

  // 0 args → list all
  if (positional.length === 0) {
    const entries = getAllSettings().map(toEntry);
    return wrapSuccess('config', { mode: 'list', entries } as ConfigData);
  }

  const key = positional[0];

  // 1 arg → get
  if (positional.length === 1) {
    const value = getBotSetting(key);
    if (value === undefined) {
      return wrapError('config', 'UNKNOWN_KEY', `Unknown config key: ${key}`) as CLIResponse<ConfigData>;
    }
    const all = getAllSettings();
    const match = all.find((s) => s.key === key);
    const entry: ConfigEntry = match
      ? toEntry(match)
      : { key, value, default: value, isDefault: true };
    return wrapSuccess('config', { mode: 'get', entry } as ConfigData);
  }

  // 2 args → set
  const rawValue = positional[1];
  try {
    const { oldValue, newValue } = setBotSetting(key, rawValue);

    auditTrail.log({
      type: 'CONFIG_SET',
      key,
      old_value: JSON.stringify(oldValue),
      new_value: JSON.stringify(newValue),
    });

    return wrapSuccess('config', { mode: 'set', key, oldValue, newValue } as ConfigData);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return wrapError('config', 'INVALID_CONFIG', msg) as CLIResponse<ConfigData>;
  }
}

function formatValue(v: unknown): string {
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

export function formatConfigHuman(data: ConfigData): string {
  switch (data.mode) {
    case 'list': {
      const rows = data.entries.map((e) => [
        e.key,
        formatValue(e.value),
        formatValue(e.default),
      ]);
      return formatTable(['Key', 'Value', 'Default'], rows);
    }
    case 'get':
      return `${data.entry.key} = ${formatValue(data.entry.value)}`;
    case 'set':
      return `${data.key}: ${formatValue(data.oldValue)} → ${formatValue(data.newValue)}`;
  }
}
