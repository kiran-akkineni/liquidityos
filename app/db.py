"""
Database connection and initialization for LiquidityOS.
Supports PostgreSQL (production via DATABASE_URL) and SQLite (local dev fallback).

The adapter layer normalizes differences:
  - SQLite uses ? placeholders; Postgres uses %s
  - SQLite has executescript; Postgres uses execute for DDL
  - Both return dict-like rows
"""

import os
import re
import json
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("LIQUIDITYOS_DB_PATH", "liquidityos.db")

_using_postgres = bool(DATABASE_URL)


# ── Connection factories ───────────────────────────────────────────────

def _get_sqlite_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _get_pg_connection():
    import psycopg2
    import psycopg2.extras
    url = DATABASE_URL
    # Railway sometimes uses postgres:// which psycopg2 needs as postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def get_connection():
    if _using_postgres:
        return _get_pg_connection()
    return _get_sqlite_connection()


# ── Unified context manager ────────────────────────────────────────────

class _PgCursorWrapper:
    """Wraps a psycopg2 cursor to normalize the interface with sqlite3."""

    def __init__(self, conn):
        import psycopg2.extras
        self._conn = conn
        self._cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=None):
        sql = _sqlite_to_pg(sql)
        self._cursor.execute(sql, params)
        return self

    def executescript(self, sql):
        """Execute a multi-statement SQL script."""
        sql = _schema_sqlite_to_pg(sql)
        self._cursor.execute(sql)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._cursor.close()
        self._conn.close()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid if hasattr(self._cursor, 'lastrowid') else None


@contextmanager
def get_db():
    if _using_postgres:
        conn = _get_pg_connection()
        wrapper = _PgCursorWrapper(conn)
        try:
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            wrapper._cursor.close()
            conn.close()
    else:
        conn = _get_sqlite_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ── SQL translation helpers ────────────────────────────────────────────

def _sqlite_to_pg(sql: str) -> str:
    """Convert SQLite-style ? placeholders to Postgres %s."""
    return sql.replace("?", "%s")


def _schema_sqlite_to_pg(sql: str) -> str:
    """Convert SQLite schema DDL to Postgres-compatible DDL."""
    # Replace ? with %s
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    # TEXT is fine in Postgres
    # REAL → DOUBLE PRECISION (TEXT/REAL both work, keep as-is for simplicity)
    # Remove IF NOT EXISTS on indexes (Postgres supports it)
    # Remove PRAGMA statements
    lines = []
    for line in sql.split("\n"):
        stripped = line.strip().upper()
        if stripped.startswith("PRAGMA"):
            continue
        lines.append(line)
    return "\n".join(lines)


# ── Database initialization ────────────────────────────────────────────

def init_db():
    """Run schema migration to create all tables."""
    from migrations.schema import SCHEMA_SQL
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
    db_label = DATABASE_URL.split("@")[-1].split("/")[-1] if _using_postgres else DB_PATH
    print(f"Database initialized at {db_label} ({'postgres' if _using_postgres else 'sqlite'})")


# ── Row conversion ─────────────────────────────────────────────────────

def dict_from_row(row) -> dict:
    """Convert a row to a dict, parsing JSON fields."""
    if row is None:
        return None
    if isinstance(row, dict):
        d = row
    else:
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
