// Game detail drawer, option A "Tale of the tape" (Detail-A board). It has its own link
// (#game/<id>), traps focus while open, closes on Esc, the close button or the backdrop,
// and hands focus back to whatever opened it.
import { ApiError, SAMPLE, api, sampleTonight, todayET } from "./api.js";
import { bookGrid, edgeText, probBar, probLabel, statusChip, tile } from "./components.js";
import { h, icon, mount, prefersReducedMotion } from "./dom.js";
import { closeExplainer, infoButton } from "./explainers.js";
import { dateTimeET, isNum, modelName, money, odds, pct, record, signClass } from "./format.js";
import { escapeStack, releaseFocus, trapFocus } from "./keys.js";
import { merge } from "./model.js";
import { logo } from "./teams.js";

const layer = () => document.getElementById("drawer-layer");
const panel = () => document.getElementById("drawer");
let current = null; // { id, opener, releaseEsc, onClose }
let loadSeq = 0;

export function isDrawerOpen() {
  return Boolean(current);
}

export function openDrawer(id, { onClose }) {
  if (current && current.id === id) return;
  const opener = current ? current.opener : document.activeElement;
  if (current) current.releaseEsc();
  const releaseEsc = escapeStack.push(() => onClose());
  current = { id, opener, releaseEsc, onClose };
  const el = panel();
  layer().hidden = false;
  el.classList.toggle("slide-in", !prefersReducedMotion());
  for (const node of [document.getElementById("page"), document.querySelector(".skip-link")]) {
    if (node) node.inert = true;
  }
  mount(el, drawerHead(null, onClose), h("p.loading", "Loading game…"));
  trapFocus(el);
  focusClose();
  load(id, onClose);
}

export function closeDrawer() {
  if (!current) return;
  const { opener, releaseEsc } = current;
  current = null;
  releaseEsc();
  closeExplainer();
  releaseFocus(panel());
  layer().hidden = true;
  mount(panel());
  for (const node of [document.getElementById("page"), document.querySelector(".skip-link")]) {
    if (node) node.inert = false;
  }
  if (opener && document.contains(opener) && typeof opener.focus === "function") opener.focus({ preventScroll: true });
}

export function initDrawer() {
  document.getElementById("drawer-backdrop").addEventListener("click", () => current && current.onClose());
}

function focusClose() {
  const btn = panel().querySelector(".drawer-close");
  if (btn) btn.focus({ preventScroll: true });
  else panel().focus();
}

async function load(id, onClose) {
  const seq = ++loadSeq;
  let detail;
  try {
    detail = await api.game(id);
  } catch (err) {
    if (seq !== loadSeq || !current) return;
    const missing = err instanceof ApiError && (err.status === 404 || err.status === 400);
    mount(panel(), drawerHead(null, onClose),
      h("div.drawer-section", h("h3.cond", missing ? "Game not found" : "Couldn't load this game"),
        h("p.note-line", missing ? "There's no prediction for this game id." : "Try again in a moment.")));
    focusClose();
    return;
  }
  if (seq !== loadSeq || !current) return;
  mount(panel(), ...drawerBody(detail, onClose));
  panel().setAttribute("aria-label", `Game detail, ${detail.game.away.tricode} at ${detail.game.home.tricode}`);
  focusClose();
}

function drawerHead(vm, onClose) {
  return h("div.drawer-head",
    vm ? statusChip(vm, { large: true }) : h("span"),
    h("button.icon-btn.drawer-close", { attrs: { type: "button", "aria-label": "Close game detail" }, on: { click: onClose } },
      icon("close", 18, 2.4)));
}

function drawerBody(detail, onClose) {
  const game = { ...detail.game, model_name: detail.model_name };
  const tonight = SAMPLE ? sampleTonight() : todayET();
  const vm = merge(game, { isPast: Boolean(game.date && game.date < tonight) });
  const pickSide = vm.pickSide;
  const bet = game.bet;

  const side = (s) => {
    const t = game[s];
    const id = h("div.id",
      h("span.abbr.cond", { class: pickSide === s ? "is-pick" : "" }, t.tricode),
      h("span.side.cond", `${s === "home" ? "Home" : "Away"} · ${t.record ? record(t.record) : "record —"}`));
    return h(`div.matchup-side.matchup-side--${s}`, s === "home" ? [id, logo(t.tricode, "lg")] : [logo(t.tricode, "lg"), id]);
  };

  const impliedCaption = isNum(game.implied_prob) && game.pick
    ? h("div.implied-caption.cond", `Yellow mark = price implied ${pct(game.implied_prob, 1)} for ${game.pick}`)
    : null;

  return [
    drawerHead(vm, onClose),
    h("h2.sr-only", { attrs: { id: "drawer-title" } }, `${game.away.tricode} at ${game.home.tricode}`),
    h("div.matchup-head", side("away"), h("span.matchup-at.cond", "@"), side("home")),
    h("div.drawer-block",
      h("div.prob-caption.cond", h("span.label-with-info", "Pregame win probability", infoButton("prob", game)), h("span", probLabel(game))),
      probBar(game, { mark: true, large: true }),
      impliedCaption),
    h("div.tiles4",
      tile("Pick", game.pick || "—", { small: true }),
      tile(game.bookmaker ? `Odds · ${game.bookmaker}` : "Odds", odds(game.odds), { small: true, info: infoButton("implied", game) }),
      tile("Edge", edgeText(game.edge), { small: true, valueClass: signClass(game.edge), info: infoButton("edge", game) }),
      tile("Bet placed", bet ? money(bet.amount) : "No bet", { small: true, valueClass: bet ? "accent" : "muted",
        info: infoButton("bet", game, { alignRight: true }) })),
    tape(detail),
    h("section.drawer-section", h("h3.cond", "Odds at time of bet"), bookGrid(vm)),
    h("div.drawer-spacer"),
    h("div.drawer-foot.cond",
      h("span", detail.predicted_at
        ? `Predicted ${dateTimeET(detail.predicted_at)}${detail.model_name ? ` · ${modelName(detail.model_name)}` : ""}`
        : detail.model_name ? `Model · ${modelName(detail.model_name)}` : "Prediction time not recorded"),
      h("span", resultLine(detail, vm))),
  ];
}

function resultLine(detail, vm) {
  const game = detail.game;
  if (vm.status === "postponed") return game.bet ? `Postponed · ${money(game.bet.amount)} returned` : "Postponed";
  const r = detail.result;
  if (r && r.correct !== null && r.correct !== undefined) {
    const score = isNum(r.home_score) && isNum(r.away_score) ? ` · ${game.away.tricode} ${r.away_score}, ${game.home.tricode} ${r.home_score}` : "";
    return `Final${score} · pick ${r.correct === 1 ? "hit" : "missed"}`;
  }
  if (vm.status === "final" && vm.result) return `Final · pick ${vm.result === "hit" ? "hit" : "missed"} · unofficial until the 6 AM run`;
  if (vm.status === "pending") return "Result not settled yet";
  return "Result appears at the final buzzer";
}

const TAPE_ROWS = [
  ["elo", "Elo rating", (v) => v.toFixed(0), 1200],
  ["rest_days", "Rest days", (v) => v.toFixed(0), 0],
  ["roll_pts", "Points", (v) => v.toFixed(1), 0],
  ["roll_fg_pct", "FG%", (v) => (v * 100).toFixed(1), 0],
  ["roll_reb", "Rebounds", (v) => v.toFixed(1), 0],
  ["roll_ast", "Assists", (v) => v.toFixed(1), 0],
  ["roll_tov", "Turnovers · lower is better", (v) => v.toFixed(1), 0],
  ["roll_stocks", "Stocks", (v) => v.toFixed(1), 0],
];

function tape(detail) {
  const { tape: t, game } = detail;
  const grid = h("div.tape",
    h("span.team.cond", game.away.tricode),
    h("span.note.cond", "Last 10 games unless noted"),
    h("span.team.r.cond", game.home.tricode));
  let any = false;
  for (const [key, label, fmt, floor] of TAPE_ROWS) {
    const a = t.away[key];
    const hv = t.home[key];
    if (!isNum(a) && !isNum(hv)) continue;
    any = true;
    const better = t.better[key];
    const bar = h("div.tape-bar", { attrs: { "aria-hidden": "true" } });
    if (isNum(a) && isNum(hv)) {
      const av = Math.max(a - floor, 0.0001);
      const hvv = Math.max(hv - floor, 0.0001);
      const share = (av / (av + hvv)) * 100;
      bar.append(h("span", { class: `team-${game.away.tricode}`, style: { width: `${share.toFixed(1)}%` } }),
        h("span", { class: `team-${game.home.tricode}`, style: { width: `${(100 - share).toFixed(1)}%` } }));
    }
    const betterText = better ? `, ${better === "home" ? game.home.tricode : game.away.tricode} better` : "";
    grid.append(
      h("span.val.cond", { class: better === "away" ? "better" : "" }, isNum(a) ? fmt(a) : "—"),
      h("div.tape-stat", h("span.name.cond", label), bar,
        h("span.sr-only", `${label}: ${game.away.tricode} ${isNum(a) ? fmt(a) : "not available"}, ${game.home.tricode} ${isNum(hv) ? fmt(hv) : "not available"}${betterText}`)),
      h("span.val.r.cond", { class: better === "home" ? "better" : "" }, isNum(hv) ? fmt(hv) : "—"));
  }
  return h("section.drawer-section", h("h3.cond", "Tale of the tape"),
    any ? grid : h("p.note-line", "Team stats before this game aren't available."));
}
