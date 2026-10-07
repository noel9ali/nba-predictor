import ast
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
MODEL_PY_PATH = os.path.join(REPO_ROOT, "src", "model.py")
ENV_EXAMPLE_PATH = os.path.join(REPO_ROOT, ".env.example")


def _model_py_constants():
    """DEFAULT_PRODUCTION_MODEL and the model_registry() keys, read from source (no torch import)."""
    with open(MODEL_PY_PATH, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    default, registry = None, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_PRODUCTION_MODEL"
            for target in node.targets
        ):
            default = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "model_registry":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict):
                    registry = [ast.literal_eval(key) for key in stmt.value.keys]
    return default, registry


class ModelPublishTests(unittest.TestCase):
    """Invariants of whichever training run is committed under data/, not a snapshot of it.

    data/model_metadata.json and data/model_leaderboard.csv are rewritten by every retrain,
    so nothing here pins a model name, a row count or a metric value.
    """

    @classmethod
    def setUpClass(cls):
        cls.metadata, cls.leaderboard = model_metadata.load_metadata_and_leaderboard(
            METADATA_PATH, LEADERBOARD_PATH
        )
        cls.row = model_metadata.build_model_run_row(cls.metadata, cls.leaderboard)

    def test_row_carries_every_leaderboard_model(self):
        models = [entry["model"] for entry in self.row["leaderboard"]]
        self.assertGreaterEqual(len(models), 2)
        self.assertEqual(len(models), len(self.leaderboard))
        self.assertEqual(len(set(models)), len(models))
        for name in models:
            self.assertIn(name, self.row["available_models"])
        self.assertEqual(self.row["features"], self.metadata["features"])
        self.assertEqual(self.row["trained_at"], self.metadata["trained_at"])

    def test_production_and_best_model_are_available_and_ranked(self):
        available = self.row["available_models"]
        ranked = [entry["model"] for entry in self.row["leaderboard"]]
        for key in ("production_model", "best_model"):
            self.assertIn(self.row[key], available, key)
            # model.run() only ever promotes a model it fitted and scored.
            self.assertIn(self.row[key], ranked, key)

    def test_test_games_is_one_positive_int_shared_by_every_row(self):
        test_games = self.row["test_games"]
        self.assertIsInstance(test_games, int)
        self.assertGreater(test_games, 0)
        for entry in self.row["leaderboard"]:
            self.assertEqual(int(entry["test_games"]), test_games, entry["model"])

    def test_feature_signal_is_a_list_of_known_features_or_none(self):
        features = set(self.metadata["features"])
        for entry in self.row["leaderboard"]:
            signal = entry["feature_signal"]
            if signal is None:  # allowed: e.g. calibrated-xgboost exposes no importances
                continue
            self.assertIsInstance(signal, list, entry["model"])
            for item in signal:
                self.assertIn(item["feature"], features, entry["model"])
                self.assertIsInstance(item["importance"], float, entry["model"])

    def test_ranks_run_one_to_n_in_log_loss_order(self):
        entries = self.row["leaderboard"]
        self.assertEqual([int(e["rank"]) for e in entries], list(range(1, len(entries) + 1)))
        losses = [float(e["log_loss"]) for e in entries]
        self.assertEqual(losses, sorted(losses))

    def test_row_is_plain_json(self):
        json.dumps(self.row, allow_nan=False)

    def test_default_production_model_is_a_registry_key(self):
        default, registry = _model_py_constants()
        self.assertIsNotNone(registry)
        self.assertIn(default, registry)
        with open(ENV_EXAMPLE_PATH, "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.startswith("NBA_PRODUCTION_MODEL=")]
        self.assertEqual(lines, [f"NBA_PRODUCTION_MODEL={default}"])

    def test_empty_feature_signal_becomes_none(self):
        metadata = {
            "trained_at": "2026-09-18T01:11:09+00:00",
            "production_model": "gradient-boosting-gridsearch",
            "best_model": "gradient-boosting-gridsearch",
            "cutoff_date": "2025-02-25",
            "features": ["ELO_DIFF"],
            "available_models": ["gradient-boosting-gridsearch", "calibrated-xgboost"],
        }
        leaderboard = pd.DataFrame(
            [
                {"rank": 1, "model": "gradient-boosting-gridsearch", "test_games": 10,
                 "feature_signal": '[{"feature": "ELO_DIFF", "importance": 0.7}]',
                 "best_params": "{}"},
                # model._extract_feature_signal() writes "" when a model has no importances;
                # read_csv turns that into NaN, so both spellings must map to None.
                {"rank": 2, "model": "calibrated-xgboost", "test_games": 10,
                 "feature_signal": "", "best_params": "  "},
                {"rank": 3, "model": "calibrated-xgboost", "test_games": 10,
                 "feature_signal": float("nan"), "best_params": float("nan")},
            ]
        )

        row = model_metadata.build_model_run_row(metadata, leaderboard)

        self.assertEqual(row["test_games"], 10)
        self.assertEqual(row["leaderboard"][0]["feature_signal"][0]["feature"], "ELO_DIFF")
        for entry in row["leaderboard"][1:]:
            self.assertIsNone(entry["feature_signal"])
            self.assertIsNone(entry["best_params"])
        json.dumps(row, allow_nan=False)

    def test_best_params_parsed_and_nan_becomes_none(self):
        metadata = {
            "trained_at": "2026-09-18T01:11:09+00:00",
            "production_model": "gradient-boosting-gridsearch",
            "best_model": "gradient-boosting-gridsearch",
            "cutoff_date": "2025-02-25",
            "features": ["ELO_DIFF"],
            "available_models": ["gradient-boosting-gridsearch"],
        }
        leaderboard = pd.DataFrame(
            [
                {
                    "test_games": 10,
                    "feature_signal": '[{"feature": "ELO_DIFF", "importance": 0.5}]',
                    "best_params": '{"learning_rate": 0.05, "max_depth": 2}',
                    "cv_best_score": float("nan"),
                }
            ]
        )

        row = model_metadata.build_model_run_row(metadata, leaderboard)
        entry = row["leaderboard"][0]

        self.assertEqual(entry["best_params"], {"learning_rate": 0.05, "max_depth": 2})
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
