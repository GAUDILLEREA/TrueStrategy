"""Base SQLite locale : journal des signaux, ordres, trades et événements."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, level TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL, data TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, symbol TEXT, strategy TEXT, direction TEXT, entry REAL, sl REAL, tp REAL,
    accepted INTEGER, reasons TEXT, mode TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    client_id TEXT PRIMARY KEY,          -- clé d'idempotence : empêche les ordres dupliqués
    ts TEXT NOT NULL, symbol TEXT, direction TEXT, lots REAL, entry REAL, sl REAL, tp REAL,
    status TEXT, broker_ticket TEXT, account_type TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    open_ts TEXT, close_ts TEXT, symbol TEXT, strategy TEXT, direction TEXT, lots REAL,
    entry REAL, exit REAL, pnl REAL, account_type TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def log_event(self, level: str, category: str, message: str, data: dict | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO events(ts, level, category, message, data) VALUES (?,?,?,?,?)",
                      (_now(), level, category, message, json.dumps(data, default=str) if data else None))

    def log_signal(self, symbol: str, strategy: str, direction: str, entry: float | None, sl: float | None,
                   tp: float | None, accepted: bool, reasons: list[str], mode: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO signals(ts, symbol, strategy, direction, entry, sl, tp, accepted, reasons, mode)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (_now(), symbol, strategy, direction, entry, sl, tp, int(accepted),
                       json.dumps(reasons, ensure_ascii=False), mode))

    def register_order(self, client_id: str, **fields: Any) -> bool:
        """Enregistre un ordre. Renvoie False si cet identifiant existe déjà (ordre dupliqué)."""
        cols = ["client_id", "ts"] + list(fields)
        vals = [client_id, _now()] + list(fields.values())
        try:
            with self._conn() as c:
                c.execute(f"INSERT INTO orders({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
            return True
        except sqlite3.IntegrityError:
            return False

    def update_order(self, client_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE orders SET {sets} WHERE client_id=?", [*fields.values(), client_id])

    def read(self, table: str, limit: int = 200) -> pd.DataFrame:
        if table not in ("events", "signals", "orders", "trades"):
            raise ValueError(table)
        with self._conn() as c:
            order = "ts" if table != "trades" else "id"
            return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", c, params=(limit,))
