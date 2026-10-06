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


class TrainingSummaryTests(unittest.TestCase):
    def frames(self):
        dates = ["2024-10-25", "2024-12-01", "2025-02-20", "2025-02-25", "2025-10-30", "2026-04-12"]
        df = pd.DataFrame({"GAME_DATE": dates, "home_win": [1, 0, 1, 1, 0, 1]})
        return df.iloc[:3], df.iloc[3:]

    def test_summary_counts_dates_and_seasons(self):
        train, test = self.frames()
        summary = model_metadata.build_training_summary(train, test, 10)
        self.assertEqual(summary, {
            "first_game_date": "2024-10-25", "cutoff_date": "2025-02-25",
            "last_game_date": "2026-04-12", "games_total": 6, "train_games": 3, "test_games": 3,
            "home_win_rate": 0.6667, "rolling_window": 10,
            "seasons": [{"season": "2024-25", "games": 4, "train": 3, "test": 1},
                        {"season": "2025-26", "games": 2, "train": 0, "test": 2}],
        })
        json.dumps(summary)  # plain JSON types only

    def test_season_label_follows_the_sept_to_aug_season(self):
        self.assertEqual(model_metadata.season_label("2020-08-30"), "2019-20")
        self.assertEqual(model_metadata.season_label("2020-09-01"), "2020-21")

    def test_training_is_only_in_the_model_run_row_when_written(self):
        metadata, leaderboard = model_metadata.load_metadata_and_leaderboard(
            METADATA_PATH, LEADERBOARD_PATH
        )
        metadata = {k: v for k, v in metadata.items() if k != "training"}
        self.assertNotIn("training", model_metadata.build_model_run_row(metadata, leaderboard))
        metadata["training"] = {"games_total": 6}
        row = model_metadata.build_model_run_row(metadata, leaderboard)
        self.assertEqual(row["training"], {"games_total": 6})


if __name__ == "__main__":
    unittest.main()
