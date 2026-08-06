"""Kalshi fee economics (from external research, assimilated 2026-08-06).

Fee formula: fee = rate * C * p * (1-p), rounded UP to next cent.
- General rate: 0.07  (~1.75% at p=0.50)
- Maker-fee tickers: 0.0175 (tennis, fed, crypto series, MLB/NHL/NBA games)
- At extremes (p=0.05/0.95): 0.33% / 0.0175-rate 0.08%

Structural consequence: cross-venue arb needs >= ~400bps raw edge to survive
round-trip fees. Sub-200bps raw edges ALWAYS net-negative.

Maker-fee ticker list captured from PolyKalshi_Client kalshi_fee_calculator.py.
"""

from __future__ import annotations

import math

# Tickers whose maker fee is 0.0175 instead of 0.07 (fee schedule per venue docs)
MAKER_FEE_PATTERNS = (
    "KXAAAGASM", "KXGDP", "KXPAYROLLS", "KXU3", "KXEGGS", "KXCPI", "KXCPIYOY",
    "KXFEDDECISION", "KXFED", "KXNBA", "KXNHL", "KXINDY500", "KXPGA", "KXUSOPEN",
    "KXPGARYDER", "KXTHEOPEN", "KXPGASOLHEIM", "KXSINGLES", "KXNFLGAME", "KXUEFACL",
    "KXNATHANSHD", "KXCLUBWC", "KXTOURDEFRANCE", "KXNASCARRACE", "KXATPMATCH",
    "KXWTAMATCH", "KXMLBASGAME", "KXMLBHRDERBY",
)

GENERAL_FEE_RATE = 0.07
MAKER_FEE_RATE = 0.0175

# Cross-venue arb raw-edge floor: below this round-trip fees eat the trade
ARB_MIN_RAW_EDGE = 0.04        # 400bps — playbook: sub-200bps ALWAYS net-negative
ARB_ALWAYS_LOSE_EDGE = 0.02    # 200bps — hard no


def fee_rate_for_ticker(ticker: str) -> float:
    """0.0175 for maker-fee tickers, else 0.07."""
    if ticker:
        for pat in MAKER_FEE_PATTERNS:
            if pat in ticker:
                return MAKER_FEE_RATE
    return GENERAL_FEE_RATE


def kalshi_fee(price: float, contracts: float, ticker: str | None = None) -> float:
    """Fee in dollars for a trade at `price` (0-1) of `contracts` shares.

    Rounded UP to next cent (Kalshi behavior).
    """
    if price <= 0 or price >= 1 or contracts <= 0:
        return 0.0
    rate = fee_rate_for_ticker(ticker or "")
    fee = rate * contracts * price * (1.0 - price)
    return math.ceil(fee * 100.0) / 100.0


def fee_per_contract(price: float, ticker: str | None = None) -> float:
    """Fee per single contract at `price` (rounded up to cent)."""
    if price <= 0 or price >= 1:
        return 0.0
    rate = fee_rate_for_ticker(ticker or "")
    fee = rate * price * (1.0 - price)
    return math.ceil(fee * 100.0) / 100.0


def net_edge_after_fees(gross_edge: float, leg_prices: list[tuple[float, str]],
                        slippage: float = 0.01) -> float:
    """gross_edge - kalshi fees on each leg - slippage.

    leg_prices: [(price, ticker_or_empty), ...] for each Kalshi leg.
    """
    fees = sum(kalshi_fee(p, 1.0, t) for p, t in leg_prices)
    return gross_edge - fees - slippage
