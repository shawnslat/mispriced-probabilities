"""
Database V2 - Enhanced Logging, Paper Trading Resolution, Metrics
"""
import sqlite3
from datetime import datetime
import config


def get_connection():
    """Get database connection."""
    return sqlite3.connect(config.DB_PATH)


def _get_table_columns(cursor, table_name):
    """Return a set of column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_paper_trade_schema(cursor):
    """Apply lightweight migrations for paper_trades."""
    columns = _get_table_columns(cursor, "paper_trades")
    if "side" not in columns:
        cursor.execute("ALTER TABLE paper_trades ADD COLUMN side TEXT DEFAULT 'NO'")


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()

    # Opportunities table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            market_id TEXT NOT NULL,
            market_title TEXT,
            category TEXT,
            quality_score REAL,
            market_price REAL,
            true_prob REAL,
            ev REAL,
            recommended_size REAL,
            outcome TEXT,
            profit REAL,
            executed INTEGER DEFAULT 0
        )
        """
    )

    # Paper trades table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            market_id TEXT NOT NULL,
            market_title TEXT,
            category TEXT,
            size REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            pnl REAL,
            status TEXT DEFAULT 'open',
            close_time TEXT,
            side TEXT DEFAULT 'NO',
            resolved_at TEXT,
            win INTEGER
        )
        """
    )
    _ensure_paper_trade_schema(c)
    
    # Performance metrics table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bankroll REAL,
            daily_pnl REAL,
            total_pnl REAL,
            open_positions INTEGER,
            win_rate REAL,
            avg_ev REAL,
            total_trades INTEGER
        )
        """
    )
    
    # Kill switch events table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS kill_switch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            reason TEXT NOT NULL,
            bankroll REAL,
            daily_loss_pct REAL
        )
        """
    )

    conn.commit()
    conn.close()
    print("✅ Database initialized")


def log_opportunity(market, score, ev, true_prob, size_pct, executed=False):
    """Log an identified opportunity."""
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO opportunities
        (timestamp, market_id, market_title, category, quality_score,
         market_price, true_prob, ev, recommended_size, executed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            market.get("ticker", "unknown"),
            market.get("title", ""),
            market.get("category", "unknown"),
            score,
            market.get("yes_price", 0),
            true_prob,
            ev,
            size_pct,
            1 if executed else 0,
        ),
    )

    conn.commit()
    conn.close()


def log_paper_trade(position):
    """Log a new paper trade."""
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO paper_trades
        (timestamp, market_id, market_title, category, size, entry_price, 
         close_time, side, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            position["market_id"],
            position.get("title", ""),
            position.get("category", "unknown"),
            position["size"],
            position["entry_price"],
            position.get("close_time"),
            position.get("side", "NO"),
            "open",
        ),
    )

    conn.commit()
    conn.close()


def update_paper_trade_result(market_id, result, exit_price):
    """
    Update paper trade with result.
    
    Args:
        market_id: Market ticker
        result: "yes" or "no"
        exit_price: Final market price
    """
    conn = get_connection()
    c = conn.cursor()
    
    # Find open trade for this market
    c.execute(
        """
        SELECT id, size, entry_price, side FROM paper_trades
        WHERE market_id = ? AND status = 'open'
        ORDER BY timestamp DESC LIMIT 1
        """,
        (market_id,)
    )
    
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    
    trade_id, size, entry_price, side = row
    side = (side or "NO").upper()
    safe_entry = max(entry_price, 0.01)
    contracts = size / safe_entry
    win = int((side == "YES" and result == "yes") or (side == "NO" and result == "no"))
    pnl = (contracts - size) if win else -size
    
    # Update trade
    c.execute(
        """
        UPDATE paper_trades
        SET exit_price = ?, pnl = ?, status = 'closed', 
            resolved_at = ?, win = ?
        WHERE id = ?
        """,
        (exit_price, pnl, datetime.now().isoformat(), win, trade_id)
    )
    
    conn.commit()
    conn.close()
    
    return {
        "trade_id": trade_id,
        "market_id": market_id,
        "pnl": pnl,
        "win": win == 1,
        "size": size,
    }


def get_open_paper_trades():
    """Get all open paper trades."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute(
        """
        SELECT id, market_id, market_title, category, size, entry_price, 
               close_time, side, timestamp
        FROM paper_trades
        WHERE status = 'open'
        ORDER BY timestamp DESC
        """
    )
    
    rows = c.fetchall()
    conn.close()
    
    trades = []
    for row in rows:
        trades.append({
            "id": row[0],
            "market_id": row[1],
            "title": row[2],
            "category": row[3],
            "size": row[4],
            "entry_price": row[5],
            "close_time": row[6],
            "side": row[7],
            "timestamp": row[8],
        })
    
    return trades


def get_performance_stats():
    """Calculate performance statistics."""
    conn = get_connection()
    c = conn.cursor()
    
    # Overall stats
    c.execute(
        """
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl,
            COUNT(CASE WHEN status = 'open' THEN 1 END) as open_trades
        FROM paper_trades
        """
    )
    
    row = c.fetchone()
    total_trades = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0
    total_pnl = row[3] or 0.0
    avg_pnl = row[4] or 0.0
    open_trades = row[5] or 0
    
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    # Recent performance (last 20 trades)
    c.execute(
        """
        SELECT AVG(ev) as avg_ev
        FROM opportunities
        WHERE executed = 1
        ORDER BY timestamp DESC
        LIMIT 20
        """
    )
    
    avg_ev_row = c.fetchone()
    avg_ev = (avg_ev_row[0] * 100) if avg_ev_row and avg_ev_row[0] else 0
    
    conn.close()
    
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "avg_ev": avg_ev,
        "open_trades": open_trades,
    }


def log_metrics(bankroll, daily_pnl, total_pnl, open_positions):
    """Log current metrics snapshot."""
    stats = get_performance_stats()
    
    conn = get_connection()
    c = conn.cursor()
    
    c.execute(
        """
        INSERT INTO metrics
        (timestamp, bankroll, daily_pnl, total_pnl, open_positions,
         win_rate, avg_ev, total_trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            bankroll,
            daily_pnl,
            total_pnl,
            len(open_positions),
            stats["win_rate"],
            stats["avg_ev"],
            stats["total_trades"],
        )
    )
    
    conn.commit()
    conn.close()


def log_kill_switch_event(reason, bankroll, daily_loss_pct):
    """Log kill switch activation."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute(
        """
        INSERT INTO kill_switch_events
        (timestamp, reason, bankroll, daily_loss_pct)
        VALUES (?, ?, ?, ?)
        """,
        (datetime.now().isoformat(), reason, bankroll, daily_loss_pct)
    )
    
    conn.commit()
    conn.close()


def print_performance_report():
    """Print formatted performance report."""
    stats = get_performance_stats()
    
    print(f"\n{'='*60}")
    print(f"📈 PERFORMANCE REPORT")
    print(f"{'='*60}")
    print(f"Total Trades: {stats['total_trades']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Win Rate: {stats['win_rate']:.1f}%")
    print(f"Total P&L: ${stats['total_pnl']:+,.2f}")
    print(f"Avg P&L per Trade: ${stats['avg_pnl']:+,.2f}")
    print(f"Avg EV (last 20): {stats['avg_ev']:+.2f}%")
    print(f"Open Trades: {stats['open_trades']}")
    print(f"{'='*60}\n")
