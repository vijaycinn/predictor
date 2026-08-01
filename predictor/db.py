"""SQLite persistence: markets, snapshots, features, signals, trades, outcomes."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT,
    slug TEXT,
    category TEXT,
    event_id TEXT,
    end_date TEXT,
    created_at TEXT,
    volume REAL,
    liquidity REAL,
    open_interest REAL,
    outcomes TEXT,
    outcome_prices TEXT,
    clob_token_ids TEXT,
    active INTEGER,
    closed INTEGER,
    last_seen REAL
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT,
    ts REAL,
    best_bid REAL, best_ask REAL, mid REAL, spread REAL,
    bid_depth REAL, ask_depth REAL, imbalance REAL,
    last_trade_price REAL,
    volume_24h REAL, open_interest REAL,
    top_bid_size REAL, top_ask_size REAL,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT,
    ts REAL,
    features_json TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT,
    ts REAL,
    side TEXT,
    action TEXT,
    prob_yes REAL,
    confidence REAL,
    confidence_tier TEXT,
    ev_raw REAL,
    ev_net REAL,
    edge REAL,
    market_price REAL,
    reasoning TEXT,
    metrics_json TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    condition_id TEXT,
    side TEXT,
    action TEXT,
    size REAL,
    limit_price REAL,
    fill_price REAL,
    slippage REAL,
    status TEXT,
    created_at REAL,
    resolved INTEGER DEFAULT 0,
    pnl REAL,
    exchange_order_id TEXT,
    order_status TEXT,
    requested_size REAL,
    filled_size REAL,
    ttl_expires_at REAL
);

CREATE TABLE IF NOT EXISTS outcomes (
    condition_id TEXT PRIMARY KEY,
    resolved_at REAL,
    result_yes INTEGER,
    final_price REAL
);

CREATE TABLE IF NOT EXISTS blocked_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    condition_id TEXT,
    side TEXT,
    reason TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT,
    question TEXT,
    side TEXT,
    size REAL,
    limit_price REAL,
    price_side REAL,
    ev_net REAL,
    confidence REAL,
    prob_yes REAL,
    created_at REAL,
    status TEXT DEFAULT 'PENDING',
    decided_at REAL,
    executed_trade_id INTEGER,
    note TEXT,
    llm_override REAL
);

CREATE INDEX IF NOT EXISTS idx_prop_status ON proposals(status, created_at);

CREATE INDEX IF NOT EXISTS idx_snap_cond ON orderbook_snapshots(condition_id, ts);
CREATE INDEX IF NOT EXISTS idx_sig_cond ON signals(condition_id, ts);
CREATE INDEX IF NOT EXISTS idx_sig_action ON signals(action);
CREATE INDEX IF NOT EXISTS idx_trades_cond ON trades(condition_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # backward-compat column adds for older DBs
    for col in ("llm_override",):
        try:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass
    for col in ("exchange_order_id TEXT", "order_status TEXT", "requested_size REAL",
                "filled_size REAL", "ttl_expires_at REAL"):
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def upsert_market(conn: sqlite3.Connection, m: dict) -> None:
    conn.execute(
        """INSERT INTO markets (condition_id, question, slug, category, event_id,
           end_date, created_at, volume, liquidity, open_interest, outcomes,
           outcome_prices, clob_token_ids, active, closed, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(condition_id) DO UPDATE SET
             question=excluded.question, slug=excluded.slug, category=excluded.category,
             event_id=excluded.event_id, end_date=excluded.end_date,
             volume=excluded.volume, liquidity=excluded.liquidity,
             open_interest=excluded.open_interest, outcomes=excluded.outcomes,
             outcome_prices=excluded.outcome_prices, clob_token_ids=excluded.clob_token_ids,
             active=excluded.active, closed=excluded.closed, last_seen=excluded.last_seen""",
        (
            m["condition_id"], m.get("question"), m.get("slug"), m.get("category"),
            m.get("event_id"), m.get("end_date"), m.get("created_at"),
            m.get("volume"), m.get("liquidity"), m.get("open_interest"),
            json.dumps(m.get("outcomes", [])), json.dumps(m.get("outcome_prices", [])),
            json.dumps(m.get("clob_token_ids", [])),
            1 if m.get("active") else 0, 1 if m.get("closed") else 0,
            time.time(),
        ),
    )
    conn.commit()


def insert_snapshot(conn, condition_id: str, snap: dict) -> None:
    conn.execute(
        """INSERT INTO orderbook_snapshots (condition_id, ts, best_bid, best_ask, mid,
           spread, bid_depth, ask_depth, imbalance, last_trade_price, volume_24h,
           open_interest, top_bid_size, top_ask_size)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            condition_id, snap.get("ts", time.time()), snap.get("best_bid"),
            snap.get("best_ask"), snap.get("mid"), snap.get("spread"),
            snap.get("bid_depth"), snap.get("ask_depth"), snap.get("imbalance"),
            snap.get("last_trade_price"), snap.get("volume_24h"),
            snap.get("open_interest"), snap.get("top_bid_size"), snap.get("top_ask_size"),
        ),
    )
    conn.commit()


def insert_features(conn, condition_id: str, features: dict) -> int:
    cur = conn.execute(
        "INSERT INTO features (condition_id, ts, features_json) VALUES (?,?,?)",
        (condition_id, time.time(), json.dumps(features, default=str)),
    )
    conn.commit()
    return cur.lastrowid


def insert_signal(conn, sig: dict) -> int:
    cur = conn.execute(
        """INSERT INTO signals (condition_id, ts, side, action, prob_yes, confidence,
           confidence_tier, ev_raw, ev_net, edge, market_price, reasoning, metrics_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sig["condition_id"], sig.get("ts", time.time()), sig["side"],
            sig["action"], sig.get("prob_yes"), sig.get("confidence"),
            sig.get("confidence_tier"), sig.get("ev_raw"), sig.get("ev_net"),
            sig.get("edge"), sig.get("market_price"), sig.get("reasoning"),
            json.dumps(sig.get("metrics_snapshot", {}), default=str),
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_trade(conn, trade: dict) -> int:
    cur = conn.execute(
        """INSERT INTO trades (signal_id, condition_id, side, action, size, limit_price,
           fill_price, slippage, status, created_at, exchange_order_id, order_status,
           requested_size, filled_size, ttl_expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            trade.get("signal_id"), trade["condition_id"], trade["side"],
            trade.get("action", "BUY"), trade.get("size"), trade.get("limit_price"),
            trade.get("fill_price"), trade.get("slippage"), trade.get("status"),
            trade.get("created_at", time.time()), trade.get("exchange_order_id"),
            trade.get("order_status"), trade.get("requested_size"), trade.get("filled_size"),
            trade.get("ttl_expires_at"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_trade(conn, trade_id: int, fields: dict) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE trades SET {sets} WHERE id=?", (*fields.values(), trade_id))
    conn.commit()


def resting_orders(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM trades WHERE status='RESTING' ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def block_trade(conn, condition_id: str, side: str, reason: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO blocked_trades (ts, condition_id, side, reason, detail) VALUES (?,?,?,?,?)",
        (time.time(), condition_id, side, reason, detail),
    )
    conn.commit()

def set_market_resolved(conn, condition_id: str, result_yes: int, final_price: float) -> None:
    conn.execute(
        """INSERT INTO outcomes (condition_id, resolved_at, result_yes, final_price)
           VALUES (?,?,?,?)
           ON CONFLICT(condition_id) DO UPDATE SET
             resolved_at=excluded.resolved_at, result_yes=excluded.result_yes,
             final_price=excluded.final_price""",
        (condition_id, time.time(), result_yes, final_price),
    )
    conn.execute("UPDATE markets SET closed=1 WHERE condition_id=?", (condition_id,))
    conn.commit()


def open_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT t.*, m.question, m.category, m.condition_id as cid
           FROM trades t JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.status='OPEN' ORDER BY t.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_trade_pnl(conn, condition_id: str, result_yes: int) -> float:
    """P&L per open trade on a resolved market. Yes shares pay $1 if result_yes=1."""
    total = 0.0
    for t in conn.execute(
        "SELECT * FROM trades WHERE condition_id=? AND status='OPEN'", (condition_id,)
    ).fetchall():
        price = t["fill_price"] if t["fill_price"] is not None else t["limit_price"]
        if t["side"] == "YES":
            payout = 1.0 if result_yes else 0.0
        else:  # NO
            payout = 0.0 if result_yes else 1.0
        pnl = (payout - price) * t["size"]
        total += pnl
        conn.execute(
            "UPDATE trades SET status='CLOSED', resolved=1, pnl=? WHERE id=?",
            (pnl, t["id"]),
        )
    conn.commit()
    return total


def insert_proposal(conn, p: dict) -> int:
    cur = conn.execute(
        """INSERT INTO proposals (condition_id, question, side, size, limit_price,
           price_side, ev_net, confidence, prob_yes, created_at, status, note, llm_override)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            p["condition_id"], p.get("question"), p["side"], p.get("size"),
            p.get("limit_price"), p.get("price_side"), p.get("ev_net"),
            p.get("confidence"), p.get("prob_yes"), p.get("created_at", time.time()),
            p.get("status", "PENDING"), p.get("note", ""), p.get("llm_override"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_proposal(conn, pid: int) -> dict | None:
    r = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def pending_proposals(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM proposals WHERE status='PENDING' ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def set_proposal_status(conn, pid: int, status: str, note: str = "", trade_id: int | None = None) -> None:
    conn.execute(
        """UPDATE proposals SET status=?, decided_at=?, note=?, executed_trade_id=COALESCE(?, executed_trade_id)
           WHERE id=?""",
        (status, time.time(), note, trade_id, pid),
    )
    conn.commit()


def expire_stale_proposals(conn, ttl_hours: float = 2.0) -> int:
    cutoff = time.time() - ttl_hours * 3600
    cur = conn.execute(
        "UPDATE proposals SET status='EXPIRED', decided_at=? WHERE status='PENDING' AND created_at < ?",
        (time.time(), cutoff),
    )
    conn.commit()
    return cur.rowcount
