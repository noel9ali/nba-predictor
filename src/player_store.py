"""Storage for the player-data tables: a local SQLite mirror now, Supabase once migrations are applied.

The new tables (migrations/0002+) do not exist in Supabase until Noel applies them, and the agent must not
write to production. So every writer goes through this module:

    NBA_PLAYER_STORE=local     (default) data/player_data/player_data.sqlite, same tables and primary keys
    NBA_PLAYER_STORE=supabase  src/database.py (upsert on the primary key, paginated reads)

`push_local_to_supabase(table)` copies the local rows up later (dry run unless confirmed).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable

import pandas as pd

import config

# SQLite DDL mirroring migrations/*.sql (types simplified: dates/timestamps as ISO text, booleans as 0/1).
SCHEMAS: dict[str, tuple[str, list[str]]] = {
    "players": ("""
        create table if not exists players (
          player_id integer primary key, full_name text not null, first_name text, last_name text,
          position text, birth_date text, is_active integer not null default 0, updated_at text)""",
                ["player_id"]),
    "player_aliases": ("""
        create table if not exists player_aliases (
          provider text not null, provider_name text not null, player_id integer not null, updated_at text,
          primary key (provider, provider_name))""",
                       ["provider", "provider_name"]),
    "player_games": ("""
        create table if not exists player_games (
          game_id text not null, player_id integer not null, team_id integer not null, game_date text not null,
          season text not null, is_home integer not null, started integer, minutes real,
          pts integer, reb integer, oreb integer, dreb integer, ast integer, stl integer, blk integer,
          tov integer, pf integer, fgm integer, fga integer, fg3m integer, fg3a integer, ftm integer, fta integer,
          plus_minus integer, primary key (game_id, player_id))""",
                     ["game_id", "player_id"]),
    "player_absences": ("""
        create table if not exists player_absences (
          game_id text not null, player_id integer not null, team_id integer not null, game_date text not null,
          basis text not null, reason text, typical_minutes real, primary key (game_id, player_id))""",
                        ["game_id", "player_id"]),
}
BOOLEAN_COLUMNS = {"is_active", "is_home", "started"}   # 0/1 locally, boolean in Postgres
INDEXES = [
    "create index if not exists player_games_player_date_idx on player_games (player_id, game_date)",
    "create index if not exists player_games_team_date_idx on player_games (team_id, game_date)",
    "create index if not exists player_absences_team_date_idx on player_absences (team_id, game_date)",
]


def register_table(name: str, ddl: str, primary_key: list[str], indexes: Iterable[str] = ()) -> None:
    """Later phases add their tables here (same DDL-mirrors-migration rule)."""
    SCHEMAS[name] = (ddl, list(primary_key))
    INDEXES.extend(indexes)


def backend() -> str:
    value = os.getenv("NBA_PLAYER_STORE", "local").strip().lower()
    if value not in {"local", "supabase"}:
        raise ValueError("NBA_PLAYER_STORE must be 'local' or 'supabase'")
    return value


_conns: dict[str, sqlite3.Connection] = {}


def local_path() -> str:
    return os.getenv("NBA_PLAYER_LOCAL_DB", config.PLAYER_LOCAL_DB)


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or local_path()
    if path in _conns:
        return _conns[path]
    if path != ":memory:":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("pragma journal_mode=wal") if path != ":memory:" else None
    for ddl, _pk in SCHEMAS.values():
        conn.execute(ddl)
    for idx in INDEXES:
        conn.execute(idx)
    conn.commit()
    _conns[path] = conn
    return conn


def close_all() -> None:
    for conn in _conns.values():
        conn.close()
    _conns.clear()


def _ensure(conn: sqlite3.Connection, table: str) -> None:
    ddl, _pk = SCHEMAS[table]
    conn.execute(ddl)


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def upsert(table: str, rows: list[dict], *, conn: sqlite3.Connection | None = None,
           batch_size: int = 5000) -> int:
    """Insert or update rows on the table's primary key. Returns the number of rows sent."""
    if not rows:
        return 0
    pk = SCHEMAS[table][1]
    if backend() == "supabase" and conn is None:
        from database import upsert_rows

        upsert_rows(table, rows, conflict_columns=pk)
        return len(rows)
    conn = conn or connect()
    _ensure(conn, table)
    columns = list(rows[0].keys())
    updates = [c for c in columns if c not in pk]
    sql = (f"insert into {table} ({', '.join(columns)}) values ({', '.join('?' for _ in columns)}) "
           f"on conflict ({', '.join(pk)}) do ")
    sql += ("update set " + ", ".join(f"{c} = excluded.{c}" for c in updates)) if updates else "nothing"
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        conn.executemany(sql, [tuple(_clean(r.get(c)) for c in columns) for r in batch])
    conn.commit()
    return len(rows)


_OPS = {"eq": "=", "neq": "!=", "gte": ">=", "lte": "<=", "gt": ">", "lt": "<"}


def read(table: str, *, columns: str = "*", filters: Iterable[tuple[str, str, Any]] = (),
         order_by: str | list[str] | None = None, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    filters = list(filters)
    if backend() == "supabase" and conn is None:
        from database import select_rows

        return select_rows(table, columns=columns, filters=filters,
                           order_by=order_by or SCHEMAS[table][1])
    conn = conn or connect()
    _ensure(conn, table)
    where, params = [], []
    for column, op, value in filters:
        if op == "in":
            values = list(value)
            where.append(f"{column} in ({', '.join('?' for _ in values)})")
            params.extend(values)
        elif op == "is" and value in (None, "null"):
            where.append(f"{column} is null")
        elif op == "not_is" and value in (None, "null"):
            where.append(f"{column} is not null")
        else:
            where.append(f"{column} {_OPS[op]} ?")
            params.append(value)
    sql = f"select {columns} from {table}"
    if where:
        sql += " where " + " and ".join(where)
    if order_by:
        sql += " order by " + (order_by if isinstance(order_by, str) else ", ".join(order_by))
    return pd.read_sql_query(sql, conn, params=params)


def count(table: str, *, conn: sqlite3.Connection | None = None) -> int:
    if backend() == "supabase" and conn is None:
        from database import count_rows

        return count_rows(table)
    conn = conn or connect()
    _ensure(conn, table)
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def query(sql: str, params: Iterable[Any] = (), *, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Local-only SQL for heavy batch jobs (backfills); the Supabase backend uses read()."""
    conn = conn or connect()
    for table in SCHEMAS:
        _ensure(conn, table)
    return pd.read_sql_query(sql, conn, params=list(params))


def push_local_to_supabase(table: str, *, dry_run: bool = True, conn: sqlite3.Connection | None = None) -> int:
    """Copy local rows of `table` into Supabase (after its migration is applied). Dry run by default."""
    df = read(table, conn=conn or connect())
    print(f"local {table}: {len(df)} rows")
    if dry_run or df.empty:
        return 0
    from database import upsert_rows

    for column in BOOLEAN_COLUMNS & set(df.columns):
        df[column] = df[column].map(lambda v: None if pd.isna(v) else bool(v))
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    upsert_rows(table, rows, conflict_columns=SCHEMAS[table][1])
    return len(rows)
