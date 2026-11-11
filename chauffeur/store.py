"""SQLite cache of daily ad-level insights."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS insights (
    ad_id TEXT NOT NULL,
    date TEXT NOT NULL,
    account_id TEXT NOT NULL,
    account_name TEXT,
    currency TEXT,
    campaign_id TEXT,
    campaign_name TEXT,
    objective TEXT,
    adset_id TEXT,
    adset_name TEXT,
    ad_name TEXT,
    spend REAL DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    link_clicks INTEGER DEFAULT 0,
    leads REAL DEFAULT 0,
    messages REAL DEFAULT 0,
    video_3s REAL DEFAULT 0,
    thruplays REAL DEFAULT 0,
    actions_json TEXT,
    synced_at TEXT,
    PRIMARY KEY (ad_id, date)
);
CREATE INDEX IF NOT EXISTS idx_insights_account_date ON insights(account_id, date);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    since TEXT,
    until TEXT,
    rows INTEGER,
    status TEXT,
    message TEXT,
    finished_at TEXT
);
"""

COLUMNS = [
    "ad_id", "date", "account_id", "account_name", "currency", "campaign_id",
    "campaign_name", "objective", "adset_id", "adset_name", "ad_name", "spend",
    "impressions", "reach", "clicks", "link_clicks", "leads", "messages",
    "video_3s", "thruplays", "actions_json", "synced_at",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    now = _now()
    placeholders = ",".join("?" for _ in COLUMNS)
    sql = f"INSERT OR REPLACE INTO insights ({','.join(COLUMNS)}) VALUES ({placeholders})"
    batch = [tuple({**r, "synced_at": now}.get(c) for c in COLUMNS) for r in rows]
    with conn:
        conn.executemany(sql, batch)
    return len(batch)


def log_sync(conn: sqlite3.Connection, account_id: str, since: str, until: str, rows: int, status: str, message: str = "") -> None:
    with conn:
        conn.execute(
            "INSERT INTO sync_log (account_id, since, until, rows, status, message, finished_at) VALUES (?,?,?,?,?,?,?)",
            (account_id, since, until, rows, status, message, _now()),
        )


def load_insights(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    with connect(path) as conn:
        df = pd.read_sql_query("SELECT * FROM insights", conn)
    df["date"] = pd.to_datetime(df["date"])
    return df


def last_sync(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with connect(path) as conn:
        return pd.read_sql_query(
            "SELECT account_id, MAX(finished_at) AS last_sync, "
            "SUM(CASE WHEN status='ok' THEN 0 ELSE 1 END) AS errors "
            "FROM sync_log GROUP BY account_id", conn,
        )
