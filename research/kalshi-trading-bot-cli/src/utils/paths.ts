import { join } from 'node:path';
import { homedir } from 'node:os';

const APP_DIR = join(homedir(), '.kalshi-bot');

export function getAppDir(): string {
  return APP_DIR;
}

export function appPath(...segments: string[]): string {
  return join(APP_DIR, ...segments);
}
