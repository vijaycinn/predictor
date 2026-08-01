"""Config loading with defaults deep-merged from config.yaml."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "venue": "polymarket",
    "kalshi": {
        "base_url": "https://external-api.kalshi.com/trade-api/v2",
        "scan": {
            "min_volume_usd": 2000,
            "min_24h_volume": 300,
            "min_liquidity": 100,
        },
    },
    "mode": "paper",
    "scan": {
        "max_markets": 40,
        "categories": ["crypto", "politics", "sports", "economics"],
        "min_volume_usd": 50000,
        "min_24h_volume": 5000,
        "min_liquidity": 1000,
        "min_recent_trades": 5,
    },
    "fees": {
        "taker_fee_per_share": 0.0,
        "maker_fee_per_share": 0.0,
        "gas_per_trade_usd": 0.0,
    },
    "execution": {
        "max_spread": 0.04,
        "min_hours_to_expiry": 2,
        "max_days_to_expiry": 400,
        "min_edge": 0.03,
        "ev_min_net": 0.02,
        "prefer_maker": True,
        "aggressiveness": 0.5,
    },
    "risk": {
        "capital_usd": 1000,
        "max_per_trade_frac": 0.20,
        "max_notional_frac": 0.60,
        "max_daily_loss_usd": 50,
        "max_per_event_frac": 0.30,
        "kelly_fraction": 0.25,
        "max_concurrent_positions": 12,
        "max_same_category_frac": 0.40,
    },
    "prob": {
        "market_price_weight": 0.55,
        "orderbook_weight": 0.15,
        "momentum_weight": 0.10,
        "base_rate_weight": 0.05,
        "sentiment_weight": 0.05,
        "llm_weight": 0.30,
        "shortlist_edge": 0.008,
        "shortlist_max": 10,
        "momentum_lookback": 24,
        "momentum_scale": 0.10,
        "book_imbalance_scale": 0.03,
        "min_prob": 0.01,
        "max_prob": 0.99,
    },
    "learn": {
        "calibration_buckets": 10,
        "min_samples_per_bucket": 5,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        p = Path(path)
        if p.exists():
            user = yaml.safe_load(p.read_text()) or {}
            cfg = _deep_merge(cfg, user)
    return cfg
