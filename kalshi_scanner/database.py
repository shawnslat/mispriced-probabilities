import sqlite3
from datetime import datetime


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect("kalshi_scanner.db")
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            market_id TEXT,
            market_title TEXT,
            category TEXT,
            quality_score REAL,
            market_price REAL,
            true_prob REAL,
            ev REAL,
            recommended_size REAL,
            outcome TEXT,
            profit REAL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            market_id TEXT,
            size REAL,
            entry_price REAL,
            exit_price REAL NULL,
            pnl REAL NULL
        )
        """
    )

    conn.commit()
    conn.close()


def log_opportunity(market, score, ev, true_prob, size_pct):
    """Log opportunity for later analysis."""
    conn = sqlite3.connect("kalshi_scanner.db")
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO opportunities
        (timestamp, market_id, market_title, category, quality_score,
         market_price, true_prob, ev, recommended_size, outcome, profit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            market["ticker"],
            market["title"],
            market.get("category", "unknown"),
            score,
            market["yes_price"],
            true_prob,
            ev,
            size_pct,
            None,
            None,
        ),
    )

    conn.commit()
    conn.close()


def log_paper_trade(position):
    """Log a simulated trade."""
    conn = sqlite3.connect("kalshi_scanner.db")
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO paper_trades
        (timestamp, market_id, size, entry_price, exit_price, pnl)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            position["market_id"],
            position["size"],
            position["entry_price"],
            position.get("exit_price"),
            position.get("pnl"),
        ),
    )

    conn.commit()
    conn.close()
