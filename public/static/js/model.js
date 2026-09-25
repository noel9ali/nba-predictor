// One view model per game: the /api/slate item merged with the latest /api/live-scores
// entry. The database settles results at the 6 AM run; until then a final from the live
// feed is shown as "unofficial" (DESIGN Round 5).
import { isNum, payout } from "./format.js";

// Latest live entries for tonight, shared by the Games page and the drawer.
export const liveStore = new Map();

export function merge(game, { isPast = false } = {}) {
  const live = isPast ? null : liveStore.get(game.game_id) || null;
  const pickSide = game.pick && game.pick === game.home.tricode ? "home"
    : game.pick && game.pick === game.away.tricode ? "away" : null;
  let status;
  if (game.status === "void" || game.status === "postponed") status = "postponed";
  else if (live && live.status === "postponed") status = "postponed";
  else if (live && (live.status === "live" || live.status === "final")) status = live.status;
  else if (game.status === "final") status = "final";
  else status = isPast ? "pending" : "scheduled";

  const fromLive = Boolean(live && (live.status === "live" || live.status === "final"));
  const homeScore = fromLive ? live.home_score : game.home.score;
  const awayScore = fromLive ? live.away_score : game.away.score;
  const hasScores = isNum(homeScore) && isNum(awayScore);
  let margin = null;
  if (hasScores && pickSide) margin = pickSide === "home" ? homeScore - awayScore : awayScore - homeScore;

  const bet = game.bet;
  let result = null;
  let pl = null;
  const dbSettled = game.status === "final" && (game.result === "hit" || game.result === "miss");
  if (status === "postponed") {
    result = bet ? "void" : null;
    pl = bet ? 0 : null;
  } else if (status === "final") {
    if (dbSettled) result = game.result;
    else if (margin !== null) result = margin > 0 ? "hit" : "miss";
    if (bet) {
      if (dbSettled && isNum(bet.profit_loss)) pl = bet.profit_loss;
      else if (result === "hit") pl = payout(bet.amount, game.odds);
      else if (result === "miss") pl = -bet.amount;
    }
  }
  const unofficial = status === "final" && !dbSettled;
  const clock = live && live.clock ? live.clock : null;
  const period = live && isNum(live.period) ? live.period : null;
  return {
    id: game.game_id, g: game, status, live, pickSide, homeScore, awayScore, hasScores, margin,
    result, pl, unofficial, clock, period, bet,
    tip: game.tip_time_utc ? new Date(game.tip_time_utc) : null,
  };
}

export function isSettledBet(vm) {
  return Boolean(vm.bet) && vm.status === "final" && isNum(vm.pl);
}

export function tipOrder(a, b) {
  const ta = a.tip ? a.tip.getTime() : Infinity;
  const tb = b.tip ? b.tip.getTime() : Infinity;
  return ta - tb || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

// "up 5" / "down 4" / "tied" while live; "won by 8" / "lost by 6" once final.
export function trackText(vm) {
  if (vm.margin === null) return "";
  if (vm.status === "live") return vm.margin > 0 ? `up ${vm.margin}` : vm.margin < 0 ? `down ${-vm.margin}` : "tied";
  if (vm.status === "final") return vm.margin > 0 ? `won by ${vm.margin}` : `lost by ${-vm.margin}`;
  return "";
}

export function sideOf(vm, side) {
  return vm.g[side];
}
