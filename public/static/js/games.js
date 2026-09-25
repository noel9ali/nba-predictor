// Games page (DESIGN Rounds 2 and 4-6): tonight's slate with its hero states, the All games
// toolbar and cards, Last night, live refresh, toasts and flashes; past nights with the date
// rail and night recap; and the page states (before the run, run failed, no games/offseason).
import { SAMPLE, api, now, sampleTonight, todayET } from "./api.js";
import {
  bookGrid, edgeText, gameCard, l10Strip, l10Text, probBar, probLabel, resultTag, statusChip, tile,
} from "./components.js";
import { clear, h, icon, mount, prefersReducedMotion } from "./dom.js";
import { infoButton, closeExplainer } from "./explainers.js";
import {
  addDays, countdown, dayLong, dayShort, isNum, money, odds, pct, record, recordParts, signClass,
  signedMoney, signedPct, timeET, weekday,
} from "./format.js";
import { LiveFeed } from "./live.js";
import { isSettledBet, liveStore, merge, tipOrder, trackText } from "./model.js";
import { logo, nickname } from "./teams.js";
import { pipelineStatus, runNow, setRefreshStatus } from "./topbar.js";
import { toast } from "./toast.js";

const FILTERS = [["all", "All"], ["bets", "Bets"], ["live", "Live"], ["upcoming", "Upcoming"], ["final", "Final"]];
const SORTS = [["tip", "Tip-off"], ["edge", "Edge"], ["bet", "Bet size"]];
const FLASH_MS = 10000;

// Filter/sort survive re-renders within a visit.
const prefs = { filter: "all", sort: "tip" };
let currentCtx = null;

export async function renderGames(main, route) {
  const tonight = SAMPLE ? sampleTonight() : todayET();
  const date = route.date && route.date !== tonight ? route.date : null;
  return date ? renderPastNight(main, date, tonight) : renderTonight(main, tonight);
}

// ============================================================================= tonight
async function renderTonight(main) {
  const slate = await api.slate();
  const view = h("div.view");
  mount(main, view);
  const ctx = {
    slate, view, feed: null, heroKey: null, prevStatus: new Map(), flashes: new Map(),
    lastNight: null, timers: [], disposed: false,
  };
  liveStore.clear();
  currentCtx = ctx;

  if (slate.last_slate_date && slate.phase !== "no_games") {
    api.slate(slate.last_slate_date).then((s) => {
      ctx.lastNight = s;
      if (!ctx.disposed) draw(ctx);
    }).catch(() => {});
  }
  if (slate.phase === "no_games") {
    await drawNoGames(ctx);
    return () => { ctx.disposed = true; };
  }

  draw(ctx, { initial: true });
  if (shouldPoll(ctx)) startFeed(ctx);
  else {
    // Start polling from two minutes before the first tip.
    ctx.timers.push(window.setInterval(() => {
      if (!ctx.feed && shouldPoll(ctx)) startFeed(ctx);
    }, 15000));
  }
  // Countdown ticks.
  ctx.timers.push(window.setInterval(() => {
    const el = ctx.view.querySelector("[data-countdown]");
    if (el) {
      const text = countdownText(Number(el.dataset.countdown));
      if (text) el.textContent = text;
    }
  }, 15000));

  return () => {
    ctx.disposed = true;
    if (ctx.feed) ctx.feed.stop();
    ctx.timers.forEach((t) => window.clearInterval(t));
    for (const t of ctx.flashes.values()) window.clearTimeout(t);
    setRefreshStatus(null);
  };
}

function shouldPoll(ctx) {
  const games = ctx.slate.games;
  if (!games.length) return false;
  if (games.every((g) => g.status === "final" || g.status === "void" || g.status === "postponed")) return false;
  const tips = games.map((g) => (g.tip_time_utc ? Date.parse(g.tip_time_utc) : null)).filter((t) => t !== null);
  if (!tips.length) return true; // no tip times recorded: poll so live games still show up
  return now().getTime() >= Math.min(...tips) - 2 * 60 * 1000;
}

function startFeed(ctx) {
  ctx.feed = new LiveFeed({
    date: ctx.slate.date,
    onScores: (games) => applyScores(ctx, games),
    onStatus: (status) => {
      if (ctx.disposed) return;
      ctx.liveStatus = status;
      setRefreshStatus({ ...status, onRefresh: () => ctx.feed.retry() });
      drawBanner(ctx);
      drawChipsStale(ctx);
    },
  });
  ctx.feed.start();
}

function applyScores(ctx, games) {
  for (const entry of games) liveStore.set(entry.game_id, entry);
  const vms = ctx.slate.games.map((g) => merge(g));
  const prevHero = ctx.lastHeroGame;
  const events = [];
  for (const vm of vms) {
    const before = ctx.prevStatus.get(vm.id);
    // The first poll only sets the baseline: games already live or final when the page
    // opened aren't news.
    if (ctx.hadScores && before && before !== vm.status) events.push({ vm, from: before, to: vm.status });
    ctx.prevStatus.set(vm.id, vm.status);
  }
  ctx.hadScores = true;
  if (!ctx.disposed) {
    draw(ctx);
    announce(events, vms, prevHero);
  }
  return vms.length > 0 && vms.every((vm) => vm.status === "final" || vm.status === "postponed");
}

function announce(events, vms, prevHero) {
  const ctx = currentCtx;
  for (const { vm, from, to } of events) {
    const g = vm.g;
    const matchup = `${g.away.tricode} @ ${g.home.tricode}`;
    if (to === "live" && (from === "scheduled" || from === "pending")) {
      let text = "is live.";
      if (prevHero === vm.id) {
        // The hero hands off (DESIGN Round 5): say where the game went and what's next.
        const hero = pickHero(vms);
        const next = hero.mode === "next" ? `${hero.vm.g.away.tricode} @ ${hero.vm.g.home.tricode} is next up.`
          : "Tonight so far is up top.";
        text = `is live. It moved to All games; ${next}`;
      }
      toast({ kind: "live", tag: "Tip-off", strong: matchup, text });
      flash(ctx, vm.id, "live");
    } else if (to === "final") {
      const home = { t: g.home.tricode, s: vm.homeScore };
      const away = { t: g.away.tricode, s: vm.awayScore };
      const [w, l] = isNum(home.s) && isNum(away.s) && home.s >= away.s ? [home, away] : [away, home];
      const score = isNum(w.s) ? `${w.t} ${w.s}, ${l.t} ${l.s}.` : `${matchup} is final.`;
      let text;
      if (vm.bet && vm.result) {
        const settled = vms.filter(isSettledBet).reduce((sum, x) => sum + x.pl, 0);
        text = `Bet ${vm.result === "hit" ? "hit" : "missed"}, ${signedMoney(vm.pl)}. Settled P/L now ${signedMoney(settled)}.`;
      } else if (vm.result) {
        text = `Pick ${vm.result === "hit" ? "hit" : "missed"}, no bet.`;
      } else text = "";
      toast({ kind: vm.result === "miss" ? "miss" : "hit", tag: "Final", strong: score, text });
      flash(ctx, vm.id, vm.result === "miss" ? "miss" : "hit");
    }
  }
}

function flash(ctx, id, kind) {
  if (prefersReducedMotion()) return; // reduced motion: no flash, only the toast
  window.clearTimeout(ctx.flashes.get(id));
  ctx.flashKinds = ctx.flashKinds || new Map();
  ctx.flashKinds.set(id, kind);
  const card = ctx.view.querySelector(`.card[data-game-id="${id}"]`);
  if (card) card.classList.add(`flash-${kind}`);
  ctx.flashes.set(id, window.setTimeout(() => {
    ctx.flashKinds.delete(id);
    const el = ctx.view.querySelector(`.card[data-game-id="${id}"]`);
    if (el) el.classList.remove("flash-live", "flash-hit", "flash-miss");
  }, FLASH_MS));
}

// ----------------------------------------------------------------------------- hero choice
function pickHero(vms) {
  if (!vms.length) return { mode: "none" };
  const allFinal = vms.every((vm) => vm.status === "final" || vm.status === "postponed");
  if (allFinal) return { mode: "recap" };
  const bets = vms.filter((vm) => vm.bet && vm.status !== "postponed");
  if (!bets.length) return { mode: "nobets" };
  const unstarted = bets.filter((vm) => vm.status === "scheduled")
    .sort((a, b) => (b.g.edge ?? -1) - (a.g.edge ?? -1));
  if (unstarted.length) return { mode: "next", vm: unstarted[0] };
  return { mode: "sofar" };
}

// ----------------------------------------------------------------------------- drawing
function draw(ctx, { initial = false } = {}) {
  const { slate } = ctx;
  const vms = slate.games.map((g) => merge(g));
  if (initial) for (const vm of vms) ctx.prevStatus.set(vm.id, vm.status);
  const hero = pickHero(vms);
  const heroKey = hero.mode === "next" ? `next-${hero.vm.id}` : hero.mode;
  const fade = ctx.heroKey !== null && ctx.heroKey !== heroKey && !prefersReducedMotion();
  ctx.heroKey = heroKey;
  ctx.lastHeroGame = hero.mode === "next" ? hero.vm.id : null;

  // Keep focus on the same control across a redraw (polls redraw every 30 s).
  const active = document.activeElement;
  const focusKey = active && ctx.view.contains(active) ? focusSignature(active) : null;
  const heroHasOpenExplainer = ctx.view.querySelector(".hero-wrap .explainer");

  const parts = [];
  if (slate.phase === "before_predictions" || slate.phase === "prediction_failed") {
    parts.push(...drawPrePicks(ctx, vms));
  } else {
    parts.push(headerTonight(ctx, vms));
    parts.push(h("div", { attrs: { id: "banner-slot" } }));
    const heroWrap = heroSection(ctx, hero, vms);
    if (fade) heroWrap.classList.add("fade-in");
    if (heroHasOpenExplainer && !fade) {
      parts.push(ctx.view.querySelector(".hero-wrap"));
    } else {
      closeExplainer();
      parts.push(heroWrap);
    }
    parts.push(allGames(ctx, vms, hero));
  }
  const ln = lastNightSection(ctx);
  if (ln) parts.push(ln);
  mount(ctx.view, parts);
  drawBanner(ctx);
  drawChipsStale(ctx);
  if (focusKey) restoreFocus(ctx.view, focusKey);
}

function focusSignature(el) {
  const card = el.closest("[data-game-id]");
  return { key: el.dataset.focusKey || el.getAttribute("aria-label") || el.textContent, game: card ? card.dataset.gameId : null };
}

function restoreFocus(root, sig) {
  const scope = sig.game ? root.querySelector(`[data-game-id="${sig.game}"]`) : root;
  if (!scope) return;
  const candidates = scope.querySelectorAll("button, a[href], input, select");
  for (const el of candidates) {
    if ((el.dataset.focusKey || el.getAttribute("aria-label") || el.textContent) === sig.key) {
      el.focus({ preventScroll: true });
      return;
    }
  }
}

function drawBanner(ctx) {
  const slot = ctx.view.querySelector("#banner-slot");
  if (!slot) return;
  const status = ctx.liveStatus;
  if (status && status.kind === "stale" && status.down) {
    const since = status.since ? timeET(status.since.toISOString()) : null;
    mount(slot, h("div.banner", { attrs: { role: "status" } },
      h("span.banner-main", icon("warn", 20, 2.2), h("span.banner-title.cond", since ? `Live scores unavailable since ${since}` : "Live scores unavailable")),
      h("span.banner-text", "Picks, odds and bets below are unaffected. Results still settle in the 6 AM run."),
      h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: () => ctx.feed && ctx.feed.retry() } }, "Retry")));
  } else clear(slot);
}

function drawChipsStale(ctx) {
  const status = ctx.liveStatus;
  const stale = Boolean(status && status.kind === "stale");
  const asOf = stale && status.at ? timeET(status.at.toISOString()) : null;
  for (const chip of ctx.view.querySelectorAll(".chip--live")) {
    chip.classList.toggle("is-stale", stale);
    let tag = chip.querySelector(".asof");
    if (stale && asOf) {
      if (!tag) {
        tag = h("span.asof");
        chip.append(" ", tag);
      }
      tag.textContent = `as of ${asOf}`;
    } else if (tag) tag.remove();
  }
}

function headerTonight(ctx, vms) {
  const counts = countStatuses(vms);
  const betVms = vms.filter((vm) => vm.bet);
  const staked = betVms.reduce((s, vm) => s + vm.bet.amount, 0);
  const settled = vms.filter(isSettledBet).reduce((s, vm) => s + vm.pl, 0);
  const livePicks = vms.filter((vm) => vm.status === "live" && vm.pickSide && vm.margin !== null);
  const ahead = livePicks.filter((vm) => vm.margin > 0).length;
  const sub = h("div.subline.cond",
    h("span.date", dayLong(ctx.slate.date)),
    h("span", `${vms.length} games · ${counts.final} final · `, h("span.live-count", `${counts.live} live`), ` · ${counts.upcoming} upcoming`));
  if (ctx.slate.last_slate_date) {
    sub.append(h("a.btn.cond", { attrs: { href: `#night/${ctx.slate.last_slate_date}` } }, icon("calendar", 18, 2.2), "Past nights"));
  }
  return h("header.page-head",
    h("div.page-head-text", h("h1.display.cond", "Tonight's slate"), sub),
    h("div.stat-tiles",
      stat("Bets placed", String(betVms.length)),
      stat("Total staked", money(staked), "accent"),
      stat("Settled P/L", signedMoney(settled), signClass(settled)),
      stat("Live picks ahead", livePicks.length ? `${ahead} of ${livePicks.length}` : "—")));
}

function stat(label, value, cls = "") {
  return h("div.stat", h("span.stat-label.cond", label), h("span.stat-value.cond", { class: cls }, value));
}

function countStatuses(vms) {
  return {
    final: vms.filter((vm) => vm.status === "final").length,
    live: vms.filter((vm) => vm.status === "live").length,
    upcoming: vms.filter((vm) => vm.status === "scheduled").length,
  };
}

// ----------------------------------------------------------------------------- hero
function heroSection(ctx, hero, vms) {
  const wrap = h("section.hero-wrap", { attrs: { "aria-labelledby": "hero-title" } });
  if (hero.mode === "next") {
    wrap.append(h("h2.section-title.cond", { attrs: { id: "hero-title" } }, "Next up · biggest edge"), heroNext(hero.vm));
  } else if (hero.mode === "sofar") {
    wrap.append(h("h2.section-title.cond", { attrs: { id: "hero-title" } }, "Tonight so far"), heroSoFar(vms));
  } else if (hero.mode === "recap") {
    wrap.append(h("h2.section-title.cond", { attrs: { id: "hero-title" } }, "Tonight · all final"), recapBlock(ctx.slate, vms, { unofficial: true }));
  } else if (hero.mode === "nobets") {
    wrap.append(h("h2.section-title.cond", { attrs: { id: "hero-title" } }, "Next up · biggest edge"), heroNoBets(vms));
  }
  return wrap;
}

function countdownText(tipMs) {
  const left = tipMs - now().getTime();
  return left > 0 && left <= 60 * 60 * 1000 ? countdown(left) : "";
}

function heroNext(vm) {
  const g = vm.g;
  const tipMs = vm.tip ? vm.tip.getTime() : null;
  const cd = tipMs ? countdownText(tipMs) : "";
  const headline = h("span.headline.cond", { class: "accent" }, icon("lock", 18, 2.5), `Bet placed · ${money(vm.bet.amount)}`);
  const mid = h("div.hero-mid",
    h("div.hero-mid-top", statusChip(vm, { large: true }),
      cd ? h("span.countdown.cond", { dataset: { countdown: tipMs } }, cd) : (tipMs ? h("span.countdown.cond", { dataset: { countdown: tipMs } }) : null),
      headline),
    h("div.prob-block",
      h("div.prob-caption.cond", h("span.label-with-info", "Pregame win probability", infoButton("prob", g)), h("span", probLabel(g))),
      probBar(g)),
    h("div.tiles4",
      tile("Pick", g.pick || "—"),
      tile("Odds taken", odds(g.odds), { info: infoButton("implied", g) }),
      tile("Edge", edgeText(g.edge), { valueClass: signClass(g.edge), info: infoButton("edge", g) }),
      tile("Bet placed", money(vm.bet.amount), { valueClass: "accent", info: infoButton("bet", g, { alignRight: true }) })),
    h("div.prob-block",
      h("span.grid-label.cond", g.bookmaker ? `Odds at time of bet · ${g.bookmaker} price taken` : "Odds at time of bet"),
      bookGrid(vm, { large: true })));
  return h("div.hero", heroTeam(vm, "away"), mid, heroTeam(vm, "home"));
}

function heroTeam(vm, side) {
  const team = vm.g[side];
  const started = vm.status === "live" || vm.status === "final";
  const score = side === "home" ? vm.homeScore : vm.awayScore;
  const big = started ? (isNum(score) ? String(score) : "—") : pct(team.win_prob);
  const small = started ? [pct(team.win_prob), "pregame"] : ["Pregame", "win prob"];
  return h(`div.hero-team.hero-team--${side}`, { class: `team-${team.tricode}` },
    h("div.hero-team-top",
      logo(team.tricode, "xl"),
      h("div.hero-team-id",
        h("span.hero-side.cond", `${side === "home" ? "Home" : "Away"} · ${team.record ? record(team.record) : "record —"}`),
        h("span.hero-abbr.cond", team.tricode),
        h("span.hero-name.cond", nickname(team.tricode, team.name)))),
    h("div.hero-l10",
      h("span.hero-l10-label.cond", `Last 10 · ${l10Text(team.l10)}`),
      l10Strip(team.l10, true)),
    h("div.hero-num-row",
      h("span.hero-big.cond", big),
      h("span.hero-small.cond", h("span", small[0]), h("span", small[1]))));
}

function heroSoFar(vms) {
  const bets = vms.filter((vm) => vm.bet && vm.status !== "postponed");
  const settled = bets.filter(isSettledBet);
  const open = bets.filter((vm) => !isSettledBet(vm));
  const settledPl = settled.reduce((s, vm) => s + vm.pl, 0);
  const [w, l] = [settled.filter((vm) => vm.result === "hit").length, settled.filter((vm) => vm.result === "miss").length];
  const stillOpen = open.reduce((s, vm) => s + vm.bet.amount, 0);
  const openAhead = open.filter((vm) => vm.margin !== null && vm.margin > 0).length;
  const ifNow = settledPl + open.reduce((s, vm) => {
    if (vm.margin === null || vm.margin === 0) return s;
    return s + (vm.margin > 0 ? (vm.pl ?? payoutFor(vm)) : -vm.bet.amount);
  }, 0);
  const rows = open.sort(tipOrder).map((vm) => {
    const g = vm.g;
    return h("a.open-bet", { attrs: { href: `#game/${vm.id}`, "aria-label": `Open ${g.away.tricode} at ${g.home.tricode}` } },
      logo(g.away.tricode, "sm"), logo(g.home.tricode, "sm"),
      h("span.matchup.cond", `${g.away.tricode} @ ${g.home.tricode} `, h("span.muted", `· pick ${g.pick}`)),
      statusChip(vm),
      h("span.margin.cond", { class: vm.margin > 0 ? "pos" : vm.margin < 0 ? "neg" : "" }, capitalize(trackText(vm)) || "—"),
      h("span.stake.cond", money(vm.bet.amount)));
  });
  return h("div.sofar",
    h("div.sofar-tiles",
      bigTile("Settled", signedMoney(settledPl), signClass(settledPl), `Bets ${w}–${l}`),
      bigTile("Still open", money(stillOpen), "accent", `${open.length} bet${open.length === 1 ? "" : "s"} in play`),
      bigTile("Open picks ahead", `${openAhead} of ${open.length}`, ""),
      bigTile("If it ended now", signedMoney(ifNow), signClass(ifNow), "Settled plus open bets at the current score")),
    h("div.open-bets", h("span.big-tile-label.cond", "Open bets"), rows.length ? rows : h("p.note-line", "Every bet has settled.")));
}

function payoutFor(vm) {
  const mult = vm.g.odds > 0 ? vm.g.odds / 100 : 100 / Math.abs(vm.g.odds);
  return Math.round(vm.bet.amount * mult * 100) / 100;
}

function capitalize(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function bigTile(label, value, cls, sub) {
  return h("div.big-tile", h("span.big-tile-label.cond", label), h("span.big-tile-value.cond", { class: cls }, value),
    sub ? h("span.big-tile-sub", sub) : null);
}

function heroNoBets(vms) {
  const priced = vms.filter((vm) => isNum(vm.g.edge)).sort((a, b) => b.g.edge - a.g.edge);
  const closest = priced[0];
  const box = h("div.nobets",
    h("div", h("span.nobets-title.cond", "No bets tonight"),
      h("p.lede", `The model didn't find a price better than its own odds on any of the ${vms.length} games. Its picks are still below.`)));
  if (closest) {
    const g = closest.g;
    const pickProb = g.pick === g.home.tricode ? g.home.win_prob : g.away.win_prob;
    box.append(h("a.closest", { attrs: { href: `#game/${closest.id}`, "aria-label": `Closest to a bet: ${g.pick} ${odds(g.odds)}` } },
      h("span.big-tile-label.cond", "Closest to a bet"),
      h("span.closest-row", logo(g.pick, "md"), h("span.pick.cond", `${g.pick} ${odds(g.odds)}`), h("span.book-name.cond", g.bookmaker || "")),
      h("span.closest-edge.cond", { class: signClass(g.edge) }, `Edge ${edgeText(g.edge)} `,
        h("span.muted", `· model ${pct(pickProb, 1)}, price ${pct(g.implied_prob, 1)}`))));
  }
  return box;
}

// ----------------------------------------------------------------------------- recap
function recapBlock(slate, vms, { unofficial = false } = {}) {
  const settled = vms.filter(isSettledBet);
  const picks = vms.filter((vm) => vm.result === "hit" || vm.result === "miss");
  let net;
  let staked;
  let pickRec;
  let betRec;
  let before;
  let after;
  if (unofficial) {
    net = settled.reduce((s, vm) => s + vm.pl, 0);
    staked = settled.reduce((s, vm) => s + vm.bet.amount, 0);
    pickRec = [picks.filter((vm) => vm.result === "hit").length, picks.filter((vm) => vm.result === "miss").length];
    betRec = [settled.filter((vm) => vm.result === "hit").length, settled.filter((vm) => vm.result === "miss").length];
    const withBankroll = vms.find((vm) => vm.bet && isNum(vm.bet.bankroll_at_bet));
    before = withBankroll ? withBankroll.bet.bankroll_at_bet : null;
    after = isNum(before) ? Math.round((before + net) * 100) / 100 : null;
  } else {
    const r = slate.recap;
    net = r.net_pl;
    staked = r.staked;
    pickRec = recordParts(r.picks);
    betRec = recordParts(r.bets);
    before = r.bankroll_before;
    after = r.bankroll_after;
  }
  const roi = staked > 0 ? net / staked : null;
  const byPl = settled.slice().sort((a, b) => a.pl - b.pl);
  const best = unofficial ? byPl[byPl.length - 1] : vms.find((vm) => slate.recap.best_bet && vm.id === slate.recap.best_bet.game_id);
  const worst = unofficial ? byPl[0] : vms.find((vm) => slate.recap.worst_bet && vm.id === slate.recap.worst_bet.game_id);
  const netCell = h("div.recap-cell",
    h("div.recap-top", h("span.recap-label.cond", "Net P/L"),
      unofficial ? h("span.tag.cond", "Unofficial until the 6 AM run") : null),
    h("span.recap-net.cond", { class: signClass(net) }, signedMoney(net)),
    isNum(before) && isNum(after)
      ? h("span.recap-bankroll.cond", "Bankroll ", h("span.v", `${money(before)} → ${money(after)}`))
      : null);
  const list = h("div.recap-cell.recap-cell--list",
    kv("Picks", `${pickRec[0]}–${pickRec[1]}`),
    kv("Bets", `${betRec[0]}–${betRec[1]}`),
    kv("Staked", money(staked), "accent"),
    kv("ROI", roi === null ? "—" : signedPct(roi, 1), signClass(roi)));
  const bw = h("div.recap-cell.recap-cell--bets",
    bestWorst("Best bet", best), bestWorst("Worst bet", worst && worst !== best ? worst : null));
  return h("div.recap", { class: net > 0 ? "recap--up" : net < 0 ? "recap--down" : "" }, netCell, list, bw);
}

function kv(label, value, cls = "") {
  return h("div.kv", h("span.kv-label.cond", label), h("span.kv-value.cond", { class: cls }, value));
}

function bestWorst(label, vm) {
  const box = h("div.bestworst", h("span.bestworst-label.cond", label));
  if (!vm) {
    box.append(h("span.note-line", "—"));
    return box;
  }
  const g = vm.g;
  box.append(h("a.bestworst-row", { attrs: { href: `#game/${vm.id}`, "aria-label": `${label}: ${g.pick} ${odds(g.odds)}, open game` } },
    logo(g.pick, "sm"),
    h("span.pick.cond", `${g.pick} ${odds(g.odds)}`),
    g.bookmaker ? h("span.book.cond", g.bookmaker) : null,
    resultTag(vm.result, vm.pl)));
  return box;
}

// ----------------------------------------------------------------------------- all games
function allGames(ctx, vms, hero) {
  const heroId = hero.mode === "next" ? hero.vm.id : null;
  const counts = {
    all: vms.length,
    bets: vms.filter((vm) => vm.bet).length,
    live: vms.filter((vm) => vm.status === "live").length,
    upcoming: vms.filter((vm) => vm.status === "scheduled").length,
    final: vms.filter((vm) => vm.status === "final").length,
  };
  const match = {
    all: () => true,
    bets: (vm) => Boolean(vm.bet),
    live: (vm) => vm.status === "live",
    upcoming: (vm) => vm.status === "scheduled",
    final: (vm) => vm.status === "final",
  };
  let list = vms.filter(match[prefs.filter]);
  if (prefs.filter === "all" && heroId) list = list.filter((vm) => vm.id !== heroId);
  list = sortVms(list);

  const redraw = () => draw(ctx);
  const filterSeg = h("div.seg.cond", { attrs: { role: "group", "aria-label": "Filter games" } },
    FILTERS.map(([key, label]) => h("button", {
      attrs: { type: "button", "aria-pressed": prefs.filter === key ? "true" : "false" },
      dataset: { focusKey: `filter-${key}` },
      on: { click: () => { prefs.filter = key; redraw(); } },
    }, `${label} `, h("span.count", String(counts[key])))));
  const sortSeg = h("div.sort-group", h("span.sort-label.cond", "Sort"),
    h("div.seg.seg--sm.cond", { attrs: { role: "group", "aria-label": "Sort games" } },
      SORTS.map(([key, label]) => h("button", {
        attrs: { type: "button", "aria-pressed": prefs.sort === key ? "true" : "false" },
        dataset: { focusKey: `sort-${key}` },
        on: { click: () => { prefs.sort = key; redraw(); } },
      }, label))));

  const section = h("section.section", { attrs: { "aria-labelledby": "all-games-title" } },
    h("div.toolbar", h("h2.section-title.cond", { attrs: { id: "all-games-title" } }, "All games"),
      h("div.toolbar-controls", filterSeg, sortSeg)));
  if (!list.length) {
    section.append(emptyFilter(vms, () => { prefs.filter = "all"; redraw(); }));
    return section;
  }
  const stale = Boolean(ctx.liveStatus && ctx.liveStatus.kind === "stale");
  const asOf = stale && ctx.liveStatus.at ? timeET(ctx.liveStatus.at.toISOString()) : null;
  const flashKinds = ctx.flashKinds || new Map();
  section.append(h("div.cards", list.map((vm) => gameCard(vm, { stale, asOf, flash: flashKinds.get(vm.id) }))));
  return section;
}

function sortVms(list) {
  const copy = list.slice();
  if (prefs.sort === "edge") return copy.sort((a, b) => (b.g.edge ?? -9) - (a.g.edge ?? -9) || tipOrder(a, b));
  if (prefs.sort === "bet") return copy.sort((a, b) => (b.bet ? b.bet.amount : 0) - (a.bet ? a.bet.amount : 0) || tipOrder(a, b));
  return copy.sort(tipOrder); // tip-off order; cards never reorder when their state changes
}

function emptyFilter(vms, showAll) {
  const next = vms.filter((vm) => vm.status === "scheduled" && vm.tip).sort(tipOrder)[0];
  const messages = {
    bets: "No bets tonight", live: "No live games right now", upcoming: "No games left to tip off", final: "No finals yet",
  };
  const extra = prefs.filter === "live" && next ? ` · next tip-off ${timeET(next.g.tip_time_utc)}` : "";
  return h("div.empty-filter",
    h("span.msg.cond", messages[prefs.filter] || "No games", extra ? h("span.muted", extra) : null),
    h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: showAll } }, "Show all games"));
}

// ----------------------------------------------------------------------------- last night
function lastNightSection(ctx) {
  const s = ctx.lastNight;
  if (!s || !s.games.length) return null;
  const vms = s.games.map((g) => merge(g, { isPast: true })).sort(tipOrder);
  const yesterday = addDays(ctx.slate.date, -1) === s.date;
  const settled = vms.filter(isSettledBet);
  const picks = vms.filter((vm) => vm.result === "hit" || vm.result === "miss");
  const pl = settled.reduce((sum, vm) => sum + vm.pl, 0);
  const pending = vms.filter((vm) => vm.status === "pending").length;
  return h("section.section", { attrs: { "aria-labelledby": "last-night-title" } },
    h("div.section-head",
      h("div.section-title-group",
        h("h2.section-title.cond", { attrs: { id: "last-night-title" } }, `${yesterday ? "Last night" : "Last slate"} · ${dayLong(s.date)}`),
        h("a.link-btn.cond", { attrs: { href: `#night/${s.date}` } }, "All past nights ›")),
      h("span.section-summary.cond",
        "Picks ", h("span.v", `${picks.filter((vm) => vm.result === "hit").length}–${picks.filter((vm) => vm.result === "miss").length}`),
        " · Bets ", h("span.v", `${settled.filter((vm) => vm.result === "hit").length}–${settled.filter((vm) => vm.result === "miss").length}`),
        " · ", h("span", { class: signClass(pl) }, signedMoney(pl)),
        pending ? ` · ${pending} pending` : "")),
    h("div.ln-grid.ln-head.cond", h("span", "Final"), h("span", "Pick"), h("span", "Odds"), h("span", "Result"),
      h("span.r", "Bet"), h("span.r", "P/L")),
    h("div.rows", vms.map(lastNightRow)));
}

function lastNightRow(vm) {
  const g = vm.g;
  const final = vm.status === "final";
  const awayTrail = final && isNum(vm.awayScore) && isNum(vm.homeScore) && vm.awayScore < vm.homeScore;
  const homeTrail = final && isNum(vm.awayScore) && isNum(vm.homeScore) && vm.homeScore < vm.awayScore;
  const pickProb = g.pick === g.home.tricode ? g.home.win_prob : g.away.win_prob;
  return h("a.ln-row.ln-grid", { attrs: { href: `#game/${vm.id}`, "aria-label": `Open ${g.away.tricode} at ${g.home.tricode}` } },
    h("span.ln-score",
      logo(g.away.tricode, "sm"),
      h("span.abbr.cond", g.away.tricode),
      h("span.pts.cond", { class: awayTrail ? "trailing" : "" }, isNum(vm.awayScore) ? String(vm.awayScore) : "—"),
      h("span.at.cond", "@"),
      h("span.pts.r.cond", { class: homeTrail ? "trailing" : "" }, isNum(vm.homeScore) ? String(vm.homeScore) : "—"),
      h("span.abbr.r.cond", g.home.tricode),
      logo(g.home.tricode, "sm")),
    h("span.ln-pick.cond", `${g.pick || "—"} `, h("span.muted", pct(pickProb))),
    h("span.ln-odds.cond", `${odds(g.odds)} `, h("span.muted", g.bookmaker || "")),
    h("span.ln-result", vm.result === "hit" || vm.result === "miss"
      ? h(`span.result-tag.result-tag--${vm.result}.result-tag--md.cond`, vm.result === "hit" ? "Hit" : "Miss")
      : resultTag(vm.result, null, "md")),
    h("span.ln-bet.cond", { class: vm.bet ? "" : "muted" }, vm.bet ? money(vm.bet.amount) : "No bet"),
    h("span.ln-pl.cond", { class: signClass(vm.pl) }, vm.bet && isNum(vm.pl) ? signedMoney(vm.pl) : "—"));
}

// ----------------------------------------------------------------------------- page states
function drawPrePicks(ctx, vms) {
  const { slate } = ctx;
  const failed = slate.phase === "prediction_failed";
  const status = pipelineStatus();
  const parts = [];
  if (failed) {
    const controls = status && status.controls_allowed;
    const run = status && status.latest && status.latest.predict;
    const at = run ? timeET(run.started_at) : null;
    parts.push(h("div.banner.banner--error", { attrs: { role: "alert" } },
      h("span.banner-main", icon("warn", 22, 2.2),
        h("span.banner-title.cond", `Tonight's picks are missing · the ${at ? `${at} ` : ""}prediction run failed`)),
      controls ? h("span.banner-actions", h("span.note", "Local view only:"),
        h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: runNow } }, "Retry run")) : null));
  }
  parts.push(h("header.page-head",
    h("div.page-head-text", h("h1.display.cond", "Tonight's slate"),
      h("div.subline.cond", `${dayLong(slate.date)} · ${vms.length} games · ${failed ? "no picks" : "picks not posted yet"}`))));
  parts.push(h("div", { attrs: { id: "banner-slot" } }));
  if (!failed) {
    const tips = vms.map((vm) => vm.tip).filter(Boolean).sort((a, b) => a - b);
    const runAt = tips.length ? timeET(new Date(tips[0].getTime() - 60 * 60 * 1000).toISOString()) : null;
    const morning = status && status.latest && status.latest.morning;
    const settledAt = morning && morning.state === "ok" ? timeET(morning.finished_at || morning.started_at) : null;
    parts.push(h("div.state-box",
      h("div.page-head-text",
        h("span.title.cond", "Picks post an hour before the first tip"),
        h("p", settledAt
          ? `Last night was settled and the model retrained at ${settledAt}. Win probabilities, odds and bets appear when the prediction run finishes.`
          : "Win probabilities, odds and bets appear when the prediction run finishes.")),
      h("span.aside.cond", runAt ? `Prediction run · ${runAt}` : "Prediction run · an hour before tip")));
  }
  if (vms.length) {
    parts.push(h("div.schedule", vms.slice().sort(tipOrder).map((vm) => {
      const g = vm.g;
      return h("div.schedule-cell",
        logo(g.away.tricode, "row"), h("span.m.cond", `${g.away.tricode} @ ${g.home.tricode}`), logo(g.home.tricode, "row"),
        h("span.t.cond", vm.status === "live" ? statusChipScore(vm) : statusChip(vm)));
    })));
  }
  return parts;
}

function statusChipScore(vm) {
  const chip = statusChip(vm);
  if (vm.hasScores) chip.append(` · ${vm.awayScore}–${vm.homeScore}`);
  return chip;
}

async function drawNoGames(ctx) {
  const { slate, view } = ctx;
  let perf = null;
  try {
    perf = await api.performance();
  } catch {
    perf = null;
  }
  const k = perf && perf.kpis;
  const lastSeasonLabel = perf && perf.season !== "all" ? "Season picks" : "Picks";
  const tiles = h("div.tiles2",
    bigTile(slate.offseason ? "Last season picks" : lastSeasonLabel, k ? record(k.picks) : "—", ""),
    bigTile("Bet ROI", k && isNum(k.roi) ? signedPct(k.roi, 1) : "—", k ? signClass(k.roi) : ""),
    bigTile("Bankroll", k && isNum(k.bankroll) ? money(k.bankroll) : "—", "accent"),
    bigTile("Next tip-off", "TBD", "", "The schedule isn't loaded yet"));
  const links = h("div.offseason-links",
    h("a.btn.btn--accent.btn--big.cond", { attrs: { href: "#performance" } }, "Season performance"));
  if (slate.last_slate_date) {
    links.append(h("a.btn.btn--outline.btn--big.cond", { attrs: { href: `#night/${slate.last_slate_date}` } },
      `Last slate · ${dayShort(slate.last_slate_date)}`));
  }
  mount(view, h("section.offseason", { attrs: { "aria-labelledby": "offseason-title" } },
    h("div.offseason-text",
      h("span.offseason-kicker.cond", "No games tonight"),
      h("h1.offseason-title.cond", { attrs: { id: "offseason-title" } }, slate.offseason ? "Offseason" : "Break"),
      h("p.lede", slate.offseason
        ? "The next slate shows up here once the schedule has games. Until then, the season's results are one click away."
        : "There are no games on the schedule tonight. The next slate shows up here as soon as it has games."),
      links),
    tiles));
  if (k && perf && perf.migration_pending) {
    view.append(h("p.note-line", "Bankroll figures are recomputed from settled results until the bankroll history is published."));
  }
}

// ============================================================================= past night
async function renderPastNight(main, date, tonight) {
  const [slate, tonightSlate] = await Promise.all([api.slate(date), api.slate().catch(() => null)]);
  const view = h("div.view");
  mount(main, view);
  const railEnd = addDays(tonight, -1);
  let days = await api.days(railEnd, 7).catch(() => null);
  if (days && days.days.length && !days.days.some((d) => d.date === date) && date < railEnd) {
    days = await api.days(date, 7).catch(() => days);
  }
  const ctx = { view, date, tonight, tonightSlate, days, slate };
  drawPast(ctx);
  return () => {};
}

function drawPast(ctx) {
  const { slate, view, date } = ctx;
  const vms = slate.games.map((g) => merge(g, { isPast: true })).sort(tipOrder);
  const pending = vms.filter((vm) => vm.status === "pending").length;
  const finals = vms.filter((vm) => vm.status === "final").length;
  let summary;
  if (!vms.length) summary = "No games";
  else if (pending === vms.length) summary = `${vms.length} games · results pending`;
  else if (pending) summary = `${vms.length} games · ${finals} final · ${pending} pending`;
  else summary = `${vms.length} games · all final`;

  const parts = [rail(ctx)];
  parts.push(h("header.page-head",
    h("div.page-head-text", h("h1.display.cond", dayLong(date)), h("div.subline.cond", summary)),
    h("a.btn.btn--accent.cond", { attrs: { href: "#games" } }, "Back to tonight")));
  if (!vms.length) {
    parts.push(h("div.state-box", h("div.page-head-text", h("span.title.cond", "No games this night"),
      h("p", "The model made no picks for this date."))));
  } else {
    const settledAny = vms.some((vm) => vm.result === "hit" || vm.result === "miss");
    parts.push(h("section.hero-wrap", { attrs: { "aria-labelledby": "recap-title" } },
      h("h2.section-title.cond", { attrs: { id: "recap-title" } }, "Night recap"),
      settledAny && slate.recap ? recapBlock(slate, vms) : h("div.pending-hero",
        h("span.title.cond", "Results not settled"),
        h("p.lede", "These games were never settled by the morning run, so this night has no results yet. The picks and bets are below."))));
    parts.push(h("section.section", { attrs: { "aria-labelledby": "night-games-title" } },
      h("h2.section-title.cond", { attrs: { id: "night-games-title" } }, "All games"),
      h("div.cards", vms.map((vm) => gameCard(vm)))));
  }
  mount(view, parts);
}

function rail(ctx) {
  const { days, date, tonight, tonightSlate } = ctx;
  const list = days ? days.days.filter((d) => d.date < tonight).slice(0, 7).reverse() : [];
  const nav = h("nav.rail.cond", { attrs: { "aria-label": "Past nights" } });
  const earliest = list.length ? list[0].date : null;
  nav.append(h("button.btn.rail-arrow", {
    attrs: { type: "button", "aria-label": "Earlier days", disabled: !(days && days.has_earlier) || !earliest },
    on: { click: async () => {
      const older = await api.days(addDays(earliest, -1), 7).catch(() => null);
      if (older && older.days.length) {
        ctx.days = older;
        drawPast(ctx);
        const first = ctx.view.querySelector(".rail-arrow");
        if (first) first.focus();
      }
    } },
  }, icon("chevronLeft", 18, 2.5)));
  for (const d of list) {
    const [pw, pl] = recordParts(d.picks);
    const sub = d.pending && pw + pl === 0 ? `${d.games} games · pending` : `Picks ${pw}–${pl}`;
    nav.append(h("a.rail-day", {
      attrs: { href: `#night/${d.date}`, "aria-current": d.date === date ? "date" : null,
        "aria-label": `${dayLong(d.date)}: ${sub}, ${signedMoney(d.net_pl)}` },
    },
    h("span.d", `${weekday(d.date)} `, h("span.muted", dayShort(d.date))),
    h("span.s", `${sub} `, h("span", { class: signClass(d.net_pl) }, signedMoney(d.net_pl)))));
  }
  const tg = tonightSlate && tonightSlate.games ? tonightSlate.games.length : 0;
  nav.append(h("a.rail-day.rail-day--tonight", { attrs: { href: "#games", "aria-label": "Tonight" } },
    h("span.d", "Tonight ", h("span.muted", dayShort(tonightSlate ? tonightSlate.date : tonight))),
    h("span.s", tg ? `${tg} games` : "No games")));
  nav.append(datePicker(ctx));
  return nav;
}

function datePicker(ctx) {
  const wrap = h("div.rail-picker");
  const button = h("button.btn.rail-arrow", { attrs: { type: "button", "aria-label": "Pick a date", "aria-expanded": "false" } },
    icon("calendar", 18, 2.2));
  button.addEventListener("click", () => {
    const openPop = wrap.querySelector(".date-pop");
    if (openPop) {
      openPop.remove();
      button.setAttribute("aria-expanded", "false");
      return;
    }
    const input = h("input", { attrs: { type: "date", "aria-label": "Night to show", max: addDays(ctx.tonight, -1), value: ctx.date } });
    const go = h("button.btn.btn--accent.cond", { attrs: { type: "button" } }, "Go");
    const submit = () => {
      if (/^\d{4}-\d{2}-\d{2}$/.test(input.value)) window.location.hash = `#night/${input.value}`;
    };
    go.addEventListener("click", submit);
    input.addEventListener("change", submit);
    wrap.append(h("div.date-pop", input, go));
    button.setAttribute("aria-expanded", "true");
    input.focus();
  });
  wrap.append(button);
  return wrap;
}
