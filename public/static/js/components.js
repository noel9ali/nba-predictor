// Shared pieces of the Games page and the drawer, rebuilt from the canvas boards.
import { h, icon } from "./dom.js";
import { dayShort, isNum, money, odds, pct, record, signClass, signedMoney, signedPct, timeET } from "./format.js";
import { trackText } from "./model.js";
import { logo, nickname, teamClass } from "./teams.js";

// ------------------------------------------------------------------ status chip
export function statusChip(vm, { stale = false, asOf = null, large = false } = {}) {
  const cls = large ? "chip--lg" : "";
  if (vm.status === "live") {
    const text = vm.hasScores ? `Live · ${vm.clock || "in progress"}` : "Live · score unavailable";
    const chip = h("span.chip.chip--live.cond", { class: [cls, stale ? "is-stale" : ""] },
      h("span.dot", { attrs: { "aria-hidden": "true" } }), text);
    if (stale && asOf) chip.append(" ", h("span.asof", `as of ${asOf}`));
    return chip;
  }
  if (vm.status === "final") {
    const label = vm.clock && vm.clock.startsWith("Final") ? vm.clock : overtimeFinal(vm);
    return h("span.chip.chip--final.cond", { class: cls }, label);
  }
  if (vm.status === "postponed") return h("span.chip.chip--postponed.cond", { class: cls }, "Postponed");
  if (vm.status === "pending") return h("span.chip.chip--pending.cond", { class: cls }, "Result pending");
  const t = timeET(vm.g.tip_time_utc);
  return h("span.chip.chip--pre.cond", { class: cls }, t ? `Tip-off ${t} ET` : `Tip-off ${vm.g.date ? dayShort(vm.g.date) : "TBD"}`);
}

function overtimeFinal(vm) {
  if (isNum(vm.period) && vm.period > 4) return vm.period === 5 ? "Final/OT" : `Final/${vm.period - 4}OT`;
  return "Final";
}

// ------------------------------------------------------------------ win probability
export function probBar(game, { mark = false, large = false } = {}) {
  const away = game.away.win_prob;
  const home = game.home.win_prob;
  const bar = h("div.probbar", { class: large ? "probbar--lg" : "", attrs: { "aria-hidden": "true" } });
  if (!isNum(away) || !isNum(home)) {
    bar.append(h("span.seg-away", { class: "team-unknown", style: { width: "100%" } }));
    return bar;
  }
  bar.append(
    h("span.seg-away", { class: teamClass(game.away.tricode), style: { width: `${(away * 100).toFixed(1)}%` } }),
    h("span.seg-home", { class: teamClass(game.home.tricode), style: { width: `${(home * 100).toFixed(1)}%` } }),
  );
  if (mark && isNum(game.implied_prob) && game.pick) {
    // The bar runs away | home; the mark sits where the price's implied probability for
    // the pick would split it.
    const x = game.pick === game.home.tricode ? 1 - game.implied_prob : game.implied_prob;
    bar.append(h("span.implied-mark", { style: { left: `${(x * 100).toFixed(1)}%` } }));
  }
  return bar;
}

export function probLabel(game) {
  return `${pct(game.away.win_prob)} – ${pct(game.home.win_prob)}`;
}

// ------------------------------------------------------------------ L10 strip
export function l10Strip(l10, large = false) {
  if (!l10) return h("span.muted", { attrs: { "aria-label": "Last 10 not available" } }, "—");
  const wins = [...l10].filter((c) => c === "W").length;
  const strip = h("span.l10", { class: large ? "l10--lg" : "", attrs: { role: "img", "aria-label": `Last ${l10.length}: ${wins} won, ${l10.length - wins} lost` } });
  for (const c of l10) strip.append(h("span", { class: c === "W" ? "" : "l" }));
  return strip;
}

export function l10Text(l10) {
  if (!l10) return "—";
  const wins = [...l10].filter((c) => c === "W").length;
  return `${wins}–${l10.length - wins}`;
}

// ------------------------------------------------------------------ odds grid
export function bookGrid(vm, { large = false } = {}) {
  const game = vm.g;
  const grid = game.book_grid;
  if (!grid) {
    if (game.skip_reason === "no_odds") return emptyGrid(game, large);
    return h("p.grid-pending", "Book-by-book prices are recorded from the 2026–27 season.");
  }
  const el = h("div.book-grid", { class: large ? "book-grid--lg" : "", attrs: { role: "table", "aria-label": "Odds at time of bet" } });
  el.append(h("span", { attrs: { role: "columnheader" } }));
  for (const book of grid.books.slice(0, 5)) el.append(h("span.bk-head.cond", { attrs: { role: "columnheader", title: book } }, book));
  const betSide = game.bet ? (game.bet.side === game.home.tricode ? "home" : game.bet.side === game.away.tricode ? "away" : null) : null;
  for (const side of ["away", "home"]) {
    el.append(h("span.bk-team.cond", { attrs: { role: "rowheader" } }, game[side].tricode));
    const prices = grid[side].slice(0, 5);
    const best = grid[`best_${side}_idx`];
    prices.forEach((price, i) => {
      let cls = "";
      if (i === best) cls = betSide === side ? "taken" : "best";
      const label = i === best ? (betSide === side ? " (price taken)" : " (best price)") : "";
      el.append(h("span.bk-cell.cond", { class: cls, attrs: { role: "cell", "aria-label": `${grid.books[i]} ${game[side].tricode} ${isNum(price) ? odds(price) : "no price"}${label}` } },
        isNum(price) ? odds(price) : "—"));
    });
  }
  return el;
}

function emptyGrid(game, large) {
  const el = h("div.book-grid", { class: large ? "book-grid--lg" : "", attrs: { role: "table", "aria-label": "No odds from any book" } });
  el.append(h("span"));
  for (const book of ["DraftKings", "FanDuel", "BetMGM", "BetRivers", "BetUS"]) el.append(h("span.bk-head.cond", book));
  for (const side of ["away", "home"]) {
    el.append(h("span.bk-team.cond", game[side].tricode));
    for (let i = 0; i < 5; i += 1) el.append(h("span.bk-cell.cond", "—"));
  }
  return el;
}

// ------------------------------------------------------------------ bet tag (card footer)
export function betTag(vm) {
  const bet = vm.bet;
  const game = vm.g;
  if (game.skip_reason === "no_odds") return h("span.bet-none.cond", "No odds · no bet");
  if (game.skip_reason === "missing_data") return h("span.bet-none.cond", "No data · no bet");
  if (!bet) return h("span.bet-none.cond", "No bet placed");
  if (vm.status === "postponed") return h("span.bet-none.bet-void.cond", `Void · ${money(bet.amount)} returned`);
  if (vm.status === "final" && vm.result) {
    const wrap = h("div.card-foot-right",
      h("span.bet-settled.cond",
        h("span.amt", `${money(bet.amount)} bet`),
        resultTag(vm.result, vm.pl)));
    if (vm.unofficial) wrap.append(h("span.unofficial.cond", "Unofficial until the 6 AM run"));
    return wrap;
  }
  return h("span.bet-placed.cond", icon("lock", 16, 2.5), `Placed ${money(bet.amount)}`);
}

export function resultTag(result, pl, size = "") {
  if (result === "void") return h("span.result-tag.result-tag--void.cond", { class: size ? `result-tag--${size}` : "" }, "Void");
  if (result !== "hit" && result !== "miss") {
    return h("span.result-tag.result-tag--pending.cond", { class: size ? `result-tag--${size}` : "" }, "Pending");
  }
  const text = result === "hit" ? "Hit" : "Miss";
  return h(`span.result-tag.result-tag--${result}.cond`, { class: size ? `result-tag--${size}` : "" },
    isNum(pl) && Math.round(pl * 100) !== 0 ? `${text} ${signedMoney(pl)}` : text);
}

// ------------------------------------------------------------------ tiles
export function tile(label, value, { valueClass = "", info = null, small = false } = {}) {
  const head = h("div.tile-head", h("span.tile-label.cond", label));
  if (info) head.append(info);
  return h("div.tile", head, h("span.tile-value.cond", { class: [valueClass, small ? "tile-value--sm" : ""] }, value));
}

export function edgeText(edge) {
  return isNum(edge) ? signedPct(edge, 1) : "—";
}

// ------------------------------------------------------------------ game card
export function gameCard(vm, { stale = false, asOf = null, flash = null } = {}) {
  const game = vm.g;
  const cardCls = vm.status === "live" ? "card--live"
    : vm.status === "final" ? (vm.result === "hit" ? "card--hit" : vm.result === "miss" ? "card--miss" : "")
      : "";
  const matchup = `${game.away.tricode} at ${game.home.tricode}`;
  const details = h("button.details-btn.cond", {
    attrs: { type: "button", "aria-label": `Open game detail, ${matchup}` },
    on: { click: (e) => { e.stopPropagation(); openGame(vm.id); } },
  }, "Details", icon("chevronRight", 18, 2.5));
  const card = h("article.card", {
    class: [cardCls, flash ? `flash-${flash}` : ""],
    dataset: { gameId: vm.id },
    attrs: { "aria-label": `${matchup}` },
    on: { click: () => openGame(vm.id) },
  },
  h("div.card-head",
    statusChip(vm, { stale, asOf }),
    h("div.card-head-right",
      h("span.card-edge.cond", "Pregame edge ", h("span", { class: signClass(game.edge) || "muted" }, edgeText(game.edge))),
      details)),
  h("div.card-body",
    h("div.team-grid.team-grid--head.cond",
      h("span"), h("span"), h("span.l10-col", "Last 10"), h("span.r", "Pregame"),
      h("span.r", vm.status === "live" ? "Score" : vm.status === "final" ? "Final" : "")),
    teamLine(vm, "away"), teamLine(vm, "home")),
  h("div.card-odds", h("span.grid-label.cond", "Odds at time of bet"), bookGrid(vm)),
  cardFoot(vm));
  return card;
}

function teamLine(vm, side) {
  const team = vm.g[side];
  const isPick = vm.pickSide === side;
  const other = side === "home" ? vm.awayScore : vm.homeScore;
  const mine = side === "home" ? vm.homeScore : vm.awayScore;
  const started = vm.status === "live" || vm.status === "final";
  let scoreText = "";
  if (started) scoreText = isNum(mine) ? String(mine) : "—";
  const trailing = started && isNum(mine) && isNum(other) && mine < other;
  const meta = [team.record ? record(team.record) : "Record —", `L10 ${l10Text(team.l10)}`].join(" · ");
  return h("div.team-grid",
    logo(team.tricode),
    h("div.team-id",
      h("span.team-abbr.cond", { class: isPick ? "is-pick" : "" }, team.tricode, " ",
        h("span.full", nickname(team.tricode, team.name))),
      h("span.team-meta", meta)),
    h("span.l10-col", l10Strip(team.l10)),
    h("span.team-prob.cond", { class: isPick ? "is-pick" : "" }, pct(team.win_prob)),
    h("span.team-score.cond", { class: trailing ? "trailing" : "" }, scoreText));
}

function cardFoot(vm) {
  const game = vm.g;
  const left = h("div.card-foot-left");
  if (game.skip_reason === "missing_data" && !game.pick) {
    left.append(h("span.pick-line.cond", "No pick"), h("span.book-name.cond", "Team data missing"));
  } else {
    left.append(h("span.pick-line.cond", `Pick ${game.pick || "—"}${isNum(game.odds) ? ` ${odds(game.odds)}` : ""}`));
    if (game.skip_reason === "no_odds") left.append(h("span.book-name.cond", "No odds found"));
    else if (game.skip_reason === "missing_data") left.append(h("span.book-name.cond", "Team data missing"));
    else if (game.bookmaker) left.append(h("span.book-name.cond", game.bookmaker));
  }
  if (vm.status === "postponed") left.append(h("span.track.cond.muted", "Makeup date TBD"));
  else {
    const t = trackText(vm);
    if (t) left.append(h("span.track.cond", { class: vm.margin > 0 ? "pos" : vm.margin < 0 ? "neg" : "" }, t));
  }
  return h("div.card-foot", left, betTag(vm));
}

export function openGame(id) {
  window.location.hash = `#game/${id}`;
}

export function pickLogo(game, size = "sm") {
  return logo(game.pick || "?", size);
}
