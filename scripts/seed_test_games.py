"""Create a deterministic local NBA game database for branch testing."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path


TEAMS = (
    (1001, "ATL", "Test Hawks"),
    (1002, "BOS", "Test Celtics"),
    (1003, "DAL", "Test Mavericks"),
    (1004, "LAL", "Test Lakers"),
)

GAME_COLUMNS = (
    "SEASON_ID",
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
    "GAME_ID",
    "GAME_DATE",
    "MATCHUP",
    "WL",
    "MIN",
    "PTS",
    "FGM",
    "FGA",
    "FG_PCT",
    "FG3M",
    "FG3A",
    "FG3_PCT",
    "FTM",
    "FTA",
    "FT_PCT",
    "OREB",
    "DREB",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "PF",
    "PLUS_MINUS",
    "SEASON",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default="data/nba.db",
        help="SQLite database to seed (default: data/nba.db)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="Number of days of two-game history to create (default: 45)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Replace the games and derived prediction tables",
    )
    return parser.parse_args()


def build_rows(days: int) -> list[tuple[object, ...]]:
    if days < 12:
        raise ValueError("--days must be at least 12 for the rolling window")

    rows: list[tuple[object, ...]] = []
    start = date.today() - timedelta(days=days - 1)
    season = f"{start.year}-{str(start.year + 1)[-2:]}"

    for day_number in range(days):
        game_date = start + timedelta(days=day_number)
        matchups = ((TEAMS[0], TEAMS[1]), (TEAMS[2], TEAMS[3]))
        if day_number % 2:
            matchups = tuple((away, home) for home, away in matchups)

        for game_number, (home, away) in enumerate(matchups, start=1):
            game_id = f"TEST-{game_date:%Y%m%d}-{game_number}"
            home_score = 104 + ((day_number + game_number) % 11)
            away_score = 98 + ((day_number * 2 + game_number) % 9)
            if day_number % 5 == 0:
                home_score, away_score = away_score, home_score

            for team, opponent, score, opponent_score, is_home in (
                (home, away, home_score, away_score, True),
                (away, home, away_score, home_score, False),
            ):
                won = score > opponent_score
                fg3m = 7 + ((day_number + team[0]) % 5)
                fg3a = fg3m + 10
                fgm = (score - (3 * fg3m) - 8) // 2
                fga = fgm + 12
                ftm = score - (2 * fgm) - (3 * fg3m)
                fta = max(ftm + 3, 8)
                rows.append(
                    (
                        "2K",
                        team[0],
                        team[1],
                        team[2],
                        game_id,
                        game_date.isoformat(),
                        f"{team[1]} vs. {opponent[1]}"
                        if is_home
                        else f"{team[1]} @ {opponent[1]}",
                        "W" if won else "L",
                        240,
                        score,
                        fgm,
                        fga,
                        round(fgm / fga, 3),
                        fg3m,
                        fg3a,
                        round(fg3m / fg3a, 3),
                        ftm,
                        fta,
                        round(ftm / fta, 3),
                        10,
                        30,
                        40,
                        22 + ((day_number + team[0]) % 8),
                        6,
                        5,
                        11,
                        18,
                        score - opponent_score,
                        season,
                    )
                )
    return rows


def seed_database(db_path: str, days: int, reset: bool) -> int:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        if reset:
            for table in ("games", "elo", "features", "predictions", "bankroll"):
                connection.execute(f"DROP TABLE IF EXISTS {table}")
        elif connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='games'"
        ).fetchone():
            raise RuntimeError(
                f"{path} already contains games; rerun with --reset to replace it"
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                SEASON_ID TEXT,
                TEAM_ID INTEGER,
                TEAM_ABBREVIATION TEXT,
                TEAM_NAME TEXT,
                GAME_ID TEXT,
                GAME_DATE TEXT,
                MATCHUP TEXT,
                WL TEXT,
                MIN INTEGER,
                PTS INTEGER,
                FGM INTEGER,
                FGA INTEGER,
                FG_PCT REAL,
                FG3M INTEGER,
                FG3A INTEGER,
                FG3_PCT REAL,
                FTM INTEGER,
                FTA INTEGER,
                FT_PCT REAL,
                OREB INTEGER,
                DREB INTEGER,
                REB INTEGER,
                AST INTEGER,
                STL INTEGER,
                BLK INTEGER,
                TOV INTEGER,
                PF INTEGER,
                PLUS_MINUS REAL,
                SEASON TEXT
            )
            """
        )
        placeholders = ", ".join("?" for _ in GAME_COLUMNS)
        columns = ", ".join(GAME_COLUMNS)
        connection.executemany(
            f"INSERT INTO games ({columns}) VALUES ({placeholders})",
            build_rows(days),
        )
        connection.commit()
    finally:
        connection.close()
    return days * 4


def main() -> None:
    args = parse_args()
    count = seed_database(args.db_path, args.days, args.reset)
    print(f"Seeded {count} team-game rows in {args.db_path}")
    print("Run src\\elo.py, src\\features.py, and src\\model.py to exercise the pipeline.")


if __name__ == "__main__":
    main()
