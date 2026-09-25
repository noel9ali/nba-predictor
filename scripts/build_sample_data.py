"""Build the sample-mode data behind ?sample=1 (public/sample/*.json).

It's the offseason, so the design can't be reviewed on live data. This script builds a
labelled sample 2026-27 season (Oct 21 - Nov 16, plus "tonight", Nov 17) as fake Supabase
tables, then asks the real API routes for every response through the Flask test client.
Each sample file is therefore exactly what /api/* would return for that data: same shapes
(04-API-CONTRACT), same logic. Nothing here touches the network or Supabase.

The numbers follow design/DESIGN_STATE.md sec1 "Sample data fixes" and the approved canvas:
- the season ends at a $1,111.67 bankroll, $4,275.40 staked, bets 54-41, picks 124-65;
- the nightly bankroll follows the Performance board's timeline (peak $1,177.87 on Nov 5,
  max drawdown $91.67 to Nov 15), and the last 7 nights match the date rail;
- Nov 16 is the draft's "Last night" (TOR a no-bet at -150, edge -2.0%);
- Nov 17 is the Games draft slate. Every bet there is quarter-Kelly capped at 5% of the
  $1,111.67 bankroll, as the design's SAC fix is ($55.58, the hit pays +$52.93); MIA, NYK,
  MIN and CLE follow the same rule (the canvas drew them at $70.65/$25.00/$44.71/$44.42).

Run from the repo root:  venv\\Scripts\\python scripts\\build_sample_data.py
It is deterministic (fixed seed) and rewrites public/sample/ completely.
"""
import json
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Never let the app reach a real project from this script (it only uses fakes anyway).
os.environ["SUPABASE_URL"] = "http://127.0.0.1:9"
os.environ["SUPABASE_SECRET_KEY"] = "sample-build-dummy"
os.environ["NBA_SCHEMA_V2"] = "true"
os.environ.pop("ALLOW_RUN_WORKFLOW", None)
os.environ.pop("VERCEL", None)

import app as dashboard  # noqa: E402

OUT = os.path.join(ROOT, "public", "sample")
SEASON = "2026-27"
FIRST_NIGHT = date(2026, 10, 21)
LAST_NIGHT = date(2026, 11, 16)
TONIGHT = date(2026, 11, 17)
START_BANKROLL = 1000.0
TARGET_STAKED = 4275.40
TARGET_BETS = (54, 41)
TARGET_PICKS = (124, 65)
BOOKS = dashboard.PREFERRED_BOOKS
TEAMS = sorted(dashboard.TEAMS)
TEAM_IDS = {code: 1610612737 + i for i, code in enumerate(TEAMS)}

rng = random.Random(20261117)

# Bankroll after each night, read off the approved Performance board's bankroll line
# (y pixels; $1,000 sits at y=235.6 and $200 spans 201.6 px). Index 0 is the Oct 20 start.
POLY_Y = [235.6, 233.9, 213.6, 211.1, 210.8, 225.4, 222.6, 187.8, 169.6, 136.6, 122.6, 105.1,
          92.7, 125.1, 96.5, 76.3, 56.3, 89.3, 123.6, 137.1, 140.5, 128.3, 144.1, 135.1, 116.5,
          138.8, 148.7, 123.0]
ANCHORS = {0: 1000.00, 16: 1177.87, 20: 1094.30, 21: 1106.40, 22: 1090.80, 23: 1099.75,
           24: 1118.15, 25: 1096.00, 26: 1086.20, 27: 1111.67}
# Pick records on the rail's seven nights (Nov 10-16).
RAIL_PICKS = {date(2026, 11, 10): (4, 2), date(2026, 11, 11): (6, 5), date(2026, 11, 12): (2, 1),
              date(2026, 11, 13): (5, 3), date(2026, 11, 14): (7, 4), date(2026, 11, 15): (3, 3),
              date(2026, 11, 16): (3, 1)}
FIXED_BETS = {date(2026, 11, 14): (1, 3), date(2026, 11, 15): (3, 3), date(2026, 11, 16): (2, 1)}


def cents(x):
    return round(x + 1e-9, 2)


def payout_mult(price):
    return price / 100 if price > 0 else 100 / abs(price)


def profit(stake, price):
    return cents(stake * payout_mult(price))


def implied(price):
    return 100 / (price + 100) if price > 0 else abs(price) / (abs(price) + 100)


def price_for(prob_implied):
    """American price whose implied probability is prob_implied."""
    if prob_implied >= 0.5:
        return -int(round(100 * prob_implied / (1 - prob_implied)))
    return int(round(100 * (1 - prob_implied) / prob_implied))


def kelly_full(p, price):
    b = payout_mult(price)
    return (b * p - (1 - p)) / b


def utc(day, hour_et, minute=0):
    """day at hour_et:minute Eastern (EST, UTC-5 in Nov) as an ISO UTC string."""
    local = datetime(day.year, day.month, day.day, hour_et, minute, tzinfo=timezone(timedelta(hours=-5)))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nights():
    d = FIRST_NIGHT
    while d <= LAST_NIGHT:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------------------- the season
class Game:
    """One prediction (and, when bet, one paper bet)."""

    _next_id = 1

    def __init__(self, day, away, home, pick_side, p_pick, price, bet, won, book,
                 tip_et=(19, 0), stake=0.0, fixed=False, scores=None):
        self.day, self.away, self.home = day, away, home
        self.pick_side, self.p_pick, self.price = pick_side, p_pick, price
        self.bet, self.won, self.book = bet, won, book
        self.tip_et, self.stake, self.fixed, self.scores = tip_et, stake, fixed, scores
        self.game_id = None

    @property
    def pick(self):
        return self.home if self.pick_side == "home" else self.away

    @property
    def pl(self):
        if not self.bet:
            return 0.0
        return profit(self.stake, self.price) if self.won else -cents(self.stake)

    def assign_id(self):
        self.game_id = f"00226{Game._next_id:05d}"
        Game._next_id += 1


def season_targets():
    balances = [ANCHORS.get(i, cents(1000 + (235.6 - y) / 1.008)) for i, y in enumerate(POLY_Y)]
    days = list(nights())
    assert len(days) == len(balances) - 1
    return {d: (balances[i], cents(balances[i + 1] - balances[i])) for i, d in enumerate(days)}


def early_pick_records(days):
    """94-46 over the 20 nights before the rail (124-65 minus the rail's 30-19)."""
    wins = [5] * 14 + [4] * 6
    losses = [3] * 6 + [2] * 14
    rng.shuffle(wins)
    rng.shuffle(losses)
    return dict(zip(days, zip(wins, losses)))


def bet_counts(pick_records, targets):
    """Bets won/lost per night. Losing nights get the extra losing bets and winning nights the
    extra winners, so each night can reach its P/L with realistic stakes."""
    free = [d for d in pick_records if d not in FIXED_BETS]
    fixed_w = sum(w for w, _ in FIXED_BETS.values())
    fixed_l = sum(l for _, l in FIXED_BETS.values())
    need_w, need_l = TARGET_BETS[0] - fixed_w, TARGET_BETS[1] - fixed_l
    counts = {d: [2, 1] for d in free}
    by_target = sorted(free, key=lambda d: targets[d][1])
    extra_l = need_l - len(free)
    for d in [d for d in by_target if pick_records[d][1] >= 2][:extra_l]:
        counts[d][1] = 2
    ups = [d for d in reversed(by_target) if pick_records[d][0] >= 3 and targets[d][1] > 0]
    downs = [d for d in by_target if targets[d][1] < 0 and d not in ups]
    pairs = min(8, len(ups), len(downs))
    ups, downs = ups[:pairs], downs[:pairs]
    for d in ups:
        counts[d][0] = 3
    for d in downs:
        counts[d][0] = 1
    assert sum(c[0] for c in counts.values()) == need_w
    assert sum(c[1] for c in counts.values()) == need_l
    counts.update({d: list(v) for d, v in FIXED_BETS.items()})
    return counts


def random_pick(won_bet, dog=False):
    """(model probability for the pick, American price). The pick is always the side the
    model favours (p >= 0.5); a bet needs the price to imply less than p (edge > 0).
    dog=True prices a winning bet as a modest underdog: the market disagrees with the model."""
    if won_bet is None:  # no bet: the price is at or above the model's probability
        p = rng.uniform(0.53, 0.72)
        imp = min(0.9, p + rng.uniform(0.0, 0.06))
    elif dog:
        imp = rng.uniform(0.38, 0.46)
        p = rng.uniform(max(0.51, imp + 0.04), min(0.6, imp + 0.16))
    elif won_bet:  # a winning bet on a winning night: a solid favourite
        imp = rng.uniform(0.58, 0.70)
        p = min(0.82, imp + rng.uniform(0.015, 0.1))
    else:
        imp = rng.uniform(0.52, 0.66)
        p = min(0.8, imp + rng.uniform(0.015, 0.11))
    price = price_for(imp)
    if -100 < price < 100 or price in (-100, 100):
        price = 102 if imp < 0.5 else -102
    return round(p, 2), price


def solve_night_stakes(bets, target, cap, want_avg=46.6):
    """Stakes (cents) for this night's bets so their P/L is exactly target. Of the feasible
    random draws, keep the one whose stakes sit closest to the season's average bet size."""
    free = [g for g in bets if not g.fixed]
    if not free:
        return cents(sum(g.pl for g in bets)) == target
    free_l = [g for g in free if not g.won]
    free_w = [g for g in free if g.won]
    best, feasible = None, 0
    for _ in range(6000):
        for g in free:
            g.stake = cents(rng.uniform(8.0, cap))
        if free_l:  # one free loser absorbs the rest, exactly in cents
            anchor = free_l[0]
            rest = sum(g.pl for g in bets if g is not anchor)
            need = cents(rest - target)
            if not 5.0 <= need <= cap:
                continue
            anchor.stake = need
        else:  # a free winner absorbs it: find a stake whose rounded profit fits
            anchor = free_w[0]
            want = cents(target - sum(x.pl for x in bets if x is not anchor))
            base = int(round(want / payout_mult(anchor.price) * 100))
            hits = [c for c in range(base - 3, base + 4)
                    if 500 <= c <= cap * 100 and profit(c / 100, anchor.price) == want]
            if not hits:
                continue
            anchor.stake = hits[0] / 100
        feasible += 1
        score = abs(sum(g.stake for g in free) - want_avg * len(free))
        if best is None or score < best[0]:
            best = (score, [g.stake for g in free])
        if feasible >= 250:
            break
    if best is None:
        return False
    for g, stake in zip(free, best[1]):
        g.stake = stake
    return True


def book_prices(pick_price, bettable):
    """Five books' prices for the picked side (the recorded price is the unique best) and
    the other side (a vigged mirror)."""
    pick_row, other_row = [], []
    other_center = price_for(min(0.95, 1 - implied(pick_price) + rng.uniform(0.03, 0.05)))
    for _ in BOOKS:
        worse = rng.choice([2, 3, 4, 5, 6, 8, 10])
        p = pick_price - worse if pick_price < 0 else pick_price - worse
        if -100 < p < 100:
            p = -100 - (100 - abs(p)) if pick_price < 0 else 100
        pick_row.append(p)
        o = other_center + rng.choice([-6, -4, -2, 0, 2, 4])
        if -100 < o < 100:
            o = 100 if o >= 0 else -100
        other_row.append(o)
    return pick_row, other_row


def build_history():
    targets = season_targets()
    days = list(nights())
    picks = early_pick_records([d for d in days if d not in RAIL_PICKS])
    picks.update(RAIL_PICKS)
    bets = bet_counts(picks, targets)
    all_games = []

    fixed = fixed_nights()
    for day in days:
        start_balance, target = targets[day]
        cap = cents(0.05 * start_balance - 0.005)
        pw, pl = picks[day]
        bw, bl = bets[day]
        games = list(fixed.get(day, []))
        known_w = sum(1 for g in games if g.won)
        known_l = sum(1 for g in games if not g.won)
        known_bw = sum(1 for g in games if g.bet and g.won)
        known_bl = sum(1 for g in games if g.bet and not g.won)
        used = {t for g in games for t in (g.home, g.away)}
        pool = [t for t in TEAMS if t not in used]
        rng.shuffle(pool)
        todo = []
        todo += [(True, True)] * (bw - known_bw) + [(False, True)] * (bl - known_bl)
        todo += [(True, False)] * (pw - known_w - (bw - known_bw))
        todo += [(False, False)] * (pl - known_l - (bl - known_bl))
        for won, bet in todo:
            away, home = pool.pop(), pool.pop()
            p, price = random_pick(won if bet else None, dog=(bet and won and target < 0))
            games.append(Game(day, away, home, rng.choice(["home", "away"]), p, price, bet, won,
                              rng.choice(BOOKS)))
        night_bets = [g for g in games if g.bet]
        if not solve_night_stakes(night_bets, target, cap, want_avg=0.85 * cap):
            raise SystemExit(f"could not solve stakes for {day}")
        assert cents(sum(g.pl for g in night_bets)) == target, day
        rng.shuffle(games)
        games.sort(key=lambda g: (not g.fixed, g.tip_et))  # fixed games keep their order
        for i, g in enumerate(games):
            if not g.fixed:
                g.tip_et = rng.choice([(19, 0), (19, 30), (20, 0), (20, 30), (21, 0), (22, 0), (22, 30)])
        games.sort(key=lambda g: (g.tip_et, g.fixed))
        all_games.append((day, games))
    balance_staked(all_games, targets)
    return all_games, targets


def balance_staked(all_games, targets):
    """Shift stake between a winning and a losing bet on the same night (keeping that
    night's P/L to the cent) until the season's total staked is exactly the target."""
    def staked():
        return cents(sum(g.stake for _, gs in all_games for g in gs if g.bet))

    for _ in range(200):
        delta = cents(TARGET_STAKED - staked())
        if delta == 0:
            return
        for day, games in all_games:
            delta = cents(TARGET_STAKED - staked())
            if delta == 0:
                return
            cap = cents(0.05 * targets[day][0] - 0.005)
            winners = [g for g in games if g.bet and g.won and not g.fixed]
            losers = [g for g in games if g.bet and not g.won and not g.fixed]
            goal = delta if abs(delta) <= 6 else max(-4.0, min(4.0, delta / 2))
            best = None
            for w in winners:
                for l in losers:
                    for c in range(-500, 501):
                        new_w = cents(w.stake + c / 100)
                        if not 5 <= new_w <= cap:
                            continue
                        new_l = cents(l.stake + profit(new_w, w.price) - profit(w.stake, w.price))
                        if not 5 <= new_l <= cap:
                            continue
                        change = cents(new_w - w.stake + new_l - l.stake)
                        if best is None or abs(change - goal) < abs(best[0] - goal):
                            best = (change, w, new_w, l, new_l)
            if best and best[0] != 0:
                _, w, new_w, l, new_l = best
                w.stake, l.stake = new_w, new_l
    raise SystemExit(f"could not balance staked (off by {cents(TARGET_STAKED - staked())})")


def fixed_nights():
    """Nov 15 and Nov 16 games that appear on the canvas (Performance log, Last night)."""
    def g(day, away, home, side, p, price, bet, won, book, tip, stake=0.0, scores=None):
        return Game(day, away, home, side, p, price, bet, won, book, tip, stake, True, scores)

    nov15, nov16 = date(2026, 11, 15), date(2026, 11, 16)
    return {
        nov15: [
            g(nov15, "BOS", "MIA", "away", 0.62, -150, True, False, "FanDuel", (19, 30), 16.80),
            g(nov15, "NYK", "CLE", "home", 0.60, -125, True, True, "DraftKings", (19, 0), 24.50),
            g(nov15, "LAL", "GSW", "away", 0.54, 102, True, False, "BetUS", (22, 0), 21.90),
            g(nov15, "SAC", "DEN", "home", 0.68, -190, True, True, "BetMGM", (21, 0), 12.60),
        ],
        nov16: [
            g(nov16, "TOR", "WAS", "away", 0.58, -150, False, True, "BetRivers", (19, 0), scores=(99, 94)),
            g(nov16, "CHI", "ATL", "home", 0.56, 110, True, False, "BetMGM", (19, 30), 22.40, scores=(121, 116)),
            g(nov16, "DAL", "OKC", "home", 0.71, -210, True, True, "FanDuel", (20, 0), 41.10, scores=(105, 118)),
            g(nov16, "PHI", "BKN", "away", 0.64, -135, True, True, "DraftKings", (20, 30), 38.20, scores=(114, 102)),
        ],
    }


# Tonight (Nov 17): the Games draft slate. (away, home, pick side, p_pick, price, book,
# stake, tip, away prices, home prices)
TONIGHT_GAMES = [
    ("MIA", "ORL", "away", 0.61, 105, "FanDuel", 55.58, (19, 0),
     [103, 105, 102, -103, -103], [-119, -124, -125, -119, -112]),
    ("BOS", "NYK", "home", 0.58, -118, "DraftKings", 23.46, (19, 30),
     [100, 104, 103, 105, 102], [-118, -126, -124, -121, -126]),
    ("DEN", "MIN", "home", 0.53, 124, "BetMGM", 41.96, (20, 0),
     [-142, -142, -152, -150, -145], [118, 116, 124, 122, 121]),
    ("CLE", "MIL", "away", 0.66, -150, "DraftKings", 41.69, (20, 0),
     [-150, -156, -156, -158, -155], [122, 132, 130, 131, 133]),
    ("LAL", "PHX", "away", 0.55, -140, "BetRivers", 0.0, (22, 0),
     [-142, -146, -146, -140, -145], [115, 123, 118, 119, 121]),
    ("GSW", "SAC", "home", 0.61, -105, "FanDuel", 55.58, (22, 30),
     [-104, -117, -115, -111, -105], [-113, -105, -107, -111, -110]),
]
TONIGHT_BANKROLL = 1111.67


# ---------------------------------------------------------------------------- tables
class Tables:
    def __init__(self):
        self.predictions, self.book_odds, self.bankroll, self.games = [], [], [], []
        self.features, self.elo, self.model_runs, self.workflow_log = [], [], [], []

    def as_dict(self):
        return {"predictions": self.predictions, "book_odds": self.book_odds,
                "bankroll": self.bankroll, "games": self.games, "features": self.features,
                "elo": self.elo, "model_runs": self.model_runs, "workflow_log": self.workflow_log}


TEAM_BASE = {}


def team_base(code):
    if code not in TEAM_BASE:
        r = random.Random(f"base-{code}")
        TEAM_BASE[code] = {
            "elo": r.uniform(1420, 1640), "PTS": r.uniform(106, 121), "FG_PCT": r.uniform(0.445, 0.495),
            "REB": r.uniform(41, 47), "AST": r.uniform(23, 30), "TOV": r.uniform(11.8, 15.8),
            "STOCKS": r.uniform(11, 17),
        }
    return TEAM_BASE[code]


def side_features(prefix, code, rest, override=None):
    base = team_base(code)
    vals = {k: base[k] + random.Random(f"{code}-{rest}-{k}").uniform(-1.2, 1.2) * (0.01 if k == "FG_PCT" else 1)
            for k in ("PTS", "FG_PCT", "REB", "AST", "TOV", "STOCKS")}
    if override:
        vals.update(override)
    row = {f"{prefix}_TEAM_ABBREVIATION": code, f"{prefix}_TEAM_ID": TEAM_IDS[code],
           f"{prefix}_rest_days": str(float(rest))}
    for k, v in vals.items():
        row[f"{prefix}_roll_{k}"] = round(v, 3 if k == "FG_PCT" else 1)
    return row


def add_context(tables, day, away, home, rest_away, rest_home, overrides=None):
    overrides = overrides or {}
    row = {"GAME_DATE": day.isoformat()}
    row.update(side_features("HOME", home, rest_home, overrides.get(home)))
    row.update(side_features("AWAY", away, rest_away, overrides.get(away)))
    tables.features.append(row)
    elo = {c: overrides.get(c, {}).get("elo", team_base(c)["elo"]) for c in (home, away)}
    tables.elo.append({"GAME_DATE": day.isoformat(), "HOME_TEAM_ID": TEAM_IDS[home],
                       "AWAY_TEAM_ID": TEAM_IDS[away], "HOME_ELO": round(elo[home], 1),
                       "AWAY_ELO": round(elo[away], 1)})


def prediction_row(g, status, bankroll_at_bet, with_kelly):
    p_home = g.p_pick if g.pick_side == "home" else round(1 - g.p_pick, 2)
    settled = status == "final"
    home_won = None
    if settled:
        home_won = (g.pick_side == "home") == g.won
    row = {
        "game_id": g.game_id, "game_date": g.day.isoformat(), "home_team": g.home, "away_team": g.away,
        "home_win_prob": p_home, "away_win_prob": round(1 - p_home, 2), "predicted_winner": g.pick,
        "actual_winner": (g.home if home_won else g.away) if settled else None,
        "correct": (1 if g.won else 0) if settled else None,
        "bet_placed": g.pick if g.bet else None, "bet_amount": cents(g.stake) if g.bet else 0.0,
        "odds": g.price, "profit_loss": g.pl if (settled and g.bet) else (0.0 if settled else None),
        "season": SEASON, "tip_time_utc": utc(g.day, *g.tip_et), "bookmaker": g.book,
        "implied_prob": round(implied(g.price), 4) if g.price else None,
        "edge": round(g.p_pick - implied(g.price), 4) if g.price else None,
        "bankroll_at_bet": bankroll_at_bet if g.bet else None,
        "kelly_full": round(kelly_full(g.p_pick, g.price), 4) if (g.bet and with_kelly) else None,
        "kelly_fraction": 0.25 if (g.bet and with_kelly) else None,
        "model_name": "legacy-calibrated-logistic",
        "predicted_at": utc(g.day, 18, 31), "status": status,
        "home_score": None, "away_score": None, "skip_reason": None,
    }
    if settled:
        if g.scores:
            away_pts, home_pts = g.scores
        else:
            win_pts = rng.randint(101, 128)
            lose_pts = win_pts - rng.randint(2, 17)
            home_pts, away_pts = (win_pts, lose_pts) if home_won else (lose_pts, win_pts)
        row["home_score"], row["away_score"] = home_pts, away_pts
    return row


def add_book_odds(tables, g, away_prices=None, home_prices=None):
    if away_prices is None:
        pick_row, other_row = book_prices(g.price, g.bet)
        # The recorded book carries the recorded (best) price for the picked side.
        i = BOOKS.index(g.book)
        pick_row[i] = g.price
        away_prices, home_prices = (pick_row, other_row) if g.pick_side == "away" else (other_row, pick_row)
        if rng.random() < 0.12:  # the odd book with no line
            j = rng.choice([k for k in range(len(BOOKS)) if k != i])
            away_prices[j] = home_prices[j] = None
    for book, a, h in zip(BOOKS, away_prices, home_prices):
        if a is None and h is None:
            continue
        tables.book_odds.append({"game_id": g.game_id, "bookmaker": book, "home_price": h, "away_price": a})


def add_games_rows(tables, g, row):
    home_won = row["actual_winner"] == g.home
    for code, won in ((g.home, home_won), (g.away, not home_won)):
        tables.games.append({"GAME_DATE": g.day.isoformat(), "TEAM_ABBREVIATION": code,
                             "WL": "W" if won else "L", "SEASON": SEASON})


def build_tables(history, targets, tonight_variant="base"):
    Game._next_id = 1
    tables = Tables()
    last_played = {}
    # Preseason context rows so every team has a features/Elo row before its first game.
    teams = list(TEAMS)
    for i in range(0, len(teams), 2):
        add_context(tables, date(2026, 10, 16), teams[i + 1], teams[i], 3, 3)
        add_context(tables, date(2026, 10, 17), teams[i], teams[i + 1], 3, 3)
    for day, games in history:
        start_balance = targets[day][0]
        for g in games:
            g.assign_id()
            rest = {c: min(3, (day - last_played.get(c, day - timedelta(days=4))).days - 1) for c in (g.home, g.away)}
            row = prediction_row(g, "final", start_balance, with_kelly=False)
            tables.predictions.append(row)
            add_book_odds(tables, g)
            add_games_rows(tables, g, row)
            add_context(tables, day, g.away, g.home, rest[g.away], rest[g.home])
            last_played[g.home] = last_played[g.away] = day
        tables.bankroll.append({"date": day.isoformat(), "balance": cents(start_balance + targets[day][1])})
    tables.bankroll.insert(0, {"date": (FIRST_NIGHT - timedelta(days=1)).isoformat(), "balance": START_BANKROLL})
    # The drawer on the canvas (Detail-A) shows GSW @ SAC's tale of the tape.
    add_context(tables, LAST_NIGHT, "GSW", "SAC", 1, 2, overrides={
        "GSW": {"elo": 1528.0, "PTS": 114.2, "FG_PCT": 0.461, "REB": 43.0, "AST": 28.9, "TOV": 14.8, "STOCKS": 15.2},
        "SAC": {"elo": 1561.0, "PTS": 117.8, "FG_PCT": 0.483, "REB": 44.6, "AST": 26.4, "TOV": 13.1, "STOCKS": 13.9},
    })
    tonight = tonight_games(tables, tonight_variant)
    tables.model_runs.append({
        "trained_at": "2026-11-17T11:04:00Z", "production_model": "legacy-calibrated-logistic",
        "cutoff_date": "2025-02-25", "test_games": 1596,
        "leaderboard": [
            {"rank": 1, "model": "current-xgboost", "test_games": 1596, "accuracy": 0.6704,
             "log_loss": 0.6082, "brier_score": 0.2100, "roc_auc": 0.7241, "baseline_home_win_rate": 0.5501},
            {"rank": 5, "model": "legacy-calibrated-logistic", "test_games": 1596, "accuracy": 0.6817,
             "log_loss": 0.6194, "brier_score": 0.2089, "roc_auc": 0.7295, "baseline_home_win_rate": 0.5501},
        ],
    })
    tables.workflow_log.extend([
        {"run_date": "2026-11-17", "kind": "predict", "trigger": "schedule", "started_at": "2026-11-17T23:30:05Z",
         "finished_at": "2026-11-17T23:31:40Z", "status": "success", "pipeline_ok": None, "predict_ok": True,
         "sms_sent": True, "notes": "6 games · 5 bets logged"},
        {"run_date": "2026-11-17", "kind": "morning", "trigger": "schedule", "started_at": "2026-11-17T11:00:04Z",
         "finished_at": "2026-11-17T11:02:37Z", "status": "success", "pipeline_ok": True, "predict_ok": None,
         "sms_sent": True, "notes": ""},
    ])
    return tables, tonight


TONIGHT_ID_BASE = {"nobets": 99101}


def tonight_games(tables, variant, first_id=None):
    if variant == "none":
        return []
    if variant in TONIGHT_ID_BASE:
        Game._next_id = TONIGHT_ID_BASE[variant]
    elif first_id is not None:
        Game._next_id = first_id
    games = []
    for away, home, side, p, price, book, stake, tip, a_prices, h_prices in TONIGHT_GAMES:
        g = Game(TONIGHT, away, home, side, p, price, stake > 0, None, book, tip, stake, True)
        g.assign_id()
        if variant == "nobets":
            g.bet, g.stake = False, 0.0
            if away != "LAL":  # LAL -140 stays the closest to a bet (edge -3.3%)
                g.price = price_for(min(0.92, g.p_pick + rng.uniform(0.045, 0.08)))
                g.book = rng.choice(BOOKS)
                a_prices = h_prices = None
        row = prediction_row(g, "scheduled", TONIGHT_BANKROLL, with_kelly=True)
        tables.predictions.append(row)
        add_book_odds(tables, g, a_prices, h_prices)
        games.append(g)
    return games


# ---------------------------------------------------------------------------- API calls
class FakeSelect:
    """database.select_rows over in-memory tables (eq/in/range filters, ordering, limit)."""

    def __init__(self, tables):
        self.tables = tables

    def __call__(self, table, *, columns="*", filters=(), order_by=None, descending=False,
                 limit=None, page_size=1000):
        import pandas as pd

        rows = [dict(r) for r in self.tables.get(table, [])]
        for column, op, value in filters:
            rows = [r for r in rows if match(r.get(column), op, value)]
        order = [order_by] if isinstance(order_by, str) else list(order_by or [])
        for column in reversed(order):
            name = column[0] if isinstance(column, tuple) else column
            desc = column[1] if isinstance(column, tuple) else descending
            rows.sort(key=lambda r: (r.get(name) is None, r.get(name)), reverse=desc)
        if limit is not None:
            rows = rows[:limit]
        if columns != "*":
            wanted = [c.strip() for c in columns.split(",")]
            rows = [{c: r.get(c) for c in wanted} for r in rows]
        return pd.DataFrame(rows)


def match(value, op, expected):
    if op == "eq":
        return value == expected
    if op == "is":
        return value is None
    if op == "not_is":
        return value is not None
    if op == "in":
        return value in expected
    if value is None:
        return False
    return {"gte": value >= expected, "lte": value <= expected, "gt": value > expected,
            "lt": value < expected}[op]


def fetch(tables, url, today=TONIGHT, now="2026-11-18T02:05:00Z"):
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    with patch.object(dashboard, "select_rows", FakeSelect(tables.as_dict())), \
            patch.object(dashboard, "today_et", lambda: today), \
            patch.object(dashboard, "now_utc", lambda: now_dt), \
            patch.dict(os.environ, {"NBA_SCHEMA_V2": "true"}):
        response = dashboard.app.test_client().get(url)
    if response.status_code != 200:
        raise SystemExit(f"{url} -> {response.status_code} {response.get_data(as_text=True)}")
    body = response.get_json()
    body["generated_at"] = now
    return body


def write(name, body):
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        fh.write("\n")


def all_predictions(tables, today=TONIGHT):
    first = fetch(tables, f"/api/predictions?season={SEASON}&page_size=100&page=1", today)
    rows = list(first["rows"])
    page = 2
    while len(rows) < first["total"]:
        rows += fetch(tables, f"/api/predictions?season={SEASON}&page_size=100&page={page}", today)["rows"]
        page += 1
    first.update(rows=rows, page=1, page_size=max(1, len(rows)))
    return first


# ---------------------------------------------------------------------------- live scores
def live(fetched_at, games):
    return {"generated_at": fetched_at, "fetched_at": fetched_at, "stale": False, "source": "sample",
            "games": games}


def lg(game_id, status, period=None, clock=None, away=None, home=None, postponed=False):
    return {"game_id": game_id, "status": status, "period": period, "clock": clock,
            "home_score": home, "away_score": away, "postponed": postponed}


def live_files(ids):
    mia, nyk, min_, cle, phx, sac = ids
    pre = lambda gid: lg(gid, "scheduled")  # noqa: E731
    fin = lambda gid, a, h, ot=False: lg(gid, "final", 5 if ot else 4, "Final/OT" if ot else "Final", a, h)  # noqa: E731
    files = {
        "live-pre": live("2026-11-17T23:59:00Z", [pre(i) for i in ids]),
        "live-live": live("2026-11-18T02:05:00Z", [
            fin(mia, 112, 104), lg(nyk, "live", 3, "Q3 4:40", 71, 76), lg(min_, "live", 2, "Q2 1:05", 48, 44),
            lg(cle, "live", 2, "Q2 3:30", 45, 47), pre(phx), pre(sac)]),
        "live-sofar": live("2026-11-18T03:40:00Z", [
            fin(mia, 112, 104), fin(nyk, 101, 108), lg(min_, "live", 4, "Q4 3:10", 98, 96),
            fin(cle, 99, 105), lg(phx, "live", 2, "Q2 5:20", 52, 49), lg(sac, "live", 1, "Q1 4:12", 11, 14)]),
        "live-final": live("2026-11-18T06:05:00Z", [
            fin(mia, 112, 104), fin(nyk, 101, 108), fin(min_, 110, 104), fin(cle, 99, 105),
            fin(phx, 115, 109), fin(sac, 110, 118)]),
        "live-failed": live("2026-11-18T00:12:00Z", [
            lg(mia, "live", 1, "Q1 6:12", 9, 7), pre(nyk), pre(min_), pre(cle), pre(phx), pre(sac)]),
    }
    replay = [
        ("2026-11-17T23:59:00Z", [pre(i) for i in ids]),
        ("2026-11-18T00:00:30Z", [lg(mia, "live", 1, "Q1 11:48", 2, 0), pre(nyk), pre(min_), pre(cle), pre(phx), pre(sac)]),
        ("2026-11-18T00:31:00Z", [lg(mia, "live", 2, "Q2 8:10", 30, 26), lg(nyk, "live", 1, "Q1 11:20", 3, 2),
                                  pre(min_), pre(cle), pre(phx), pre(sac)]),
        ("2026-11-18T01:02:00Z", [lg(mia, "live", 3, "Q3 10:02", 64, 60), lg(nyk, "live", 2, "Q2 9:31", 30, 33),
                                  lg(min_, "live", 1, "Q1 11:40", 2, 0), lg(cle, "live", 1, "Q1 11:35", 0, 3), pre(phx), pre(sac)]),
        ("2026-11-18T02:20:00Z", [fin(mia, 112, 104), lg(nyk, "live", 4, "Q4 6:12", 88, 92),
                                  lg(min_, "live", 3, "Q3 2:40", 76, 72), lg(cle, "live", 3, "Q3 1:15", 74, 80), pre(phx), pre(sac)]),
        ("2026-11-18T03:31:00Z", [fin(mia, 112, 104), fin(nyk, 101, 108), lg(min_, "live", 4, "Q4 4:02", 96, 94),
                                  fin(cle, 99, 105), lg(phx, "live", 2, "Q2 7:30", 44, 43), lg(sac, "live", 1, "Q1 11:50", 0, 2)]),
        ("2026-11-18T05:55:00Z", [fin(mia, 112, 104), fin(nyk, 101, 108), fin(min_, 110, 104), fin(cle, 99, 105),
                                  fin(phx, 115, 109), fin(sac, 110, 118)]),
    ]
    for i, (at, games) in enumerate(replay):
        files[f"live-replay-{i}"] = live(at, games)
    return files


# ---------------------------------------------------------------------------- variants
def schedule_only(slate, phase):
    """Tonight before picks exist: the schedule, with every model/odds field empty."""
    body = json.loads(json.dumps(slate))
    body["phase"] = phase
    for g in body["games"]:
        for side in ("home", "away"):
            g[side]["win_prob"] = None
        g.update(pick=None, pick_prob=None, odds=None, bookmaker=None, implied_prob=None, edge=None,
                 bet=None, result=None, book_grid=None, skip_reason=None)
    body["summary"].update(bets_placed=0, staked=0.0, settled_pl=0.0)
    return body


def edges_slate(tables):
    """The Round 6 card edge cases on one slate (sample scene "edges")."""
    Game._next_id = 99001
    specs = [
        ("DEN", "MIN", "home", 0.53, 124, "BetMGM", 41.96, (20, 0), None),
        ("GSW", "SAC", "home", 0.61, -105, "FanDuel", 55.58, (19, 0), None),
        ("CLE", "MIL", "away", 0.66, -150, "DraftKings", 41.69, (19, 30), "postponed"),
        ("BOS", "NYK", "home", 0.58, -118, "DraftKings", 23.46, (20, 30), "partial"),
        ("LAL", "PHX", "away", 0.55, None, None, 0.0, (22, 0), "no_odds"),
        ("ATL", "CHI", "home", 0.58, -118, "DraftKings", 23.46, (19, 30), None),
        ("HOU", "DAL", "home", 0.57, None, None, 0.0, (21, 30), "missing_data"),
    ]
    ids = []
    for away, home, side, p, price, book, stake, tip, case in specs:
        g = Game(TONIGHT, away, home, side, p, price or -110, stake > 0, None, book or "FanDuel", tip, stake, True)
        g.assign_id()
        row = prediction_row(g, "postponed" if case == "postponed" else "scheduled", TONIGHT_BANKROLL, True)
        if case in ("no_odds", "missing_data"):
            row.update(odds=None, bookmaker=None, implied_prob=None, edge=None, skip_reason=case)
            if case == "missing_data":
                row.update(home_win_prob=None, away_win_prob=None, predicted_winner=None)
        tables.predictions.append(row)
        if case == "partial":
            add_book_odds(tables, g, [100, 104, 103, None, None], [-118, -126, -124, None, None])
        elif case not in ("no_odds", "missing_data"):
            add_book_odds(tables, g)
        ids.append(g.game_id)
    return ids


def main():
    history, targets = build_history()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    tables, tonight = build_tables(history, targets)
    ids = [g.game_id for g in tonight]
    season_dates = [d.isoformat() for d, _ in history]

    # Tonight and every past night.
    base = fetch(tables, f"/api/slate?date={TONIGHT}")
    write(f"slate-{TONIGHT}", base)
    for day in season_dates:
        write(f"slate-{day}", fetch(tables, f"/api/slate?date={day}"))
    write(f"slate-{TONIGHT}-before", schedule_only(base, "before_predictions"))
    write(f"slate-{TONIGHT}-failed", schedule_only(base, "prediction_failed"))

    # Every game's drawer.
    for row in tables.predictions:
        write(f"game-{row['game_id']}", fetch(tables, f"/api/game/{row['game_id']}"))

    write("days", fetch(tables, f"/api/days?end={TONIGHT}&n=31"))
    write("performance", fetch(tables, f"/api/performance?season={SEASON}"))
    write("predictions", all_predictions(tables))
    write("model", fetch(tables, f"/api/model?season={SEASON}"))
    write("workflow-status", fetch(tables, "/api/workflow-status"))
    failed_tables = Tables()
    failed_tables.workflow_log = [
        {"run_date": "2026-11-17", "kind": "predict", "trigger": "schedule", "started_at": "2026-11-17T23:00:03Z",
         "finished_at": "2026-11-17T23:01:12Z", "status": "failed", "pipeline_ok": None, "predict_ok": False,
         "sms_sent": False, "notes": "prediction run failed (exit code 1)"},
        tables.workflow_log[1],
    ]
    write("workflow-status-failed", fetch(failed_tables, "/api/workflow-status", now="2026-11-18T00:12:00Z"))

    # No bets tonight.
    nobets_tables, nobets_games = build_tables(history, targets, tonight_variant="nobets")
    write(f"slate-{TONIGHT}-nobets", fetch(nobets_tables, f"/api/slate?date={TONIGHT}"))
    for g in nobets_games:
        write(f"game-{g.game_id}", fetch(nobets_tables, f"/api/game/{g.game_id}"))

    # Offseason: the day after the sample season, as the real site looks today.
    off_tables, _ = build_tables(history, targets, tonight_variant="none")
    off = fetch(off_tables, "/api/slate", today=date(2027, 7, 20), now="2027-07-20T19:00:00Z")
    write(f"slate-{TONIGHT}-offseason", off)

    # Card edge cases.
    edge_tables, _ = build_tables(history, targets, tonight_variant="none")
    edge_ids = edges_slate(edge_tables)
    write(f"slate-{TONIGHT}-edges", fetch(edge_tables, f"/api/slate?date={TONIGHT}"))
    for gid in edge_ids:
        write(f"game-{gid}", fetch(edge_tables, f"/api/game/{gid}"))
    den, sac, cle, nyk, phx, chi, dal = edge_ids
    write("live-edges", live("2026-11-18T03:50:00Z", [
        lg(den, "live", 5, "OT 2:31", 118, 116), lg(sac, "final", 5, "Final/OT", 121, 126),
        lg(cle, "postponed", None, None, None, None, True), lg(nyk, "scheduled"),
        lg(phx, "scheduled"), lg(chi, "live", 2, "Q2 5:10", None, None), lg(dal, "scheduled")]))

    # Early season: tonight is the first night, nothing settled.
    early = Tables()
    tonight_games(early, "base", first_id=int(ids[0][5:]))
    early.bankroll = [{"date": "2026-11-16", "balance": START_BANKROLL}]
    write("performance-early", fetch(early, f"/api/performance?season={SEASON}"))
    write("predictions-early", all_predictions(early))

    for name, body in live_files(ids).items():
        write(name, body)

    perf = json.load(open(os.path.join(OUT, "performance.json"), encoding="utf-8"))
    k = perf["kpis"]
    print(f"bankroll {k['bankroll']}  staked {k['staked']}  bets {k['bets']}  picks {k['picks']}  "
          f"drawdown {k['max_drawdown']}")
    print(f"wrote {len(os.listdir(OUT))} files to {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
