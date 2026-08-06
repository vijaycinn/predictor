import { describe, test, expect } from 'bun:test';
import { formatAlertForWhatsApp } from '../alerts/formatter.js';
import type { AlertPayload } from '../../scan/alerter.js';

function makeAlert(overrides: Partial<AlertPayload> = {}): AlertPayload {
  return {
    ticker: 'KXBTC-26MAR-B80000',
    alertType: 'EDGE_DETECTED',
    edge: 0.082,
    message: 'Edge 8.2% (high) on KXBTC-26MAR-B80000',
    channels: ['whatsapp'],
    ...overrides,
  };
}

describe('formatAlertForWhatsApp', () => {
  test('edge alert has magnitude bar', () => {
    const output = formatAlertForWhatsApp(makeAlert());
    expect(output).toContain('[========--]');
    expect(output).toContain('+8.2%');
  });

  test('edge alert has ticker in bold', () => {
    const output = formatAlertForWhatsApp(makeAlert());
    expect(output).toContain('*KXBTC-26MAR-B80000*');
  });

  test('edge alert has approve prompt', () => {
    const output = formatAlertForWhatsApp(makeAlert());
    expect(output).toContain('Reply *YES* to get a recommendation');
  });

  test('does not use markdown bold (**)', () => {
    const output = formatAlertForWhatsApp(makeAlert());
    expect(output).not.toContain('**');
  });

  test('convergence alert format', () => {
    const output = formatAlertForWhatsApp(makeAlert({ alertType: 'CONVERGENCE', edge: 0.02 }));
    expect(output).toContain('*CONVERGENCE*');
    expect(output).toContain('2.0%');
  });

  test('adverse move alert format', () => {
    const output = formatAlertForWhatsApp(makeAlert({ alertType: 'ADVERSE_MOVE' }));
    expect(output).toContain('*ADVERSE MOVE*');
  });

  test('expiry alert format', () => {
    const output = formatAlertForWhatsApp(makeAlert({ alertType: 'EXPIRY_APPROACHING' }));
    expect(output).toContain('*EXPIRY APPROACHING*');
  });

  test('catalyst alert format', () => {
    const output = formatAlertForWhatsApp(makeAlert({ alertType: 'CATALYST_APPROACHING' }));
    expect(output).toContain('*CATALYST APPROACHING*');
  });

  test('circuit breaker alert format', () => {
    const output = formatAlertForWhatsApp(makeAlert({
      alertType: 'CIRCUIT_BREAKER',
      ticker: '*',
      message: 'Max drawdown exceeded',
    }));
    expect(output).toContain('*CIRCUIT BREAKER*');
    expect(output).toContain('Max drawdown exceeded');
  });

  test('negative edge shows minus sign', () => {
    const output = formatAlertForWhatsApp(makeAlert({ edge: -0.05 }));
    expect(output).toContain('-5.0%');
  });
});
