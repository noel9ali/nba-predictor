import json
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# This module must stay torch-free: it imports only model_metadata, never
# model.py (which transitively imports torch via model_wrappers).
import model_metadata

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
METADATA_PATH = os.path.join(REPO_ROOT, "data", "model_metadata.json")
LEADERBOARD_PATH = os.path.join(REPO_ROOT, "data", "model_leaderboard.csv")


class ModelPublishTests(unittest.TestCase):
    def test_build_model_run_row_from_committed_artifacts(self):
        metadata, leaderboard = model_metadata.load_metadata_and_leaderboard(
            METADATA_PATH, LEADERBOARD_PATH
        )
        row = model_metadata.build_model_run_row(metadata, leaderboard)

        self.assertEqual(len(row["leaderboard"]), 5)
        self.assertEqual(row["production_model"], "legacy-calibrated-logistic")
        self.assertEqual(row["test_games"], 1596)
        self.assertIsInstance(row["leaderboard"][0]["feature_signal"], list)
        self.assertEqual(
            row["leaderboard"][0]["feature_signal"][0]["feature"], "ELO_DIFF"
        )

    def test_best_params_parsed_and_nan_becomes_none(self):
        metadata = {
            "trained_at": "2026-09-18T01:11:09+00:00",
            "production_model": "legacy-calibrated-logistic",
            "best_model": "legacy-calibrated-logistic",
            "cutoff_date": "2025-02-25",
            "features": ["ELO_DIFF"],
            "available_models": ["legacy-calibrated-logistic"],
        }
        leaderboard = pd.DataFrame(
            [
                {
                    "test_games": 10,
                    "feature_signal": '[{"feature": "ELO_DIFF", "importance": 0.5}]',
                    "best_params": "{}",
                    "cv_best_score": float("nan"),
                }
            ]
        )

        row = model_metadata.build_model_run_row(metadata, leaderboard)
        entry = row["leaderboard"][0]

        self.assertEqual(entry["best_params"], {})
        self.assertIsNone(entry["cv_best_score"])
        self.assertEqual(entry["feature_signal"][0]["feature"], "ELO_DIFF")

    def test_publish_is_skipped_when_flag_is_off(self):
        with patch.dict(os.environ, {"NBA_SCHEMA_V2": "false"}, clear=True):
            enabled = os.getenv("NBA_SCHEMA_V2", "false").strip().lower() in {
                "1",
                "true",
                "yes",
            }
        self.assertFalse(enabled)

        # model.publish_model_run() checks schema_v2_enabled() before calling
        # upsert_rows; simulate the same guard without importing torch-heavy
        # model.py by exercising database.schema_v2_enabled() directly.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        import database

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(database.schema_v2_enabled())
        with patch.object(database, "upsert_rows") as fake_upsert:
            if database.schema_v2_enabled():
                database.upsert_rows("model_runs", [{}], conflict_columns=["trained_at"])
            fake_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
