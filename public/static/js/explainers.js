// Info popovers next to Pregame win prob, Odds taken, Edge and Bet placed (Games-Controls
// board): each works this game's numbers through. One open at a time; Esc, a second click
// or a click outside closes it and focus returns to the info button.
import { h, icon } from "./dom.js";
import { impliedProb, isNum, modelName, money, odds, pct, signedPct } from "./format.js";
import { escapeStack } from "./keys.js";

let open = null; // { button, pop, close }
let seq = 0;

document.addEventListener("click", (e) => {
  if (open && !open.pop.contains(e.target) && !open.button.contains(e.target)) close();
});

function close({ restoreFocus = false } = {}) {
  if (!open) return;
  const { button, pop, release } = open;
  open = null;
  button.setAttribute("aria-expanded", "false");
  pop.remove();
  release();
  if (restoreFocus) button.focus();
}

export function closeExplainer() {
  close();
}

export function infoButton(kind, game, { alignRight = false } = {}) {
  const id = `explainer-${++seq}`;
  const titles = { prob: "pregame win probability", implied: "odds taken", edge: "edge", bet: "bet placed" };
  const button = h("button.info-btn", {
    attrs: { type: "button", "aria-label": `What is ${titles[kind]}?`, "aria-expanded": "false", "aria-controls": id },
  }, h("span.ring", icon("info", 16, 2.2)));
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    if (open && open.button === button) {
      close();
      return;
    }
    close();
    const pop = explainer(kind, game, id);
    if (alignRight) pop.classList.add("align-right");
    const host = button.closest(".tile, .prob-block, .label-with-info") || button.parentElement;
    host.appendChild(pop);
    button.setAttribute("aria-expanded", "true");
    const release = escapeStack.push(() => close({ restoreFocus: true }));
    open = { button, pop, release };
  });
  return button;
}

function row(k, v, cls = "") {
  return h("div.explainer-row", h("span.k", k), h("span.v.cond", { class: cls }, v));
}

function explainer(kind, game, id) {
  const pick = game.pick;
  const pickTeam = pick === game.home.tricode ? game.home : pick === game.away.tricode ? game.away : null;
  const pickProb = pickTeam ? pickTeam.win_prob : null;
  const implied = isNum(game.implied_prob) ? game.implied_prob : impliedProb(game.odds);
  const parts = [];
  if (kind === "prob") {
    parts.push(h("span.explainer-title.cond", "Pregame win probability"),
      h("p", "The model's chance that each team wins, set before tip-off. It never changes during the game."),
      h("div",
        row(game.away.tricode, pct(game.away.win_prob, 1), pick === game.away.tricode ? "accent" : ""),
        row(game.home.tricode, pct(game.home.win_prob, 1), pick === game.home.tricode ? "accent" : ""),
        game.model_name ? row("Model", modelName(game.model_name)) : null));
  } else if (kind === "implied") {
    const where = game.bookmaker ? ` The best ${pick} price across the five books was ${odds(game.odds)} at ${game.bookmaker}.` : "";
    const formula = !isNum(game.odds) ? "No price"
      : game.odds < 0 ? `${odds(game.odds)} → ${Math.abs(game.odds)} ÷ (${Math.abs(game.odds)} + 100)`
        : `${odds(game.odds)} → 100 ÷ (${game.odds} + 100)`;
    parts.push(h("span.explainer-title.cond", "Implied probability"),
      h("p", `What the price says the chance is.${where}`),
      h("div", row(formula, pct(implied, 1))));
  } else if (kind === "edge") {
    parts.push(h("span.explainer-title.cond", "Edge"),
      h("p", "How much more likely the model thinks the pick is than the price does. A bet is placed only when edge is above zero."),
      h("div",
        row("Model win probability", pct(pickProb, 1)),
        row(`Implied by ${odds(game.odds)}`, isNum(implied) ? `− ${pct(implied, 1)}` : "—"),
        row("Edge", isNum(game.edge) ? signedPct(game.edge, 1) : "—", isNum(game.edge) ? (game.edge > 0 ? "pos" : "neg") : "")));
  } else {
    const bet = game.bet;
    const rows = [];
    if (bet && isNum(bet.kelly_full)) {
      rows.push(row("Full Kelly", `${pct(bet.kelly_full, 1)} of bankroll`));
      if (isNum(bet.kelly_fraction)) rows.push(row("Quarter-Kelly", pct(bet.kelly_full * bet.kelly_fraction, 1)));
    }
    if (bet && isNum(bet.bankroll_at_bet)) {
      rows.push(row("Bankroll at bet time", money(bet.bankroll_at_bet)));
      rows.push(row("Cap, 5% of bankroll", money(Math.floor(bet.bankroll_at_bet * 5) / 100)));
    }
    rows.push(row("Bet placed", bet ? money(bet.amount) : "No bet", "accent"));
    parts.push(h("span.explainer-title.cond", "Bet size"),
      h("p", bet
        ? "Quarter-Kelly: a quarter of the stake the Kelly formula calls for, never more than 5% of the bankroll."
        : "No bet: the price didn't leave an edge above zero, so the model's pick is tracked without a stake."),
      h("div", rows));
    if (bet && !isNum(bet.kelly_full)) {
      parts.push(h("p", "The Kelly details for this bet weren't recorded; they're stored from the 2026–27 season."));
    }
  }
  const titles = { prob: "Pregame win probability", implied: "Implied probability", edge: "Edge", bet: "Bet size" };
  return h("div.explainer", { attrs: { id, role: "dialog", "aria-label": titles[kind] } }, parts);
}
