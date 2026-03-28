"""
Database connection and initialization for LiquidityOS.
Supports PostgreSQL (production via DATABASE_URL) and SQLite (local dev fallback).
"""

import os
import json
import sqlite3
import logging
from contextlib import contextmanager

logger = logging.getLogger("liquidityos.db")

DB_PATH = os.environ.get("LIQUIDITYOS_DB_PATH", "liquidityos.db")


def _get_database_url():
    """Read DATABASE_URL at call time (not import time) so env can be set late."""
    url = os.environ.get("DATABASE_URL")
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def is_postgres():
    return bool(_get_database_url())


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
    url = _get_database_url()
    logger.debug("Connecting to PostgreSQL at %s", url.split("@")[-1] if url else "?")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


# ── Postgres cursor wrapper ───────────────────────────────────────────

class _PgCursorWrapper:
    """Wraps a psycopg2 connection+cursor to match the sqlite3 conn interface."""

    def __init__(self, conn):
        import psycopg2.extras
        self._conn = conn
        self._cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        self._cursor.execute(sql, params)
        return self

    def executescript(self, sql):
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


# ── Unified context manager ────────────────────────────────────────────

@contextmanager
def get_db():
    if is_postgres():
        conn = _get_pg_connection()
        wrapper = _PgCursorWrapper(conn)
        try:
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                wrapper._cursor.close()
                conn.close()
            except Exception:
                pass
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


# ── SQL translation ───────────────────────────────────────────────────

def _schema_sqlite_to_pg(sql: str) -> str:
    """Strip SQLite-only pragmas from schema DDL.
    The schema already uses CREATE TABLE IF NOT EXISTS and TEXT types,
    which work in both SQLite and Postgres."""
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
    try:
        with get_db() as conn:
            conn.executescript(SCHEMA_SQL)
        backend = "postgres" if is_postgres() else "sqlite"
        target = _get_database_url().split("@")[-1].split("?")[0] if is_postgres() else DB_PATH
        logger.info("Database initialized (%s: %s)", backend, target)
        print(f"Database initialized ({backend}: {target})")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        print(f"ERROR: Database initialization failed: {e}")
        raise


# ── Row conversion ─────────────────────────────────────────────────────

def dict_from_row(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    for key, value in d.items():
        if isinstance(value, str) and value and value[0] in ('{', '['):
            try:
                d[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
    return d


def rows_to_dicts(rows) -> list:
    return [dict_from_row(r) for r in rows]
