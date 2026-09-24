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

    return {
        "trained_at": metadata["trained_at"],
        "production_model": metadata["production_model"],
        "best_model": metadata["best_model"],
        "cutoff_date": metadata.get("cutoff_date"),
        "test_games": test_games,
        "features": metadata["features"],
        "available_models": metadata["available_models"],
        "leaderboard": parsed_leaderboard,
    }


def load_metadata_and_leaderboard(
    metadata_path: str, leaderboard_path: str
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Load a previously saved run's metadata JSON and leaderboard CSV from disk."""
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    leaderboard = pd.read_csv(leaderboard_path)
    return metadata, leaderboard
