"""
Database connection and initialization for LiquidityOS.
Uses SQLite for development; swap to psycopg2/asyncpg for Postgres in production.
"""

import sqlite3
import os
import json
from contextlib import contextmanager

DB_PATH = os.environ.get("LIQUIDITYOS_DB_PATH", "liquidityos.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Run schema migration to create all tables."""
    from migrations.schema import SCHEMA_SQL
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
    print(f"Database initialized at {DB_PATH}")

def dict_from_row(row) -> dict:
    """Convert a sqlite3.Row to a dict, parsing JSON fields."""
    if row is None:
        return None
    d = dict(row)
    # Auto-parse JSON fields
    for key, value in d.items():
        if isinstance(value, str) and value and value[0] in ('{', '['):
            try:
                d[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
    return d

def rows_to_dicts(rows) -> list:
    return [dict_from_row(r) for r in rows]
