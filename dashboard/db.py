"""SQLite read helpers for the Streamlit dashboard."""

# READ-ONLY DASHBOARD
# LIVE TRADING DISABLED

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

# Get the parent directory (project root) for default database path
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DEFAULT_DB_PATH = _PROJECT_ROOT / "seer.db"


def _resolve_db_path() -> Path:
    env_path = os.getenv("SEER_DB")
    if env_path:
        db_path = Path(env_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path
    return DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    db_path = _resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
    return conn.execute(query, (table,)).fetchone() is not None


def _get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _first_existing_column(columns: set[str], candidates: Iterable[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _read_dataframe(conn: sqlite3.Connection, query: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params)


def get_scanner_status(conn: sqlite3.Connection) -> dict:
    status = "Unknown"
    last_scan = None

    # First check the metrics table (primary source for this scanner)
    if _table_exists(conn, "metrics"):
        row = conn.execute(
            "SELECT timestamp FROM metrics ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            last_scan = row["timestamp"]
            status = "Running"
            return {"status": status, "last_scan_time": last_scan}

    # Fallback to scanner_status table if it exists
    if _table_exists(conn, "scanner_status"):
        columns = _get_table_columns(conn, "scanner_status")
        status_col = _first_existing_column(columns, ["status", "state", "is_running", "running"])
        last_scan_col = _first_existing_column(
            columns,
            ["last_scan_time", "last_scan_at", "last_scan", "last_run", "updated_at", "timestamp"],
        )
        select_cols = [col for col in [status_col, last_scan_col] if col]
        if select_cols:
            query = f"SELECT {', '.join(select_cols)} FROM scanner_status ORDER BY rowid DESC LIMIT 1"
            row = conn.execute(query).fetchone()
            if row is not None:
                if status_col:
                    raw_status = row[status_col]
                    if isinstance(raw_status, (int, float)):
                        status = "Running" if raw_status else "Stopped"
                    elif raw_status:
                        status = str(raw_status).title()
                if last_scan_col:
                    last_scan = row[last_scan_col]

    if last_scan is None:
        last_scan = _latest_timestamp(conn)
        if last_scan is not None and status == "Unknown":
            status = "Running"

    return {"status": status, "last_scan_time": last_scan}


def _latest_timestamp(conn: sqlite3.Connection) -> Optional[str]:
    for table, column in [
        ("scans", "timestamp"),
        ("scanner_runs", "end_time"),
        ("scan_history", "timestamp"),
        ("opportunities", "timestamp"),
    ]:
        if _table_exists(conn, table) and column in _get_table_columns(conn, table):
            query = f"SELECT {column} FROM {table} ORDER BY {column} DESC LIMIT 1"
            row = conn.execute(query).fetchone()
            if row is not None:
                return row[column]
    return None


def get_portfolio_summary(conn: sqlite3.Connection) -> dict:
    summary = {
        "paper_bankroll": None,
        "total_pnl": None,
        "total_trades": 0,
        "win_rate": None,
        "open_positions": 0,
    }

    # Primary: use metrics table which has current state
    if _table_exists(conn, "metrics"):
        row = conn.execute(
            "SELECT bankroll, total_pnl, total_trades, win_rate, open_positions FROM metrics ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            summary["paper_bankroll"] = row["bankroll"]
            summary["total_pnl"] = row["total_pnl"]
            summary["total_trades"] = row["total_trades"]
            summary["win_rate"] = row["win_rate"]
            summary["open_positions"] = row["open_positions"]
            return summary

    # Fallback to paper_account table
    if _table_exists(conn, "paper_account"):
        columns = _get_table_columns(conn, "paper_account")
        bankroll_col = _first_existing_column(columns, ["bankroll", "balance", "equity"])
        if bankroll_col:
            row = conn.execute(
                f"SELECT {bankroll_col} FROM paper_account ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                summary["paper_bankroll"] = row[bankroll_col]

    if _table_exists(conn, "paper_trades"):
        columns = _get_table_columns(conn, "paper_trades")
        pnl_col = _first_existing_column(columns, ["pnl", "profit", "realized_pnl"])
        if pnl_col:
            row = conn.execute(f"SELECT SUM({pnl_col}) AS total_pnl FROM paper_trades").fetchone()
            if row is not None:
                summary["total_pnl"] = row["total_pnl"]
        row = conn.execute("SELECT COUNT(*) AS total_trades FROM paper_trades").fetchone()
        if row is not None:
            summary["total_trades"] = row["total_trades"]

    return summary


def get_recent_scans(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    # Primary: use metrics table which logs each scan run
    if _table_exists(conn, "metrics"):
        return _read_dataframe(
            conn,
            "SELECT timestamp, bankroll, total_pnl, open_positions, win_rate, avg_ev, total_trades FROM metrics ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    if _table_exists(conn, "scans"):
        return _read_dataframe(
            conn,
            "SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    if _table_exists(conn, "scanner_runs"):
        return _read_dataframe(
            conn,
            "SELECT * FROM scanner_runs ORDER BY start_time DESC LIMIT ?",
            (limit,),
        )

    if _table_exists(conn, "scan_history"):
        return _read_dataframe(
            conn,
            "SELECT * FROM scan_history ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    if _table_exists(conn, "opportunities"):
        columns = _get_table_columns(conn, "opportunities")
        if "timestamp" in columns:
            return _read_dataframe(
                conn,
                "SELECT DISTINCT timestamp FROM opportunities ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )

    return pd.DataFrame()


def get_opportunities(conn: sqlite3.Connection, limit: int = 250) -> pd.DataFrame:
    if not _table_exists(conn, "opportunities"):
        return pd.DataFrame()
    return _read_dataframe(
        conn,
        "SELECT * FROM opportunities ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )


def get_watchlist(conn: sqlite3.Connection, limit: int = 250) -> pd.DataFrame:
    for table in ["watch_list", "watchlist", "watch_list_items", "watchlist_items"]:
        if _table_exists(conn, table):
            query = f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?"
            return _read_dataframe(conn, query, (limit,))
    return pd.DataFrame()


def get_opportunity_timeseries(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    if not _table_exists(conn, "opportunities"):
        return pd.DataFrame()
    columns = _get_table_columns(conn, "opportunities")
    if "timestamp" not in columns:
        return pd.DataFrame()
    value_col = _first_existing_column(columns, ["ev", "quality_score", "market_price", "true_prob"])
    if not value_col:
        return pd.DataFrame()
    query = (
        "SELECT timestamp, {value_col} AS metric "
        "FROM opportunities ORDER BY timestamp DESC LIMIT ?"
    ).format(value_col=value_col)
    df = _read_dataframe(conn, query, (limit,))
    return df.sort_values("timestamp")


def get_trade_pnl_timeseries(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    if not _table_exists(conn, "paper_trades"):
        return pd.DataFrame()
    columns = _get_table_columns(conn, "paper_trades")
    time_col = _first_existing_column(columns, ["timestamp", "exit_time", "created_at"])
    pnl_col = _first_existing_column(columns, ["pnl", "profit", "realized_pnl"])
    if not time_col or not pnl_col:
        return pd.DataFrame()
    query = (
        "SELECT {time_col} AS timestamp, {pnl_col} AS pnl "
        "FROM paper_trades ORDER BY {time_col} DESC LIMIT ?"
    ).format(time_col=time_col, pnl_col=pnl_col)
    df = _read_dataframe(conn, query, (limit,))
    return df.sort_values("timestamp")

