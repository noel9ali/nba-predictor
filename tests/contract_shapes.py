"""Response shapes from integration-docs/04-API-CONTRACT.md, shared by the endpoint tests
and the sample-data tests so the API and public/sample/*.json can't drift apart.

A shape is a type (str, bool, NUM, INT), an Opt(shape) (the value may be null), an
Enum(...) of allowed values, a one-element list [shape] (a list of that shape), or a dict
{key: shape}. Dicts are checked for the exact key set: no missing and no extra keys.
"""
import re

NUM = "number"
INT = "int"


class Opt:
    def __init__(self, shape):
        self.shape = shape


class Enum:
    def __init__(self, *values):
        self.values = values


class Pattern:
    def __init__(self, regex):
        self.regex = re.compile(regex)


DATE = Pattern(r"^\d{4}-\d{2}-\d{2}$")
GAME_ID = Pattern(r"^\d{10}$")
SEASON = Pattern(r"^\d{4}-\d{2}$")
RECORD = Pattern(r"^\d+-\d+$")
TIMESTAMP = Pattern(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
ENVELOPE = {"generated_at": TIMESTAMP, "migration_pending": bool}

TEAM = {
    "tricode": str, "name": Opt(str), "record": Opt(RECORD), "l10": Opt(Pattern(r"^[WL]{0,10}$")),
    "win_prob": Opt(NUM), "score": Opt(INT),
}
BET = {
    "side": Opt(str), "amount": NUM, "bankroll_at_bet": Opt(NUM), "kelly_full": Opt(NUM),
    "kelly_fraction": Opt(NUM), "result": Opt(Enum("hit", "miss", "void")),
    "profit_loss": Opt(NUM),
}
BOOK_GRID = {
    "books": [str], "home": [Opt(INT)], "away": [Opt(INT)],
    "best_home_idx": Opt(INT), "best_away_idx": Opt(INT),
}
GAME = {
    "game_id": GAME_ID, "date": Opt(DATE), "tip_time_utc": Opt(TIMESTAMP),
    "status": Enum("scheduled", "final", "postponed", "void"),
    "home": TEAM, "away": TEAM, "pick": Opt(str), "pick_prob": Opt(NUM), "odds": Opt(INT),
    "bookmaker": Opt(str), "implied_prob": Opt(NUM), "edge": Opt(NUM), "bet": Opt(BET),
    "result": Opt(Enum("hit", "miss", "void")),
    "skip_reason": Opt(Enum("no_odds", "missing_data")), "book_grid": Opt(BOOK_GRID),
}
BET_REF = {"game_id": GAME_ID, "profit_loss": NUM}
RECAP = {
    "net_pl": NUM, "bankroll_before": Opt(NUM), "bankroll_after": Opt(NUM),
    "picks": RECORD, "bets": RECORD, "staked": NUM, "roi": Opt(NUM),
    "best_bet": Opt(BET_REF), "worst_bet": Opt(BET_REF),
}
SLATE = {
    **ENVELOPE, "date": DATE, "season": SEASON, "is_past": bool,
    "phase": Enum("before_predictions", "picks_posted", "all_final", "no_games",
                  "prediction_failed"),
    "offseason": bool, "last_slate_date": Opt(DATE),
    "summary": {"games": INT, "final": INT, "live": INT, "upcoming": INT,
                "bets_placed": INT, "staked": NUM, "settled_pl": NUM},
    "games": [GAME], "recap": Opt(RECAP),
}
TAPE_SIDE = {
    "elo": Opt(NUM), "rest_days": Opt(NUM), "roll_pts": Opt(NUM), "roll_fg_pct": Opt(NUM),
    "roll_reb": Opt(NUM), "roll_ast": Opt(NUM), "roll_tov": Opt(NUM), "roll_stocks": Opt(NUM),
}
GAME_DETAIL = {
    **ENVELOPE, "game": GAME,
    "tape": {"home": TAPE_SIDE, "away": TAPE_SIDE, "better": "better"},
    "predicted_at": Opt(TIMESTAMP), "model_name": Opt(str),
    "result": Opt({"winner": Opt(str), "home_score": Opt(INT), "away_score": Opt(INT),
                   "correct": Opt(INT)}),
}
DAYS = {
    **ENVELOPE, "has_earlier": bool,
    "days": [{"date": DATE, "games": INT, "picks": RECORD, "bets": RECORD, "net_pl": NUM,
              "pending": INT}],
}
SPLIT = {"key": str, "bets": INT, "w": INT, "l": INT, "staked": NUM, "pl": NUM, "roi": Opt(NUM)}
PERFORMANCE = {
    **ENVELOPE, "season": Pattern(r"^(\d{4}-\d{2}|all)$"), "seasons": [SEASON],
    "kpis": {
        "bankroll": Opt(NUM), "start_bankroll": NUM, "net_pl": NUM, "roi": Opt(NUM),
        "staked": NUM, "bets": RECORD, "picks": RECORD, "accuracy": Opt(NUM),
        "max_drawdown": {"amount": NUM, "peak_date": Opt(DATE), "trough_date": Opt(DATE)},
        "longest_win_streak": INT, "longest_loss_streak": INT, "pending": INT,
    },
    "series": [{"date": DATE, "bankroll": NUM, "nightly_pl": NUM, "bets": RECORD,
                "picks": RECORD, "pending": INT}],
    "splits": {"book": [SPLIT], "confidence": [SPLIT], "edge": [SPLIT]},
    "recent_bets": [Enum("W", "L")],
}
PREDICTION_ROW = {
    "game_id": GAME_ID, "date": DATE, "matchup": str, "home": str, "away": str,
    "pick": Opt(str), "pick_prob": Opt(NUM), "odds": Opt(INT), "bookmaker": Opt(str),
    "edge": Opt(NUM), "bet_amount": NUM,
    "result": Enum("hit", "miss", "pending", "void"), "profit_loss": Opt(NUM),
}
PREDICTIONS = {
    **ENVELOPE, "season": Pattern(r"^(\d{4}-\d{2}|all)$"), "total": INT, "page": INT,
    "page_size": INT, "books": [str], "rows": [PREDICTION_ROW],
}
MODEL = {
    **ENVELOPE, "production_model": Opt(str), "trained_at": Opt(TIMESTAMP),
    "cutoff_date": Opt(DATE),
    "test": Opt({"games": Opt(INT), "accuracy": Opt(NUM), "brier": Opt(NUM),
                 "log_loss": Opt(NUM), "roc_auc": Opt(NUM),
                 "baseline_home_win_rate": Opt(NUM)}),
    "season_live": {"season": SEASON, "picks": INT, "accuracy": Opt(NUM)},
    "calibration": [{"bucket": Pattern(r"^\d\.\d{2}-\d\.\d{2}$"), "n": INT, "predicted": NUM,
                     "actual": NUM}],
    "leaderboard": [{"rank": Opt(INT), "model": Opt(str), "accuracy": Opt(NUM),
                     "log_loss": Opt(NUM), "brier_score": Opt(NUM)}],
}
WORKFLOW_RUN = {
    "run_date": Opt(DATE), "started_at": Opt(TIMESTAMP), "finished_at": Opt(TIMESTAMP),
    "status": Enum("running", "success", "partial", "failed"),
    "state": Enum("ok", "running", "failed", "missed"), "trigger": Opt(str),
    "pipeline_ok": Opt(bool), "predict_ok": Opt(bool), "sms_sent": Opt(bool), "notes": str,
}
WORKFLOW_STATUS = {
    **ENVELOPE, "controls_allowed": bool, "running": bool,
    "latest": {"morning": Opt(WORKFLOW_RUN), "predict": Opt(WORKFLOW_RUN),
               "manual": Opt(WORKFLOW_RUN)},
}
LIVE_SCORES = {
    "generated_at": TIMESTAMP, "fetched_at": TIMESTAMP, "stale": bool, "source": str,
    "games": [{"game_id": GAME_ID, "status": Enum("scheduled", "live", "final", "postponed"),
               "period": Opt(INT), "clock": Opt(str), "home_score": Opt(INT),
               "away_score": Opt(INT), "postponed": bool}],
}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check(value, shape, path="$"):
    """Return a list of human-readable mismatches (empty when value matches shape)."""
    if isinstance(shape, Opt):
        return [] if value is None else check(value, shape.shape, path)
    if shape == "better":
        ok = isinstance(value, dict) and all(v in ("home", "away") for v in value.values())
        return [] if ok else [f"{path}: expected a {{stat: home|away}} map"]
    if shape is NUM:
        return [] if _is_number(value) else [f"{path}: expected a number, got {value!r}"]
    if shape is INT:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return [] if ok else [f"{path}: expected an int, got {value!r}"]
    if shape is bool:
        return [] if isinstance(value, bool) else [f"{path}: expected a bool, got {value!r}"]
    if shape is str:
        return [] if isinstance(value, str) else [f"{path}: expected a string, got {value!r}"]
    if isinstance(shape, Enum):
        return [] if value in shape.values else [f"{path}: {value!r} not in {shape.values}"]
    if isinstance(shape, Pattern):
        ok = isinstance(value, str) and shape.regex.match(value)
        return [] if ok else [f"{path}: {value!r} doesn't match {shape.regex.pattern}"]
    if isinstance(shape, list):
        if not isinstance(value, list):
            return [f"{path}: expected a list, got {type(value).__name__}"]
        errors = []
        for i, item in enumerate(value):
            errors += check(item, shape[0], f"{path}[{i}]")
        return errors
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return [f"{path}: expected an object, got {type(value).__name__}"]
        errors = []
        missing = set(shape) - set(value)
        extra = set(value) - set(shape)
        if missing:
            errors.append(f"{path}: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"{path}: unexpected keys {sorted(extra)}")
        for key in set(shape) & set(value):
            errors += check(value[key], shape[key], f"{path}.{key}")
        return errors
    raise TypeError(f"unknown shape {shape!r}")
