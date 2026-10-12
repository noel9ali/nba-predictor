import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import odds


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._json


class OddsTimeoutTests(unittest.TestCase):
    def test_get_tonights_odds_passes_a_connect_and_read_timeout(self):
        with patch.object(odds.requests, "get", return_value=FakeResponse(200, [])) as fake_get:
            odds.get_tonights_odds()
        self.assertEqual(fake_get.call_args.kwargs.get("timeout"), (5, 30))

    def test_generic_market_rows_use_capture_time_not_commence_time(self):
        payload = [{
            "id": "event-1",
            "commence_time": "2020-01-01T00:00:00Z",
            "home_team": "Atlanta Hawks",
            "away_team": "Boston Celtics",
            "bookmakers": [{
                "title": "DraftKings",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Atlanta Hawks", "price": -110},
                    {"name": "Boston Celtics", "price": 100},
                ]}],
            }],
        }]
        with patch.object(odds.requests, "get", return_value=FakeResponse(200, payload)):
            with patch("market_odds.write_moneyline_rows") as write:
                odds.get_tonights_odds()
        rows = write.call_args.args[0]
        self.assertTrue(rows)
        self.assertNotEqual(rows[0]["captured_at"], payload[0]["commence_time"])

    def test_get_bookmakers_passes_a_connect_and_read_timeout(self):
        with patch.object(odds.requests, "get", return_value=FakeResponse(200, [])) as fake_get:
            odds.get_bookmakers()
        self.assertEqual(fake_get.call_args.kwargs.get("timeout"), (5, 30))


class OddsMainBlockTests(unittest.TestCase):
    def test_odds_module_has_a_single_main_block(self):
        src_path = os.path.join(os.path.dirname(__file__), "..", "src", "odds.py")
        with open(src_path, encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(source.count("if __name__ == '__main__':"), 1)


if __name__ == "__main__":
    unittest.main()
