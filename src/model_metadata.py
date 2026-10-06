"""Pure helpers for publishing a training run to the model_runs table.

Deliberately torch-free: model.py transitively imports torch through
model_wrappers, so this module stays importable (and testable) without it.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd


def _clean_value(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        return value
    if pd.isna(value):
        return None
    return value


def _parse_json_field(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return None
    return json.loads(value)


def _build_leaderboard_entry(row: dict[str, Any]) -> dict[str, Any]:
    entry = {column: _clean_value(value) for column, value in row.items()}
    entry["feature_signal"] = _parse_json_field(row.get("feature_signal"))
    entry["best_params"] = _parse_json_field(row.get("best_params"))
    return entry


def build_model_run_row(metadata: dict[str, Any], leaderboard: pd.DataFrame) -> dict[str, Any]:
    """Build the model_runs row for the given training run's metadata and leaderboard."""
    records = leaderboard.to_dict("records")
    parsed_leaderboard = [_build_leaderboard_entry(row) for row in records]
    test_games = None
    if parsed_leaderboard and parsed_leaderboard[0].get("test_games") is not None:
        test_games = int(parsed_leaderboard[0]["test_games"])

    row = {
        "trained_at": metadata["trained_at"],
        "production_model": metadata["production_model"],
        "best_model": metadata["best_model"],
        "cutoff_date": metadata.get("cutoff_date"),
        "test_games": test_games,
        "features": metadata["features"],
        "available_models": metadata["available_models"],
        "leaderboard": parsed_leaderboard,
    }
    # Only sent when the training run wrote it: the column needs migration 20261006000100, so an
    # older metadata file must keep publishing to a database that does not have it yet.
    if metadata.get("training") is not None:
        row["training"] = metadata["training"]
    return row


def season_label(game_date: Any) -> str:
    """NBA season for a date (Sept 1 - Aug 31, as app.season_for): 2025-02-25 -> "2024-25"."""
    stamp = pd.Timestamp(game_date)
    start = stamp.year if stamp.month >= 9 else stamp.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def build_training_summary(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    rolling_window: int,
    target: str = "home_win",
) -> dict[str, Any]:
    """Size of a training run for the Model page: dates, game counts, home win rate, per season."""
    both = pd.concat([df_train, df_test], ignore_index=True)
    if both.empty:
        raise ValueError("Cannot summarise a training run with no games.")
    dates = pd.to_datetime(both["GAME_DATE"])
    test_dates = pd.to_datetime(df_test["GAME_DATE"])
    seasons: dict[str, dict[str, int]] = {}
    for label, is_test in zip(dates.map(season_label), [False] * len(df_train) + [True] * len(df_test)):
        entry = seasons.setdefault(label, {"games": 0, "train": 0, "test": 0})
        entry["games"] += 1
        entry["test" if is_test else "train"] += 1
    return {
        "first_game_date": dates.min().strftime("%Y-%m-%d"),
        "cutoff_date": test_dates.min().strftime("%Y-%m-%d") if len(test_dates) else None,
        "last_game_date": dates.max().strftime("%Y-%m-%d"),
        "games_total": int(len(both)),
        "train_games": int(len(df_train)),
        "test_games": int(len(df_test)),
        "home_win_rate": round(float(both[target].mean()), 4),
        "rolling_window": int(rolling_window),
        "seasons": [{"season": k, **v} for k, v in sorted(seasons.items())],
    }


def load_metadata_and_leaderboard(
    metadata_path: str, leaderboard_path: str
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Load a previously saved run's metadata JSON and leaderboard CSV from disk."""
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    leaderboard = pd.read_csv(leaderboard_path)
    return metadata, leaderboard
