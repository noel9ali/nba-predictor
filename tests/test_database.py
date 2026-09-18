import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database


class Response:
    def __init__(self, data=None, error=None):
        self.data = data or []
        self.error = error


class FakeQuery:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
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

    def execute(self):
        return self.response


class FakeClient:
    def __init__(self, response=None):
        self.query = FakeQuery(response or Response())

    def table(self, table):
        self.query.calls.append(("table", table))
        return self.query


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

    def test_insert_and_upsert_use_explicit_rows_and_batches(self):
        client = FakeClient(Response([{"GAME_ID": "g1"}]))
        database._client = client
        row = {"GAME_ID": "g1", "TEAM_ID": 7}

        database.insert_rows("games", [row])
        database.upsert_rows("elo", [row], conflict_columns=["GAME_ID"])

        self.assertIn(("insert", [row]), client.query.calls)
        self.assertIn(("upsert", [row], "GAME_ID"), client.query.calls)

    def test_failed_write_is_translated_without_secret(self):
        error = type("Error", (), {"code": "23505", "message": "duplicate"})()
        database._client = FakeClient(Response(error=error))

        with self.assertRaises(database.DuplicateRecordError) as raised:
            database.insert_rows("predictions", [{"game_id": "g1"}])

        self.assertNotIn("SUPABASE_SECRET_KEY", str(raised.exception))

    def test_missing_configuration_is_explicit(self):
        database._client = None
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(database.DatabaseError) as raised:
                database.get_client()

        self.assertIn("SUPABASE_URL", str(raised.exception))
        self.assertNotIn("secret-value", str(raised.exception))

    def test_invalid_batch_size_does_not_issue_a_write(self):
        database._client = FakeClient()
        with self.assertRaises(ValueError):
            database.insert_rows("games", [{"GAME_ID": "g1"}], batch_size=0)
        self.assertEqual(database._client.query.calls, [])


if __name__ == "__main__":
    unittest.main()
