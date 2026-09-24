import contextlib
import io
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database
import track


class FakeScoreboard:
    def __init__(self, teams_df, headers_df=None):
        self._teams_df = teams_df
        if headers_df is None:
            # Default: every game present in the LineScore frame is final, so
            # existing tests that only care about settlement math (not
            # finality itself) don't need to construct a GameHeader frame.
            game_ids = list(teams_df["gameId"].unique()) if len(teams_df) else []
            headers_df = pd.DataFrame(
                {
                    "gameId": game_ids,
                    "gameStatus": [3] * len(game_ids),
                    "gameStatusText": ["Final"] * len(game_ids),
                }
            )
        self._headers_df = headers_df

    def get_data_frames(self):
        # ScoreboardV3.get_data_frames() returns several frames; GameHeader
        # (gameStatus) is index 1, LineScore (teams/scores) is index 2.
        return [None, self._headers_df, self._teams_df]


def _apply_fake_filters(rows, filters):
    """A small, faithful-enough filter engine so fake DB reads actually
    respect the filter values track.py sends (eq/lt/is-null/not-is-null),
    instead of always returning a fixed frame regardless of the query."""
    matched = []
    for row in rows:
        keep = True
        for column, op, value in filters:
            actual = row.get(column)
            if op == "eq":
                keep = actual == value
            elif op == "lt":
                keep = actual is not None and actual < value
            elif op == "is" and value == "null":
                keep = actual is None
            elif op == "not_is" and value == "null":
                keep = actual is not None
            else:
                raise AssertionError(f"unsupported fake filter op: {op!r}")
            if not keep:
                break
        if keep:
            matched.append(row)
    return matched


def _fake_select_rows(rows):
    """select_rows() fake backed by a live list of dicts, so writes made by
    a fake update_rows()/upsert_rows() during the same run are visible to a
    later read (needed to prove idempotency across two calls)."""

    def fake(table, **kwargs):
        if table != "predictions":
            raise AssertionError(f"Unexpected table read: {table}")
        filters = kwargs.get("filters", ())
        matched = _apply_fake_filters(rows, filters)
        order_by = kwargs.get("order_by")
        if order_by:
            matched = sorted(matched, key=lambda r: r.get(order_by), reverse=kwargs.get("descending", False))
        columns = kwargs.get("columns")
        if columns and columns != "*":
            cols = columns.split(",")
            projected = [{c: r.get(c) for c in cols} for r in matched]
            return pd.DataFrame(projected, columns=cols)
        limit = kwargs.get("limit")
        if limit is not None:
            matched = matched[:limit]
        return pd.DataFrame(matched)

    return fake


class TrackTests(unittest.TestCase):
    def test_missing_bankroll_raises_actionable_database_error(self):
        with patch.object(
            track,
            "select_rows",
            side_effect=database.MissingTableError("bankroll missing"),
        ):
            with self.assertRaises(database.DatabaseError) as raised:
                track.get_current_bankroll()
        self.assertIn("20260923000400", str(raised.exception))

        with patch.object(
            track,
            "select_rows",
            side_effect=database.MissingTableError("bankroll missing"),
        ):
            with self.assertRaises(database.DatabaseError) as raised:
                track.setup_tables()
        self.assertIn("20260923000400", str(raised.exception))

    def test_update_results_settles_loss_and_win_with_text_odds(self):
        pending = pd.DataFrame(
            [
                {
                    "game_id": "0022501195",
                    "game_date": "2026-04-12",
                    "home_team": "MIN",
                    "away_team": "NOP",
                    "predicted_winner": "NOP",
                    "bet_placed": "NOP",
                    "bet_amount": 21.04,
                    "odds": "188",
                },
                {
                    "game_id": "0022501196",
                    "game_date": "2026-04-12",
                    "home_team": "PHX",
                    "away_team": "OKC",
                    "predicted_winner": "PHX",
                    "bet_placed": "PHX",
                    "bet_amount": 40.0,
                    "odds": "-150",
                },
            ]
        )
        teams = pd.DataFrame(
            [
                {"gameId": "0022501195", "teamTricode": "MIN", "score": "110"},
                {"gameId": "0022501195", "teamTricode": "NOP", "score": "100"},
                {"gameId": "0022501196", "teamTricode": "PHX", "score": "112"},
                {"gameId": "0022501196", "teamTricode": "OKC", "score": "104"},
            ]
        )

        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=self._select_rows_router(pending)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 2)
        loss_update = next(v for v, f in updates if ("game_id", "eq", "0022501195") in f)
        win_update = next(v for v, f in updates if ("game_id", "eq", "0022501196") in f)
        self.assertEqual(loss_update["profit_loss"], -21.04)
        self.assertAlmostEqual(win_update["profit_loss"], 40.0 * 100 / 150)

    def test_int_game_id_matches_zero_padded_scoreboard_id(self):
        pending = pd.DataFrame(
            [
                {
                    "game_id": 22501195,
                    "game_date": "2026-04-12",
                    "home_team": "MIN",
                    "away_team": "NOP",
                    "predicted_winner": "NOP",
                    "bet_placed": None,
                    "bet_amount": 0.0,
                    "odds": "188",
                }
            ]
        )
        teams = pd.DataFrame(
            [
                {"gameId": "0022501195", "teamTricode": "MIN", "score": "110"},
                {"gameId": "0022501195", "teamTricode": "NOP", "score": "100"},
            ]
        )
        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=self._select_rows_router(pending)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 1)
        self.assertIn(("game_id", "eq", "0022501195"), updates[0][1])

    def test_max_decimal_odds_cutoff(self):
        self.assertEqual(track.kelly_bet(0.3, 450, 1000), 0)
        self.assertAlmostEqual(track.kelly_bet(0.61, -105, 1111.67), 55.5835)

    @staticmethod
    def _select_rows_router(pending):
        def router(table, **kwargs):
            if table == "predictions":
                filters = kwargs.get("filters", ())
                if any(f[0] == "profit_loss" for f in filters):
                    return pd.DataFrame(columns=["game_date", "profit_loss"])
                return pending
            raise AssertionError(f"Unexpected table read: {table}")

        return router


class UpdateResultsBacklogTests(unittest.TestCase):
    """DP-F3: update_results() must settle every prediction with
    game_date < today (not just yesterday), in game_date order, idempotently,
    leaving postponed/unfinished games pending."""

    def test_settles_a_backlog_row_from_20_days_ago(self):
        old_date = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
        pending_rows = [
            {
                "game_id": "0022500555",
                "game_date": old_date,
                "home_team": "BOS",
                "away_team": "MIA",
                "predicted_winner": "BOS",
                "bet_placed": "BOS",
                "bet_amount": 25.0,
                "odds": "-120",
                "actual_winner": None,
            }
        ]
        teams = pd.DataFrame(
            [
                {"gameId": "0022500555", "teamTricode": "BOS", "score": "101"},
                {"gameId": "0022500555", "teamTricode": "MIA", "score": "95"},
            ]
        )
        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            (column, op, value), = filters
            for row in pending_rows:
                if row["game_id"] == value:
                    row.update(values)
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 1)
        values, filters = updates[0]
        self.assertIn(("game_id", "eq", "0022500555"), filters)
        self.assertEqual(values["actual_winner"], "BOS")
        self.assertEqual(values["correct"], 1)

    def test_running_update_results_twice_is_idempotent(self):
        old_date = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")
        pending_rows = [
            {
                "game_id": "0022500556",
                "game_date": old_date,
                "home_team": "DAL",
                "away_team": "SAS",
                "predicted_winner": "DAL",
                "bet_placed": "DAL",
                "bet_amount": 10.0,
                "odds": "120",
                "actual_winner": None,
            }
        ]
        teams = pd.DataFrame(
            [
                {"gameId": "0022500556", "teamTricode": "DAL", "score": "99"},
                {"gameId": "0022500556", "teamTricode": "SAS", "score": "90"},
            ]
        )
        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            (column, op, value), = filters
            for row in pending_rows:
                if row["game_id"] == value:
                    row.update(values)
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()  # first run settles it
                track.update_results()  # second run must be a no-op

        self.assertEqual(len(updates), 1)

    def test_postponed_game_stays_pending(self):
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        pending_rows = [
            {
                "game_id": "0022500557",
                "game_date": yesterday,
                "home_team": "CHI",
                "away_team": "DET",
                "predicted_winner": "CHI",
                "bet_placed": None,
                "bet_amount": 0.0,
                "odds": None,
                "actual_winner": None,
            }
        ]
        teams = pd.DataFrame(columns=["gameId", "teamTricode", "score"])  # postponed: no scoreboard rows

        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]) as fake_upsert, \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(updates, [])
        self.assertIsNone(pending_rows[0]["actual_winner"])
        fake_upsert.assert_not_called()

    def test_bankroll_recompute_processes_affected_dates_in_chronological_order(self):
        older_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        newer_date = (date.today() - timedelta(days=9)).strftime("%Y-%m-%d")
        pending_rows = [
            {
                "game_id": "0022500559",
                "game_date": older_date,
                "home_team": "POR",
                "away_team": "UTA",
                "predicted_winner": "POR",
                "bet_placed": "POR",
                "bet_amount": 100.0,
                "odds": "100",
                "actual_winner": None,
            },
            {
                "game_id": "0022500560",
                "game_date": newer_date,
                "home_team": "SAC",
                "away_team": "GSW",
                "predicted_winner": "GSW",
                "bet_placed": "GSW",
                "bet_amount": 50.0,
                "odds": "-110",
                "actual_winner": None,
            },
        ]
        teams_by_date = {
            older_date: pd.DataFrame(
                [
                    {"gameId": "0022500559", "teamTricode": "POR", "score": "120"},
                    {"gameId": "0022500559", "teamTricode": "UTA", "score": "100"},
                ]
            ),
            newer_date: pd.DataFrame(
                [
                    {"gameId": "0022500560", "teamTricode": "SAC", "score": "115"},
                    {"gameId": "0022500560", "teamTricode": "GSW", "score": "108"},
                ]
            ),
        }

        def fake_update_rows(table, values, *, filters):
            (column, op, value), = filters
            for row in pending_rows:
                if row["game_id"] == value:
                    row.update(values)
            return []

        upserts = []

        def fake_upsert_rows(table, rows, *, conflict_columns):
            upserts.extend(rows)
            return rows

        def fake_scoreboard(game_date=None):
            return FakeScoreboard(teams_by_date[game_date])

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", side_effect=fake_upsert_rows), \
             patch.object(track.scoreboardv3, "ScoreboardV3", side_effect=fake_scoreboard):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(upserts), 2)
        by_date = {row["date"]: row["balance"] for row in upserts}
        self.assertAlmostEqual(by_date[older_date], 1000.0 + 100.0)  # POR wins even money (+100)
        self.assertAlmostEqual(by_date[newer_date], 1000.0 + 100.0 - 50.0)  # GSW's bet loses (-50)

    def test_kelly_bet_returns_zero_for_a_negative_edge_within_the_odds_cap(self):
        # decimal odds 1.5 (well under the 5.0 cap), but prob*decimal < 1 -> negative edge.
        self.assertEqual(track.kelly_bet(0.5, -200, 1000), 0)

    def test_update_results_settles_a_positive_odds_win(self):
        game_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        pending_rows = [
            {
                "game_id": "0022500558",
                "game_date": game_date,
                "home_team": "ORL",
                "away_team": "ATL",
                "predicted_winner": "ORL",
                "bet_placed": "ORL",
                "bet_amount": 40.0,
                "odds": "150",
                "actual_winner": None,
            }
        ]
        teams = pd.DataFrame(
            [
                {"gameId": "0022500558", "teamTricode": "ORL", "score": "115"},
                {"gameId": "0022500558", "teamTricode": "ATL", "score": "108"},
            ]
        )
        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0]["profit_loss"], 60.0)  # 40 * (150 / 100)

    def test_settling_a_backlog_date_reshifts_every_later_bankroll_row(self):
        # D1 < D2 < D3. D2 and D3 are already settled (bankroll rows for them
        # already exist, computed without D1). This run settles the D1
        # backlog row -- D1's profit_loss shifts the cumulative balance of
        # EVERY later date too, so D2 and D3 must be rewritten as well, not
        # just D1.
        d1 = (date.today() - timedelta(days=15)).strftime("%Y-%m-%d")
        d2 = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        d3 = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")

        pending_rows = [
            {
                "game_id": "0022500561",
                "game_date": d1,
                "home_team": "MEM",
                "away_team": "NOP",
                "predicted_winner": "MEM",
                "bet_placed": "MEM",
                "bet_amount": 100.0,
                "odds": "100",
                "actual_winner": None,
                "profit_loss": None,
            },
            {
                "game_id": "0022500562",
                "game_date": d2,
                "home_team": "LAC",
                "away_team": "PHX",
                "predicted_winner": "LAC",
                "bet_placed": "LAC",
                "bet_amount": None,
                "odds": None,
                "actual_winner": "LAC",  # already settled by an earlier run
                "profit_loss": 50.0,
            },
            {
                "game_id": "0022500563",
                "game_date": d3,
                "home_team": "DEN",
                "away_team": "UTA",
                "predicted_winner": "DEN",
                "bet_placed": "UTA",
                "bet_amount": None,
                "odds": None,
                "actual_winner": "DEN",  # already settled by an earlier run
                "profit_loss": -20.0,
            },
        ]
        teams = pd.DataFrame(
            [
                {"gameId": "0022500561", "teamTricode": "MEM", "score": "110"},
                {"gameId": "0022500561", "teamTricode": "NOP", "score": "100"},
            ]
        )

        def fake_update_rows(table, values, *, filters):
            (column, op, value), = filters
            for row in pending_rows:
                if row["game_id"] == value:
                    row.update(values)
            return []

        upserts = []

        def fake_upsert_rows(table, rows, *, conflict_columns):
            upserts.append(rows)
            return rows

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", side_effect=fake_upsert_rows), \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams)):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()

        self.assertEqual(len(upserts), 1)  # exactly one upsert_rows call, with a list of rows
        by_date = {row["date"]: row["balance"] for row in upserts[0]}
        self.assertEqual(set(by_date), {d1, d2, d3})
        self.assertAlmostEqual(by_date[d1], 1000.0 + 100.0)
        self.assertAlmostEqual(by_date[d2], 1000.0 + 100.0 + 50.0)
        self.assertAlmostEqual(by_date[d3], 1000.0 + 100.0 + 50.0 - 20.0)


class SettlementFinalityTests(unittest.TestCase):
    """DP-F20: update_results() must only settle a game once GameHeader
    reports it final (gameStatus == 3) -- a game merely present in LineScore
    (which lists every game for the date regardless of status) must stay
    pending if it's scheduled, live, postponed, or missing from GameHeader
    entirely. A "final" game with equal/missing scores is also left pending
    (defensive check) instead of fabricating a winner."""

    @staticmethod
    def _pending_row(game_id, game_date):
        return {
            "game_id": game_id,
            "game_date": game_date,
            "home_team": "CHI",
            "away_team": "DET",
            "predicted_winner": "CHI",
            "bet_placed": "CHI",
            "bet_amount": 25.0,
            "odds": "-130",
            "actual_winner": None,
            "profit_loss": None,
        }

    def _run(self, teams_df, headers_df):
        game_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        pending_rows = [self._pending_row("0022500999", game_date)]

        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            (column, op, value), = filters
            for row in pending_rows:
                if row["game_id"] == value:
                    row.update(values)
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]) as fake_upsert, \
             patch.object(track.scoreboardv3, "ScoreboardV3", return_value=FakeScoreboard(teams_df, headers_df)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                track.update_results()

        return updates, fake_upsert, output.getvalue()

    def test_scheduled_not_started_game_stays_pending(self):
        teams = pd.DataFrame(
            [
                {"gameId": "0022500999", "teamTricode": "CHI", "score": "0"},
                {"gameId": "0022500999", "teamTricode": "DET", "score": "0"},
            ]
        )
        headers = pd.DataFrame([{"gameId": "0022500999", "gameStatus": 1, "gameStatusText": "7:00 pm ET"}])

        updates, fake_upsert, _ = self._run(teams, headers)

        self.assertEqual(updates, [])
        fake_upsert.assert_not_called()

    def test_live_in_progress_game_stays_pending(self):
        teams = pd.DataFrame(
            [
                {"gameId": "0022500999", "teamTricode": "CHI", "score": "58"},
                {"gameId": "0022500999", "teamTricode": "DET", "score": "61"},
            ]
        )
        headers = pd.DataFrame([{"gameId": "0022500999", "gameStatus": 2, "gameStatusText": "Q3 4:12"}])

        updates, fake_upsert, _ = self._run(teams, headers)

        self.assertEqual(updates, [])
        fake_upsert.assert_not_called()

    def test_final_game_settles_with_the_right_winner(self):
        teams = pd.DataFrame(
            [
                {"gameId": "0022500999", "teamTricode": "CHI", "score": "101"},
                {"gameId": "0022500999", "teamTricode": "DET", "score": "95"},
            ]
        )
        headers = pd.DataFrame([{"gameId": "0022500999", "gameStatus": 3, "gameStatusText": "Final"}])

        updates, fake_upsert, _ = self._run(teams, headers)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0]["actual_winner"], "CHI")
        fake_upsert.assert_called_once()

    def test_game_in_linescore_but_missing_from_gameheader_stays_pending(self):
        teams = pd.DataFrame(
            [
                {"gameId": "0022500999", "teamTricode": "CHI", "score": "101"},
                {"gameId": "0022500999", "teamTricode": "DET", "score": "95"},
            ]
        )
        headers = pd.DataFrame(columns=["gameId", "gameStatus", "gameStatusText"])  # absent entirely

        updates, fake_upsert, _ = self._run(teams, headers)

        self.assertEqual(updates, [])
        fake_upsert.assert_not_called()

    def test_final_game_with_equal_scores_stays_pending_and_warns(self):
        teams = pd.DataFrame(
            [
                {"gameId": "0022500999", "teamTricode": "CHI", "score": "100"},
                {"gameId": "0022500999", "teamTricode": "DET", "score": "100"},
            ]
        )
        headers = pd.DataFrame([{"gameId": "0022500999", "gameStatus": 3, "gameStatusText": "Final"}])

        updates, fake_upsert, output = self._run(teams, headers)

        self.assertEqual(updates, [])
        fake_upsert.assert_not_called()
        self.assertIn("0022500999", output)
        self.assertIn("arning", output)  # "Warning"/"warning"


class CapSelectionTests(unittest.TestCase):
    """DP-F22: MAX_PENDING_PER_RUN must select the MOST RECENT pending rows
    (order_by game_date descending), then process the selected dates in
    ascending order as before -- so permanently-stuck old rows can never
    occupy every cap slot and starve genuinely newer, settleable rows."""

    def test_newer_settleable_rows_settle_on_the_first_run_despite_stuck_old_rows(self):
        base = date(2020, 1, 1)
        pending_rows = []
        for i in range(5):  # 5 permanently-postponed old rows: never on any scoreboard
            d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            pending_rows.append(
                {
                    "game_id": f"00PPD{i:05d}",
                    "game_date": d,
                    "home_team": "AAA",
                    "away_team": "BBB",
                    "predicted_winner": "AAA",
                    "bet_placed": None,
                    "bet_amount": 0.0,
                    "odds": None,
                    "actual_winner": None,
                }
            )
        newer_dates = []
        for i in range(2):  # 2 genuinely-settleable NEWER rows
            d = (base + timedelta(days=100 + i)).strftime("%Y-%m-%d")
            newer_dates.append(d)
            pending_rows.append(
                {
                    "game_id": f"00NEW{i:05d}",
                    "game_date": d,
                    "home_team": "CCC",
                    "away_team": "DDD",
                    "predicted_winner": "CCC",
                    "bet_placed": "CCC",
                    "bet_amount": 10.0,
                    "odds": "-110",
                    "actual_winner": None,
                }
            )

        def fake_scoreboard(game_date=None):
            if game_date not in newer_dates:
                return FakeScoreboard(pd.DataFrame(columns=["gameId", "teamTricode", "score"]))
            gid = f"00NEW{newer_dates.index(game_date):05d}"
            return FakeScoreboard(
                pd.DataFrame(
                    [
                        {"gameId": gid, "teamTricode": "CCC", "score": "100"},
                        {"gameId": gid, "teamTricode": "DDD", "score": "90"},
                    ]
                )
            )

        updates = []

        def fake_update_rows(table, values, *, filters):
            updates.append((values, filters))
            return []

        with patch.object(track, "select_rows", side_effect=_fake_select_rows(pending_rows)), \
             patch.object(track, "update_rows", side_effect=fake_update_rows), \
             patch.object(track, "upsert_rows", return_value=[]), \
             patch.object(track, "MAX_PENDING_PER_RUN", 3), \
             patch.object(track.scoreboardv3, "ScoreboardV3", side_effect=fake_scoreboard):
            with contextlib.redirect_stdout(io.StringIO()):
                track.update_results()  # a single run

        settled_ids = {value for _, filters in updates for col, op, value in filters if col == "game_id"}
        self.assertEqual(settled_ids, {"00NEW00000", "00NEW00001"})


class SavePredictionTests(unittest.TestCase):
    """TH-F5: save_prediction() -- the only write path for new predictions
    rows -- was entirely untested: the dedup check, the insert, and the
    DuplicateRecordError handling."""

    def test_inserts_a_new_prediction_row_with_the_expected_shape(self):
        inserted = []

        def fake_insert_rows(table, rows):
            inserted.append((table, rows))
            return rows

        with patch.object(track, "select_rows", return_value=pd.DataFrame(columns=["game_id"])), \
             patch.object(track, "insert_rows", side_effect=fake_insert_rows):
            with contextlib.redirect_stdout(io.StringIO()):
                track.save_prediction(
                    game_id=22501195,
                    game_date="2026-04-12",
                    home_team="MIN",
                    away_team="NOP",
                    home_prob="0.55",
                    away_prob="0.45",
                    predicted_winner="MIN",
                    bet_placed="MIN",
                    bet_amount="21.04",
                    odds="188",
                )

        self.assertEqual(len(inserted), 1)
        table, rows = inserted[0]
        self.assertEqual(table, "predictions")
        row = rows[0]
        self.assertEqual(row["game_id"], "0022501195")  # normalized/zero-padded
        self.assertEqual(row["home_win_prob"], 0.55)
        self.assertEqual(row["away_win_prob"], 0.45)
        self.assertEqual(row["bet_amount"], 21.04)
        self.assertEqual(row["odds"], 188)
        self.assertIsNone(row["actual_winner"])
        self.assertIsNone(row["correct"])
        self.assertIsNone(row["profit_loss"])

    def test_already_logged_game_id_skips_the_insert(self):
        with patch.object(track, "select_rows", return_value=pd.DataFrame([{"game_id": "0022501195"}])), \
             patch.object(track, "insert_rows") as fake_insert_rows:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                track.save_prediction(
                    game_id="0022501195",
                    game_date="2026-04-12",
                    home_team="MIN",
                    away_team="NOP",
                    home_prob=0.55,
                    away_prob=0.45,
                    predicted_winner="MIN",
                    bet_placed="MIN",
                    bet_amount=21.04,
                    odds="188",
                )

        fake_insert_rows.assert_not_called()
        self.assertIn("already logged", output.getvalue())

    def test_duplicate_record_error_from_insert_is_caught_not_propagated(self):
        with patch.object(track, "select_rows", return_value=pd.DataFrame(columns=["game_id"])), \
             patch.object(track, "insert_rows", side_effect=database.DuplicateRecordError("dup")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                track.save_prediction(
                    game_id="0022501195",
                    game_date="2026-04-12",
                    home_team="MIN",
                    away_team="NOP",
                    home_prob=0.55,
                    away_prob=0.45,
                    predicted_winner="MIN",
                    bet_placed="MIN",
                    bet_amount=21.04,
                    odds="188",
                )

        self.assertIn("already logged", output.getvalue())


class PrintSummaryTests(unittest.TestCase):
    """TH-F5: smoke test for print_summary() -- must not raise, and must
    print the key totals it reads from the database."""

    def test_print_summary_prints_the_key_totals(self):
        preds = pd.DataFrame(
            [
                {"correct": 1, "profit_loss": 40.0},
                {"correct": 0, "profit_loss": -25.0},
                {"correct": 1, "profit_loss": 15.0},
            ]
        )
        bankroll = pd.DataFrame([{"date": "2026-04-12", "balance": 1030.0}])

        def fake_select_rows(table, **kwargs):
            if table == "predictions":
                return preds
            if table == "bankroll":
                return bankroll
            raise AssertionError(f"Unexpected table read: {table}")

        with patch.object(track, "select_rows", side_effect=fake_select_rows):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                track.print_summary()  # must not raise

        text = output.getvalue()
        self.assertIn("Games predicted:    3", text)
        self.assertIn("Correct:            2", text)
        self.assertIn("Current bankroll:   $1030.00", text)

    def test_print_summary_handles_no_completed_predictions(self):
        with patch.object(track, "select_rows", return_value=pd.DataFrame(columns=["correct"])):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                track.print_summary()  # must not raise

        self.assertIn("No completed predictions yet.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
