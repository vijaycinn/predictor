#!/usr/bin/env bun
/**
 * Test every slash command end-to-end with live API data.
 * Run: bun scripts/test-commands.ts
 */
import { handleSlashCommand } from '../src/commands/index.js';

const commands = [
  // Research
  '/events',
  '/events KXTESLA',
  '/events next',
  '/markets',
  '/markets KXTESLA',
  '/markets next',
  '/event KXTESLA-26-Q1',
  '/market KXTESLA-26-Q1-340000',

  // Analysis (should fall through to agent)
  '/edge',
  '/recommend',
  '/deep-research',
  '/portfolio',

  // Account
  '/balance',
  '/positions',
  '/orders',
  '/status',

  // Trade
  '/buy KXTESLA-26-Q1-340000 1 65',
  '/sell KXTESLA-26-Q1-340000 1 65',
  '/cancel',

  // Settings
  '/help',
];

let passed = 0;
let failed = 0;
const issues: string[] = [];

for (const cmd of commands) {
  console.log('━'.repeat(80));
  console.log('CMD:', cmd);
  try {
    const start = Date.now();
    const result = await handleSlashCommand(cmd);
    const elapsed = Date.now() - start;

    if (result === null) {
      console.log('→ NULL (falls to agent) ✓ [' + elapsed + 'ms]');
      passed++;
      continue;
    }

    const output = result.output;
    const lines = output.split('\n');
    const hasTable = output.includes('│');
    const hasPending = !!result.pendingTrade;

    const cmdIssues: string[] = [];

    // Check for empty tables
    if (hasTable) {
      const dataRows = lines.filter(l => l.startsWith('│') && !l.includes('─'));
      // First data row is the header
      const contentRows = dataRows.slice(1);
      if (contentRows.length === 0) cmdIssues.push('Table has no data rows');

      // Check for rows that are ALL dashes
      const emptyRows = contentRows.filter(r => {
        const cells = r.split('│').filter(c => c.trim()).map(c => c.trim());
        return cells.every(c => c === '-' || c === '');
      });
      if (emptyRows.length > 0 && emptyRows.length === contentRows.length) {
        cmdIssues.push('All rows are empty');
      }
    }

    // Check for error messages
    if (output.toLowerCase().includes('error:')) {
      cmdIssues.push('Contains error message');
    }

    if (cmdIssues.length > 0) {
      console.log('⚠️  ISSUES:', cmdIssues.join(', '));
      issues.push(`${cmd}: ${cmdIssues.join(', ')}`);
      failed++;
    } else {
      console.log('✓ OK [' + elapsed + 'ms]');
      passed++;
    }

    // Show preview
    if (hasTable) {
      const tableRows = lines.filter(l => l.startsWith('│') && !l.includes('─'));
      console.log('  Rows:', tableRows.length - 1, '(excl header)');
      if (tableRows[1]) console.log('  First:', tableRows[1].slice(0, 110));
    } else if (output.length < 300) {
      const preview = output.replace(/\n/g, ' ').slice(0, 150);
      console.log(' ', preview);
    } else {
      console.log('  Output:', output.length, 'chars');
    }

    if (hasPending) console.log('  📋 Has pending trade confirmation');

  } catch (e: any) {
    console.log('✗ ERROR:', e.message);
    issues.push(`${cmd}: THREW ${e.message}`);
    failed++;
  }
}

console.log('\n' + '═'.repeat(80));
console.log(`Results: ${passed} passed, ${failed} failed out of ${commands.length}`);
if (issues.length > 0) {
  console.log('\nIssues:');
  for (const issue of issues) {
    console.log('  •', issue);
  }
}
