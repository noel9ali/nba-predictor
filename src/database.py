"""Server-side Supabase data access for the NBA prediction pipeline."""

from __future__ import annotations

import os
import math
from datetime import date, datetime
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client


DEFAULT_BATCH_SIZE = 500


class DatabaseError(RuntimeError):
    """Application-level database failure with safe diagnostic context."""


class DuplicateRecordError(DatabaseError):
    """A write violated a database uniqueness constraint."""


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


def _raise_response_error(operation: str, response: Any) -> None:
    error = getattr(response, "error", None)
    if not error:
        return
    code, message = _error_details(error)
    safe_message = f"{operation} failed"
    if code == "23505":
        raise DuplicateRecordError(safe_message) from None
    raise DatabaseError(f"{safe_message} ({code})" if code else safe_message) from None


def _run(operation: str, callback):
    try:
        response = callback()
    except (DatabaseError, DuplicateRecordError):
        raise
    except Exception as exc:
        raise DatabaseError(f"{operation} failed") from exc
    _raise_response_error(operation, response)
    return response


def _normalize_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
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
        elif operator == "is":
            query = query.is_(column, value)
        elif operator == "not_is":
            query = query.not_.is_(column, value)
        elif operator == "gte":
            query = query.gte(column, value)
        elif operator == "lte":
            query = query.lte(column, value)
        else:
            raise ValueError(f"Unsupported database filter operator: {operator}")
    return query


def select_rows(
    table: str,
    *,
    columns: str = "*",
    filters: Iterable[tuple[str, str, Any]] = (),
    order_by: str | None = None,
    descending: bool = False,
    limit: int | None = None,
    page_size: int = 1000,
) -> pd.DataFrame:
    """Read a table through PostgREST, paginating large result sets."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch_limit = page_size if limit is None else min(page_size, limit - len(rows))

        def request():
            query = get_client().table(table).select(columns)
            query = _apply_filters(query, filters)
            if order_by:
                query = query.order(order_by, desc=descending)
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
