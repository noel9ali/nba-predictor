import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from postgrest.exceptions import APIError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database


class Response:
    def __init__(self, data=None, error=None, count=None):
        self.data = data or []
        self.error = error
        self.count = count


class FakeQuery:
    def __init__(self, response):
        self.responses = response if isinstance(response, list) else [response]
        self.default_response = self.responses[-1]
        self.calls = []

    def select(self, columns, count=None, head=None):
        self.calls.append(("select", columns, count, head))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.calls.append(("neq", column, value))
        return self

    def lt(self, column, value):
        self.calls.append(("lt", column, value))
        return self

    def gt(self, column, value):
        self.calls.append(("gt", column, value))
        return self

    def gte(self, column, value):
        self.calls.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.calls.append(("lte", column, value))
        return self

    def ilike(self, column, pattern):
        self.calls.append(("ilike", column, pattern))
        return self

    def in_(self, column, values):
        self.calls.append(("in_", column, values))
        return self

    def is_(self, column, value):
        self.calls.append(("is_", column, value))
        return self

    @property
    def not_(self):
        return self

    def order(self, column, desc=False):
        self.calls.append(("order", column, desc))
        return self

    def range(self, start, end):
        self.calls.append(("range", start, end))
        return self

    def insert(self, rows):
        self.calls.append(("insert", rows))
        return self

    def upsert(self, rows, on_conflict):
        self.calls.append(("upsert", rows, on_conflict))
        return self

    def update(self, values):
        self.calls.append(("update", values))
        return self

    def rpc(self, function, params):
        self.calls.append(("rpc", function, params))
        return self

    def execute(self):
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.default_response


class FakeClient:
    def __init__(self, response=None):
        self.query = FakeQuery(response or Response())

    def table(self, table):
        self.query.calls.append(("table", table))
        return self.query

    def rpc(self, function, params):
        return self.query.rpc(function, params)


class RaisingQuery(FakeQuery):
    """Models the real postgrest client: execute() raises instead of returning an error response."""

    def __init__(self, exc):
        super().__init__(Response())
        self.exc = exc

    def execute(self):
        raise self.exc


class RaisingClient:
    def __init__(self, exc):
        self.query = RaisingQuery(exc)

    def table(self, table):
        self.query.calls.append(("table", table))
        return self.query

    def rpc(self, function, params):
        return self.query.rpc(function, params)


class DatabaseTests(unittest.TestCase):
    def tearDown(self):
        database._client = None

    def test_select_applies_table_filter_sort_and_limit(self):
        client = FakeClient(Response([{"GAME_ID": "g1"}]))
        database._client = client

        result = database.select_rows(
            "games",
            columns="GAME_ID,GAME_DATE",
            filters=[("TEAM_ID", "eq", 7)],
            order_by="GAME_DATE",
            descending=True,
            limit=1,
        )

        self.assertEqual(result["GAME_ID"].tolist(), ["g1"])
        self.assertIn(("eq", "TEAM_ID", 7), client.query.calls)
        self.assertIn(("order", "GAME_DATE", True), client.query.calls)

    def test_select_requires_order_for_paginated_reads(self):
        database._client = FakeClient(Response([{"GAME_ID": "g1"}]))
        with self.assertRaises(ValueError):
            database.select_rows("games")

    def test_select_paginates_in_stable_order(self):
        client = FakeClient(
            [
                Response([{"GAME_ID": "g1"}]),
                Response([{"GAME_ID": "g2"}]),
                Response([]),
            ]
        )
        database._client = client

        result = database.select_rows("games", order_by=["GAME_DATE", "GAME_ID"], page_size=1)

        self.assertEqual(result["GAME_ID"].tolist(), ["g1", "g2"])
        self.assertEqual(
            [call for call in client.query.calls if call[0] == "order"],
            [
                ("order", "GAME_DATE", False),
                ("order", "GAME_ID", False),
                ("order", "GAME_DATE", False),
                ("order", "GAME_ID", False),
                ("order", "GAME_DATE", False),
                ("order", "GAME_ID", False),
            ],
        )

    def test_insert_and_upsert_use_explicit_rows_and_batches(self):
        client = FakeClient(Response([{"GAME_ID": "g1"}]))
        database._client = client
        row = {"GAME_ID": "g1", "TEAM_ID": 7}

        database.insert_rows("games", [row])
        database.upsert_rows("elo", [row], conflict_columns=["GAME_ID"])

        self.assertIn(("insert", [row]), client.query.calls)
        self.assertIn(("upsert", [row], "GAME_ID"), client.query.calls)

    def test_write_normalizes_pandas_missing_values(self):
        client = FakeClient(Response([{"GAME_ID": "g1"}]))
        database._client = client

        database.insert_rows(
            "features",
            [{"GAME_ID": "g1", "DATE": pd.NaT, "VALUE": np.float32(np.nan)}],
        )

        self.assertIn(
            ("insert", [{"GAME_ID": "g1", "DATE": None, "VALUE": None}]),
            client.query.calls,
        )

    def test_failed_write_is_translated_without_secret(self):
        error = type("Error", (), {"code": "23505", "message": "duplicate"})()
        database._client = FakeClient(Response(error=error))

        with self.assertRaises(database.DuplicateRecordError) as raised:
            database.insert_rows("predictions", [{"game_id": "g1"}])

        self.assertNotIn("SUPABASE_SECRET_KEY", str(raised.exception))

    def test_missing_configuration_is_explicit(self):
        database._client = None
        # Patch out load_dotenv so this test's outcome doesn't depend on
        # whether a real .env happens to exist on disk in this checkout.
        with patch.object(database, "load_dotenv"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(database.DatabaseError) as raised:
                database.get_client()

        self.assertIn("SUPABASE_URL", str(raised.exception))
        self.assertNotIn("secret-value", str(raised.exception))

    def test_invalid_batch_size_does_not_issue_a_write(self):
        database._client = FakeClient()
        with self.assertRaises(ValueError):
            database.insert_rows("games", [{"GAME_ID": "g1"}], batch_size=0)
        self.assertEqual(database._client.query.calls, [])

    def test_new_filter_operators_call_the_right_query_methods(self):
        client = FakeClient(Response([]))
        database._client = client

        database.select_rows(
            "predictions",
            filters=[
                ("season", "neq", "2024-25"),
                ("edge", "lt", 0.1),
                ("edge", "gt", 0.0),
                ("bookmaker", "ilike", "%draft%"),
            ],
            order_by="game_id",
        )

        self.assertIn(("neq", "season", "2024-25"), client.query.calls)
        self.assertIn(("lt", "edge", 0.1), client.query.calls)
        self.assertIn(("gt", "edge", 0.0), client.query.calls)
        self.assertIn(("ilike", "bookmaker", "%draft%"), client.query.calls)

    def test_in_filter_calls_in_and_rejects_str_or_empty(self):
        client = FakeClient(Response([]))
        database._client = client

        database.select_rows(
            "games", filters=[("TEAM_ID", "in", [1, 2, 3])], order_by="GAME_ID"
        )
        self.assertIn(("in_", "TEAM_ID", [1, 2, 3]), client.query.calls)

        with self.assertRaises(ValueError):
            database._apply_filters(FakeQuery(Response()), [("TEAM_ID", "in", "12")])
        with self.assertRaises(ValueError):
            database._apply_filters(FakeQuery(Response()), [("TEAM_ID", "in", [])])

    def test_unknown_operator_still_raises(self):
        with self.assertRaises(ValueError):
            database._apply_filters(FakeQuery(Response()), [("TEAM_ID", "bogus", 1)])

    def test_order_by_accepts_mixed_direction_tuples(self):
        client = FakeClient(Response([]))
        database._client = client

        database.select_rows(
            "predictions",
            order_by=[("game_date", True), "game_id"],
            descending=False,
        )

        order_calls = [call for call in client.query.calls if call[0] == "order"]
        self.assertIn(("order", "game_date", True), order_calls)
        self.assertIn(("order", "game_id", False), order_calls)

    def test_select_page_returns_rows_and_exact_count(self):
        client = FakeClient(Response([{"game_id": "g1"}], count=131))
        database._client = client

        frame, total = database.select_page(
            "predictions", order_by="game_id", offset=25, limit=25
        )

        self.assertEqual(frame["game_id"].tolist(), ["g1"])
        self.assertEqual(total, 131)
        self.assertIn(("select", "*", "exact", None), client.query.calls)
        self.assertIn(("range", 25, 49), client.query.calls)

    def test_select_page_requires_order_by_and_valid_limit(self):
        database._client = FakeClient(Response([]))
        with self.assertRaises(ValueError):
            database.select_page("predictions", order_by=())
        with self.assertRaises(ValueError):
            database.select_page("predictions", order_by="game_id", limit=0)

    def test_count_rows_uses_head_request(self):
        client = FakeClient(Response([], count=42))
        database._client = client

        total = database.count_rows("predictions", filters=[("bet_amount", "gt", 0)])

        self.assertEqual(total, 42)
        self.assertIn(("select", "*", "exact", True), client.query.calls)
        self.assertIn(("gt", "bet_amount", 0), client.query.calls)

    def test_call_rpc_returns_a_dataframe(self):
        client = FakeClient(Response([{"team_id": 7, "wins": 10}]))
        database._client = client

        result = database.call_rpc("team_form", {"p_season": "2025-26"})

        self.assertEqual(result["team_id"].tolist(), [7])
        self.assertIn(("rpc", "team_form", {"p_season": "2025-26"}), client.query.calls)

    def test_missing_table_and_column_errors_are_translated(self):
        database._client = FakeClient(
            Response(error=type("Error", (), {"code": "PGRST205", "message": "missing"})())
        )
        with self.assertRaises(database.MissingTableError):
            database.select_rows("bankroll", order_by="date")

        database._client = FakeClient(
            Response(error=type("Error", (), {"code": "42P01", "message": "missing"})())
        )
        with self.assertRaises(database.MissingTableError):
            database.select_rows("bankroll", order_by="date")

        database._client = FakeClient(
            Response(error=type("Error", (), {"code": "PGRST204", "message": "missing"})())
        )
        with self.assertRaises(database.MissingColumnError):
            database.select_rows("predictions", order_by="game_id")

        database._client = FakeClient(
            Response(error=type("Error", (), {"code": "42703", "message": "missing"})())
        )
        with self.assertRaises(database.MissingColumnError):
            database.select_rows("predictions", order_by="game_id")

    def test_raised_api_error_is_translated_to_missing_table_error(self):
        for code in ("PGRST205", "42P01"):
            error = APIError({"code": code, "message": "missing", "details": None, "hint": None})
            database._client = RaisingClient(error)
            with self.assertRaises(database.MissingTableError):
                database.select_rows("bankroll", order_by="date")

    def test_raised_api_error_is_translated_to_missing_column_error(self):
        for code in ("PGRST204", "42703"):
            error = APIError({"code": code, "message": "missing", "details": None, "hint": None})
            database._client = RaisingClient(error)
            with self.assertRaises(database.MissingColumnError):
                database.select_rows("predictions", order_by="game_id")

    def test_raised_api_error_is_translated_to_duplicate_record_error(self):
        error = APIError({"code": "23505", "message": "duplicate", "details": None, "hint": None})
        database._client = RaisingClient(error)
        with self.assertRaises(database.DuplicateRecordError):
            database.insert_rows("predictions", [{"game_id": "g1"}])

    def test_raised_api_error_with_unknown_code_is_plain_database_error(self):
        error = APIError({"code": "99999", "message": "boom", "details": None, "hint": None})
        database._client = RaisingClient(error)
        with self.assertRaises(database.DatabaseError) as raised:
            database.select_rows("predictions", order_by="game_id")

        self.assertIn("99999", str(raised.exception))

    def test_raised_api_error_message_text_is_not_leaked(self):
        error = APIError(
            {"code": "PGRST205", "message": "super-secret-diagnostic-text", "details": None, "hint": None}
        )
        database._client = RaisingClient(error)
        with self.assertRaises(database.MissingTableError) as raised:
            database.select_rows("bankroll", order_by="date")

        self.assertNotIn("super-secret-diagnostic-text", str(raised.exception))

    def test_non_api_error_exception_still_becomes_plain_database_error(self):
        database._client = RaisingClient(RuntimeError("connection reset"))
        with self.assertRaises(database.DatabaseError) as raised:
            database.select_rows("predictions", order_by="game_id")

        self.assertNotIsInstance(raised.exception, database.MissingTableError)
        self.assertNotIn("connection reset", str(raised.exception))

    def test_normalize_game_id(self):
        self.assertEqual(database.normalize_game_id(22501186), "0022501186")
        self.assertEqual(database.normalize_game_id("22501186"), "0022501186")
        self.assertEqual(database.normalize_game_id("0022501186"), "0022501186")
        with self.assertRaises(ValueError):
            database.normalize_game_id(None)

    def test_schema_v2_enabled_defaults_to_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(database.schema_v2_enabled())
        with patch.dict(os.environ, {"NBA_SCHEMA_V2": "true"}, clear=True):
            self.assertTrue(database.schema_v2_enabled())


if __name__ == "__main__":
    unittest.main()
