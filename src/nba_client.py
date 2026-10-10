"""Throttled, retrying, cached access to nba_api endpoints (shared by the player-data modules).

Every call waits at least NBA_API_MIN_INTERVAL_SECONDS since the previous one, retries with
exponential backoff, and can cache the resulting DataFrames as JSON under data/raw/ so a rerun
after a crash does not hit nba_api again. ID columns stay strings (zero-padded GAME_IDs survive).
"""

from __future__ import annotations

import json
import os
import time
from io import StringIO
from typing import Callable

import pandas as pd

import config

_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = config.NBA_API_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def frames_to_json(frames: list[pd.DataFrame]) -> str:
    return json.dumps([f.to_json(orient="split", date_format="iso", index=False) for f in frames])


def frames_from_json(text: str) -> list[pd.DataFrame]:
    return [pd.read_json(StringIO(s), orient="split", dtype=False, convert_dates=False)
            for s in json.loads(text)]


def call_frames(factory: Callable[[], object], *, cache_path: str | None = None,
                refresh: bool = False, retries: int | None = None,
                sleep: Callable[[float], None] = time.sleep) -> list[pd.DataFrame]:
    """Return endpoint.get_data_frames(), from cache_path when present (unless refresh)."""
    if cache_path and not refresh and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            return frames_from_json(fh.read())
    retries = config.NBA_API_RETRIES if retries is None else retries
    last_exc: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            frames = factory().get_data_frames()
            break
        except Exception as exc:  # network errors, JSON decode errors, timeouts
            last_exc = exc
            if attempt < retries - 1:
                sleep(config.NBA_API_BACKOFF_SECONDS * (2 ** attempt))
    else:
        raise RuntimeError(f"nba_api call failed after {retries} attempts: {type(last_exc).__name__}") from last_exc
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(frames_to_json(frames))
        os.replace(tmp, cache_path)
    return frames


def season_for_date(d) -> str:
    """NBA season label for a date: Oct 2026 -> '2026-27', Mar 2026 -> '2025-26'."""
    year, month = d.year, d.month
    start = year if month >= 8 else year - 1
    return f"{start}-{(start + 1) % 100:02d}"
