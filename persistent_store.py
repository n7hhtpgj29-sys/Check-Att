"""V12.1.1: durable main data, with the original V12.1 SQL/API retained.

PostgreSQL is required on Render by default. Broken/missing credentials do NOT
silently select a new SQLite database. SQLite is for local development only.
All PostgreSQL tables live in cc_attendance, outside Supabase's public Data API.
"""
from __future__ import annotations
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = 'cc_attendance'
WRITE_LOCK = 121100926

class DatabaseUnavailable(RuntimeError):
    pass

class CompatRow(dict):
    """Support both sqlite.Row-style integer lookup and dict(row)."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)

def compat_row_factory(cursor):
    names = [c.name for c in (cursor.description or ())]
    return lambda values: CompatRow(zip(names, values))

def pg_sql(query: str, has_parameters: bool = True) -> str:
    """Translate this app's SQLite qmark parameters without touching literals."""
    ignore = bool(re.match(r'\s*INSERT\s+OR\s+IGNORE\s+', query, re.I))
    query = re.sub(r'^(\s*)INSERT\s+OR\s+IGNORE\s+', r'\1INSERT ', query, flags=re.I)
    out, quoted, i = [], False, 0
    while i < len(query):
        ch = query[i]
        if ch == "'":
            if quoted and i + 1 < len(query) and query[i + 1] == "'":
                out.append("''"); i += 2; continue
            quoted = not quoted
        if ch == '?' and not quoted:
            out.append('%s')
        elif ch == '%' and has_parameters:
            out.append('%%')
        else:
            out.append(ch)
        i += 1
    result = ''.join(out).rstrip().rstrip(';')
    if ignore:
        result += ' ON CONFLICT DO NOTHING'
    return result

class Tx:
    def __init__(self, conn, postgres: bool):
        self.conn, self.postgres = conn, postgres
        self._locked = False
    def write_lock(self):
        if self.postgres and not self._locked:
            self.conn.execute('SELECT pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
        self._locked = True
    def execute(self, query, params=()):
        if self.postgres:
            m = re.fullmatch(r'\s*PRAGMA table_info\((\w+)\)\s*;?\s*', query, re.I)
            if m:
                return self.conn.execute(
                    'SELECT ordinal_position-1 AS cid, column_name AS name '
                    'FROM information_schema.columns WHERE table_schema=%s AND table_name=%s '
                    'ORDER BY ordinal_position', (SCHEMA, m.group(1)))
            return self.conn.execute(pg_sql(query, bool(params)), params if params else None)
        return self.conn.execute(query, params)

class Store:
    def __init__(self, url: str, sqlite_path):
        self.url = (url or '').strip()
        self.path = Path(sqlite_path)
        self.postgres = bool(self.url)
        required = os.getenv('REQUIRE_POSTGRES', 'true' if os.getenv('RENDER') else 'false')
        self.required = required.lower() in ('1', 'true', 'yes')
        if self.required and not self.postgres:
            raise DatabaseUnavailable('DATABASE_URL is required. No empty local database was created.')
        if self.url and not self.url.startswith(('postgres://', 'postgresql://')):
            raise DatabaseUnavailable('DATABASE_URL must be a PostgreSQL connection string, not an API URL.')
        self._ready = False
        self._init_lock = threading.Lock()
    @property
    def kind(self):
        return 'postgres' if self.postgres else 'sqlite-local'
    def _connect_pg(self):
        try:
            import psycopg
            return psycopg.connect(self.url, row_factory=compat_row_factory,
                                   connect_timeout=10, prepare_threshold=None,
                                   application_name='cc-attendance-v1211')
        except Exception:
            # Deliberately hide DSN/password even if a driver error includes one.
            raise DatabaseUnavailable('PostgreSQL unavailable. Check DATABASE_URL or resume the database project.') from None
    def _schema(self):
        if self._ready: return
        with self._init_lock:
            if self._ready: return
            c = self._connect_pg()
            try:
                c.execute("SET LOCAL statement_timeout='15000ms'")
                c.execute('SELECT pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
                c.execute(f'CREATE SCHEMA IF NOT EXISTS {SCHEMA}')
                c.execute(f'REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC')
                c.commit(); self._ready = True
            except Exception:
                c.rollback()
                raise DatabaseUnavailable('Unable to initialize database schema. Check the database user permissions.') from None
            finally:
                c.close()
    @contextmanager
    def pg_tx(self):
        self._schema()
        c = self._connect_pg()
        try:
            c.execute(f'SET LOCAL search_path TO {SCHEMA},pg_catalog')
            c.execute("SET LOCAL statement_timeout='15000ms'")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    @contextmanager
    def tx(self, serial=False):
        if self.postgres:
            with self.pg_tx() as c:
                t = Tx(c, True)
                if serial: t.write_lock()
                yield t
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA busy_timeout=15000')
            # Local/test mode: serialize writes, including read-modify-write imports.
            c.execute('BEGIN IMMEDIATE')
            yield Tx(c, False)
            c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.close()
    def ping(self):
        with self.tx() as t:
            return t.execute('SELECT 1').fetchone()[0] == 1
