export type CommandIntent =
  | { type: 'scan'; theme?: string }
  | { type: 'edge'; ticker?: string }
  | { type: 'portfolio' }
  | { type: 'none' };

export function parseCommand(body: string): CommandIntent {
  const trimmed = body.trim();
  const lower = trimmed.toLowerCase();

  // Portfolio / positions
  if (lower === 'portfolio' || lower === 'positions') {
    return { type: 'portfolio' };
  }

  // Scan [theme]
  if (lower === 'scan' || lower.startsWith('scan ')) {
    const rest = trimmed.slice(4).trim();
    return { type: 'scan', theme: rest || undefined };
  }

  // Edge [ticker]
  if (lower === 'edge' || lower.startsWith('edge ')) {
    const rest = trimmed.slice(4).trim();
    return { type: 'edge', ticker: rest || undefined };
  }

  return { type: 'none' };
}
