"""Outcome tracking, calibration, and strategy refinement analytics."""
from __future__ import annotations

import json
import statistics
import time

from . import db


def check_resolutions(conn) -> list[dict]:
    """Poll gamma for closed markets we track; record outcomes and P&L."""
    from .ingest import GAMMA, get_json

    rows = conn.execute(
        "SELECT condition_id FROM markets WHERE closed=0 AND condition_id IS NOT NULL"
    ).fetchall()
    resolved = []
    for r in rows:
        cid = r["condition_id"]
        try:
            d = get_json(f"{GAMMA}/markets", {"condition_id": cid})
        except Exception:
            continue
        market = (d or [{}])[0] if isinstance(d, list) else d
        if not market:
            continue
        if not market.get("closed"):
            continue
        prices = []
        try:
            prices = [float(p) for p in json.loads(market.get("outcomePrices") or "[]")]
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if len(prices) < 2:
            continue
        result_yes = 1 if prices[0] >= 0.5 else 0
        db.set_market_resolved(conn, cid, result_yes, prices[0])
        pnl = db.get_trade_pnl(conn, cid, result_yes)
        resolved.append({"condition_id": cid, "result_yes": result_yes, "pnl": pnl})
    return resolved


def calibration_report(conn, cfg: dict) -> dict:
    """Reliability table: predicted prob bucket vs realized outcome frequency."""
    buckets = cfg.get("learn", {}).get("calibration_buckets", 10)
    min_samples = cfg.get("learn", {}).get("min_samples_per_bucket", 5)

    rows = conn.execute(
        """SELECT s.prob_yes, s.confidence, s.confidence_tier, s.side, s.action,
                  o.result_yes
           FROM signals s JOIN outcomes o ON o.condition_id = s.condition_id
           WHERE s.action='BUY' OR s.action='HOLD'"""
    ).fetchall()

    bucket_map = {i: [] for i in range(buckets)}
    for r in rows:
        p = r["prob_yes"]
        if p is None:
            continue
        idx = min(buckets - 1, int(p * buckets))
        bucket_map[idx].append(r["result_yes"])

    table = []
    brier_total, brier_n = 0.0, 0
    for idx in range(buckets):
        outcomes = bucket_map[idx]
        if not outcomes:
            continue
        n = len(outcomes)
        freq = sum(outcomes) / n
        mid_p = (idx + 0.5) / buckets
        brier_total += sum((p_mid - o) ** 2 for o in outcomes)
        brier_n += n
        table.append({
            "bucket": f"{mid_p:.2f}",
            "n": n,
            "realized": round(freq, 3),
            "predicted": round(mid_p, 3),
            "bias": round(freq - mid_p, 3),
        })

    # category-level bias
    cat_rows = conn.execute(
        """SELECT s.prob_yes, s.metrics_json, o.result_yes
           FROM signals s JOIN outcomes o ON o.condition_id = s.condition_id"""
    ).fetchall()
    by_cat = {}
    for r in cat_rows:
        try:
            meta = json.loads(r["metrics_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        cat = meta.get("category", "unknown")
        by_cat.setdefault(cat, []).append((r["prob_yes"], r["result_yes"]))

    cat_bias = {}
    for cat, pairs in by_cat.items():
        if len(pairs) < min_samples:
            continue
        pred = [p for p, _ in pairs]
        realized = [o for _, o in pairs]
        cat_bias[cat] = {
            "n": len(pairs),
            "mean_pred": round(statistics.mean(pred), 3),
            "realized": round(statistics.mean(realized), 3),
            "bias": round(statistics.mean(realized) - statistics.mean(pred), 3),
        }

    return {
        "n_signals_resolved": len(rows),
        "brier_score": round(brier_total / brier_n, 4) if brier_n else None,
        "table": table,
        "category_bias": cat_bias,
    }


def performance_summary(conn) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) n, SUM(pnl) pnl FROM trades GROUP BY status"
    ).fetchall()
    return {r["status"]: {"count": r["n"], "pnl": r["pnl"]} for r in rows}
