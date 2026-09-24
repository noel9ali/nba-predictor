"""Server-side Supabase data access for the NBA prediction pipeline."""

from __future__ import annotations

import os
import math
from datetime import date, datetime
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client


DEFAULT_BATCH_SIZE = 500


class DatabaseError(RuntimeError):
    """Application-level database failure with safe diagnostic context."""


class DuplicateRecordError(DatabaseError):
    """A write violated a database uniqueness constraint."""


class MissingTableError(DatabaseError):
    """The target table does not exist yet (a migration hasn't been applied)."""


class MissingColumnError(DatabaseError):
    """The target column does not exist yet (a migration hasn't been applied)."""


_client: Client | None = None


def get_client() -> Client:
    """Return the process-wide server-only Supabase client."""
    global _client
    if _client is not None:
        return _client

    load_dotenv()
    url = os.getenv("SUPABASE_URL", "").strip()
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret_key:
        raise DatabaseError(
            "Supabase configuration is missing: set SUPABASE_URL and "
            "SUPABASE_SECRET_KEY in the server environment"
        )

    try:
        _client = create_client(url, secret_key)
    except Exception as exc:
        raise DatabaseError("Failed to initialize the Supabase client") from exc
    return _client


def _error_details(error: Any) -> tuple[str, str]:
    code = getattr(error, "code", "") or ""
    message = getattr(error, "message", "") or ""
    if isinstance(error, Mapping):
        code = error.get("code", code) or ""
        message = error.get("message", message) or ""
    return str(code), str(message)


def _raise_for_error(operation: str, error: Any) -> None:
    code, message = _error_details(error)
    safe_message = f"{operation} failed"
    if code == "23505":
        raise DuplicateRecordError(safe_message) from None
    if code == "42P10":
        raise DatabaseError(
            f"{safe_message}: configured upsert conflict target is not backed "
            "by a database unique constraint"
        ) from None
    if code in ("PGRST205", "42P01"):
        raise MissingTableError(
            f"{safe_message}: table is missing; apply supabase/migrations"
        ) from None
    if code in ("PGRST204", "42703"):
        raise MissingColumnError(
            f"{safe_message}: column is missing; apply supabase/migrations"
        ) from None
    raise DatabaseError(f"{safe_message} ({code})" if code else safe_message) from None


def _raise_response_error(operation: str, response: Any) -> None:
    error = getattr(response, "error", None)
    if not error:
        return
    _raise_for_error(operation, error)


def _run(operation: str, callback):
    try:
        response = callback()
    except DatabaseError:
        raise
    except APIError as exc:
        _raise_for_error(operation, exc)
    except Exception as exc:
        raise DatabaseError(f"{operation} failed") from exc
    _raise_response_error(operation, response)
    return response


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if not hasattr(missing, "__len__") and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    return value


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {column: _normalize_value(value) for column, value in row.items()}
        for row in rows
    ]


def _apply_filters(query, filters: Iterable[tuple[str, str, Any]]):
    for column, operator, value in filters:
        if operator == "eq":
            query = query.eq(column, value)
        elif operator == "neq":
            query = query.neq(column, value)
        elif operator == "is":
            query = query.is_(column, value)
        elif operator == "not_is":
            query = query.not_.is_(column, value)
        elif operator == "gte":
            query = query.gte(column, value)
        elif operator == "lte":
            query = query.lte(column, value)
        elif operator == "lt":
            query = query.lt(column, value)
        elif operator == "gt":
            query = query.gt(column, value)
        elif operator == "ilike":
            query = query.ilike(column, value)
        elif operator == "in":
            if isinstance(value, str) or not value:
                raise ValueError('The "in" filter requires a non-empty, non-string list of values')
            query = query.in_(column, list(value))
        else:
            raise ValueError(f"Unsupported database filter operator: {operator}")
    return query


def _normalize_order_columns(
    order_by: str | tuple[str, bool] | Iterable[str | tuple[str, bool]] | None,
) -> list[tuple[str, bool | None]]:
    if order_by is None:
        items: list[Any] = []
    elif isinstance(order_by, str) or (
        isinstance(order_by, tuple) and len(order_by) == 2 and isinstance(order_by[1], bool)
    ):
        items = [order_by]
    else:
        items = list(order_by)

    normalized: list[tuple[str, bool | None]] = []
    for item in items:
        if isinstance(item, tuple):
            column, desc = item
            normalized.append((column, bool(desc)))
        else:
            normalized.append((item, None))
    return normalized


def select_rows(
    table: str,
    *,
    columns: str = "*",
    filters: Iterable[tuple[str, str, Any]] = (),
    order_by: str | Iterable[str] | None = None,
    descending: bool = False,
    limit: int | None = None,
    page_size: int = 1000,
) -> pd.DataFrame:
    """Read a table through PostgREST, paginating large result sets."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    if limit is None and order_by is None:
        raise ValueError(
            f"Reading {table} requires a deterministic order when pagination is enabled"
        )
    order_columns = _normalize_order_columns(order_by)
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch_limit = page_size if limit is None else min(page_size, limit - len(rows))

        def request():
            query = get_client().table(table).select(columns)
            query = _apply_filters(query, filters)
            for order_column, order_desc in order_columns:
                query = query.order(
                    order_column, desc=descending if order_desc is None else order_desc
                )
            return query.range(offset, offset + batch_limit - 1).execute()

        if limit is not None and len(rows) >= limit:
            break
        response = _run(f"Reading {table}", request)
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
    return pd.DataFrame(rows)


def insert_rows(
    table: str,
    rows: list[dict[str, Any]],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Insert explicit row dictionaries in bounded batches."""
    if not rows:
        return []
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    rows = _normalize_rows(rows)
    inserted: list[dict[str, Any]] = []
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        response = _run(
            f"Inserting rows into {table}",
            lambda batch=batch: get_client().table(table).insert(batch).execute(),
        )
        inserted.extend(response.data or [])
    return inserted


def upsert_rows(
    table: str,
    rows: list[dict[str, Any]],
    *,
    conflict_columns: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Idempotently upsert explicit row dictionaries in bounded batches."""
    if not rows:
        return []
    if not conflict_columns:
        raise ValueError("conflict_columns must not be empty")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    rows = _normalize_rows(rows)
    inserted: list[dict[str, Any]] = []
    conflict_target = ",".join(conflict_columns)
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        response = _run(
            f"Upserting rows into {table}",
            lambda batch=batch: get_client()
            .table(table)
            .upsert(batch, on_conflict=conflict_target)
            .execute(),
        )
        inserted.extend(response.data or [])
    return inserted


def update_rows(
    table: str,
    values: dict[str, Any],
    *,
    filters: Iterable[tuple[str, str, Any]],
) -> list[dict[str, Any]]:
    """Update rows matching structured filters and return changed rows."""
    if not values:
        raise ValueError("values must not be empty")

    def request():
        query = get_client().table(table).update(values)
        return _apply_filters(query, filters).execute()

    response = _run(f"Updating {table}", request)
    return response.data or []


def select_page(
    table: str,
    *,
    columns: str = "*",
    filters: Iterable[tuple[str, str, Any]] = (),
    order_by: str | tuple[str, bool] | Iterable[str | tuple[str, bool]],
    descending: bool = False,
    offset: int = 0,
    limit: int = 25,
) -> tuple[pd.DataFrame, int]:
    """Read one page of a table plus the total matching row count in a single request."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    order_columns = _normalize_order_columns(order_by)
    if not order_columns:
        raise ValueError(f"Reading a page of {table} requires order_by")

    def request():
        query = get_client().table(table).select(columns, count="exact")
        query = _apply_filters(query, filters)
        for order_column, order_desc in order_columns:
            query = query.order(order_column, desc=descending if order_desc is None else order_desc)
        return query.range(offset, offset + limit - 1).execute()

    response = _run(f"Reading a page of {table}", request)
    return pd.DataFrame(response.data or []), response.count or 0


def count_rows(table: str, *, filters: Iterable[tuple[str, str, Any]] = ()) -> int:
    """Count rows matching structured filters without transferring row data."""

    def request():
        query = get_client().table(table).select("*", count="exact", head=True)
        return _apply_filters(query, filters).execute()

    response = _run(f"Counting {table}", request)
    return response.count or 0


def call_rpc(function: str, params: dict[str, Any]) -> pd.DataFrame:
    """Call a Postgres function exposed through PostgREST and return its rows."""
    response = _run(
        f"Calling {function}",
        lambda: get_client().rpc(function, params).execute(),
    )
    return pd.DataFrame(response.data or [])


def schema_v2_enabled() -> bool:
    """Whether the migrated (v2) Supabase schema is in use."""
    return os.getenv("NBA_SCHEMA_V2", "false").strip().lower() in {"1", "true", "yes"}


def normalize_game_id(value: Any) -> str:
    """Normalize an NBA game id to the 10-character, zero-padded text form."""
    if value is None:
        raise ValueError("game_id must not be None")
    if isinstance(value, str):
        return value.strip().zfill(10)
    return str(int(value)).zfill(10)
