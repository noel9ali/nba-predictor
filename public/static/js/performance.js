// Performance page (Round 7, option C refined: Perf-Final board): season picker, scorebug,
// the two-chart season timeline, W/L strip, risk line, box score, model strip and the
// prediction log with filters and paging.
import { api } from "./api.js";
import { calibrationChart, seasonTimeline } from "./charts.js";
import { resultTag } from "./components.js";
import { clear, h, mount } from "./dom.js";
import {
  dateTimeET, dayShort, isNum, modelName, money, odds, pct, record, recordParts, seasonLabel, signClass,
  signedMoney, signedPct,
} from "./format.js";
import { logo } from "./teams.js";

const PAGE_SIZE = 25;
const EDGE_OPTIONS = [["", "Any"], ["0", "0%+"], ["0.03", "3%+"], ["0.06", "6%+"], ["0.1", "10%+"]];
const RESULT_OPTIONS = [["any", "Any result"], ["hit", "Hit"], ["miss", "Miss"], ["pending", "Pending"]];
const CONFIDENCE_LABELS = { high: "High · 65%+", medium: "Medium · 58–65%", low: "Low · under 58%" };
const EDGE_LABELS = { "<0": "Below 0%", "0-3": "0–3%", "3-6": "3–6%", "6-10": "6–10%", "10+": "10%+" };

let chosenSeason = null; // remembered across visits within the session

export async function renderPerformance(main) {
  const view = h("div.view", h("p.loading", "Loading performance…"));
  mount(main, view);
  const perf = await api.performance(chosenSeason || undefined);
  const season = perf.season;
  const model = await api.model(season === "all" ? undefined : season).catch(() => null);
  const ctx = { view, perf, model, season, disposers: [], log: { team: "", bets_only: "false", result: "any", book: "", min_edge: "", page: 1 } };
  draw(ctx);
  return () => ctx.disposers.forEach((d) => d());
}

function draw(ctx) {
  const { perf, view } = ctx;
  const k = perf.kpis;
  const settledNights = perf.series.filter((p, i) => i > 0 && !(p.picks === "0-0" && p.pending > 0));
  const hasResults = recordParts(k.picks).reduce((a, b) => a + b, 0) > 0;
  const parts = [header(ctx, settledNights)];
  if (!hasResults) {
    parts.push(emptySeason(ctx));
  } else {
    if (perf.migration_pending) {
      parts.push(h("p.note-line", "Bankroll is recomputed from settled results (a $1,000 start plus each night's P/L) until the bankroll history is published."));
    }
    parts.push(scorebug(perf, settledNights), timeline(ctx, settledNights), boxScore(perf), modelStrip(ctx));
  }
  parts.push(logSection(ctx));
  mount(view, parts);
  loadLog(ctx);
}

// ------------------------------------------------------------------ header
function header(ctx, nights) {
  const { perf } = ctx;
  const range = nights.length ? `${dayShort(nights[0].date)} – ${dayShort(nights[nights.length - 1].date)}` : "no nights settled yet";
  const start = money(perf.kpis.start_bankroll).replace(".00", "");
  const seasons = [...perf.seasons, "all"];
  return h("header.page-head",
    h("div.page-head-text",
      h("h1.display.cond", "Performance"),
      h("span.season-sub.cond", `${seasonLabel(perf.season)}${perf.season === "all" ? "" : " season"} · ${range} · paper bets from a ${start} start`)),
    h("div.seg.cond", { attrs: { role: "group", "aria-label": "Season" } },
      seasons.map((season) => h("button", {
        attrs: { type: "button", "aria-pressed": season === perf.season ? "true" : "false" },
        on: { click: () => switchSeason(ctx, season) },
      }, seasonLabel(season)))));
}

async function switchSeason(ctx, season) {
  if (season === ctx.perf.season) return;
  chosenSeason = season;
  try {
    ctx.perf = await api.performance(season);
    ctx.model = await api.model(season === "all" ? undefined : season).catch(() => ctx.model);
    ctx.season = ctx.perf.season;
    ctx.log.page = 1;
    ctx.disposers.forEach((d) => d());
    ctx.disposers = [];
    draw(ctx);
    const btn = [...ctx.view.querySelectorAll(".page-head .seg button")].find((b) => b.getAttribute("aria-pressed") === "true");
    if (btn) btn.focus();
  } catch {
    // keep the current view; the error is transient
  }
}

// ------------------------------------------------------------------ scorebug
function scorebug(perf, nights) {
  const k = perf.kpis;
  const [bw, bl] = recordParts(k.bets);
  const [pw, pl] = recordParts(k.picks);
  const since = nights.length ? dayShort(nights[0].date) : "the start";
  const gain = isNum(k.bankroll) ? k.bankroll - k.start_bankroll : null;
  return h("section.scorebug", { attrs: { "aria-label": "Season summary" } },
    h("div.cell.cell--bankroll", h("span.label.cond", "Bankroll"), h("span.value.cond", money(k.bankroll)),
      h("span.sub.cond", isNum(gain) ? `${signedMoney(gain)} since ${since}` : "")),
    h("div.cell", h("span.label.cond", "ROI"), h("span.value.cond", { class: signClass(k.roi) }, isNum(k.roi) ? signedPct(k.roi, 1) : "—"),
      h("span.sub", "P/L ÷ staked")),
    h("div.cell", h("span.label.cond", "Bet record"), h("span.value.cond", record(k.bets)),
      h("span.sub", bw + bl ? `${pct(bw / (bw + bl), 1)} of bets hit` : "No bets settled")),
    h("div.cell", h("span.label.cond", "Pick accuracy"), h("span.value.cond", isNum(k.accuracy) ? pct(k.accuracy, 1) : "—"),
      h("span.sub", `${record(k.picks)} on all ${pw + pl} picks`)));
}

// ------------------------------------------------------------------ timeline
function timeline(ctx, nights) {
  const { perf } = ctx;
  const section = h("section.timeline", { attrs: { "aria-labelledby": "timeline-title" } },
    h("div.section-head",
      h("h2.section-title.cond", { attrs: { id: "timeline-title" } }, "Season timeline"),
      h("span.section-note.cond", "Hover or arrow keys move through nights; click opens that night on Games")));
  if (nights.length) {
    const points = [perf.series[0], ...nights];
    const chart = seasonTimeline(points, {
      start: perf.kpis.start_bankroll,
      drawdown: perf.kpis.max_drawdown,
      onOpen: (date) => { window.location.hash = `#night/${date}`; },
    });
    ctx.disposers.push(chart.dispose);
    section.append(chart.el);
  }
  const recent = perf.recent_bets;
  if (recent.length) {
    section.append(h("div.wl-block",
      h("span.section-note.cond", `Last ${recent.length} bets, oldest to newest`),
      h("div.wl-strip", { attrs: { role: "img", "aria-label": `Last ${recent.length} bets, oldest to newest: ${recent.join(" ")}` } },
        recent.map((r) => h("span", { class: r === "W" ? "" : "l" }, r)))));
  }
  const dd = perf.kpis.max_drawdown;
  section.append(h("div.risk.cond",
    h("span.k", "Risk"),
    h("span.item", "Max drawdown ", h("span.neg", dd.amount > 0 ? signedMoney(-dd.amount) : "$0"),
      dd.peak_date ? h("span.dates", ` ${dayShort(dd.peak_date)} → ${dayShort(dd.trough_date)}`) : null),
    h("span.item", `Longest win streak W${perf.kpis.longest_win_streak}`),
    h("span.item", `Longest losing streak L${perf.kpis.longest_loss_streak}`)));
  return section;
}

// ------------------------------------------------------------------ box score
function boxScore(perf) {
  const section = h("section.section", { attrs: { "aria-labelledby": "box-title" } },
    h("div.section-head", h("h2.section-title.cond", { attrs: { id: "box-title" } }, "Box score"),
      h("span.section-note.cond", "Settled bets only")));
  const table = h("div.table-scroll", { attrs: { role: "table", "aria-label": "Box score" } });
  table.append(h("div.box-grid.box-head.cond", { attrs: { role: "row" } },
    h("span", { attrs: { role: "columnheader" } }, ""),
    ...["Bets", "W–L", "Staked", "P/L", "ROI"].map((c) => h("span.r", { attrs: { role: "columnheader" } }, c))));
  const groups = [
    ["By book", perf.splits.book, (key) => key, "The sportsbook for each bet is recorded from the 2026–27 season."],
    ["By confidence", perf.splits.confidence, (key) => CONFIDENCE_LABELS[key] || key, "No settled bets yet."],
    ["By edge size", perf.splits.edge, (key) => EDGE_LABELS[key] || key, "No settled bets yet."],
  ];
  for (const [title, rows, label, empty] of groups) {
    table.append(h("div.box-group.cond", { attrs: { role: "row" } }, h("span", { attrs: { role: "rowheader" } }, title)));
    if (!rows.length) {
      table.append(h("div.box-empty", { attrs: { role: "row" } }, h("span", { attrs: { role: "cell" } }, empty)));
      continue;
    }
    for (const r of rows) {
      table.append(h("div.box-grid.box-row.cond", { attrs: { role: "row" } },
        h("span.k", { attrs: { role: "rowheader" } }, label(r.key)),
        h("span.r", { attrs: { role: "cell" } }, String(r.bets)),
        h("span.r", { attrs: { role: "cell" } }, `${r.w}–${r.l}`),
        h("span.r", { attrs: { role: "cell" } }, money(r.staked)),
        h("span.r.strong", { class: signClass(r.pl), attrs: { role: "cell" } }, signedMoney(r.pl)),
        h("span.roi-cell", { attrs: { role: "cell" } },
          isNum(r.roi) ? h("span.sq", { class: r.roi < 0 ? "l" : "", attrs: { "aria-hidden": "true" } }) : null,
          isNum(r.roi) ? signedPct(r.roi, 1) : "—")));
    }
  }
  section.append(table);
  return section;
}

// ------------------------------------------------------------------ model strip
function modelStrip(ctx) {
  const m = ctx.model;
  const stat = (label, value, sub, name = false) => h("div.model-stat",
    h("span.label.cond", label), h("span.value.cond", { class: name ? "value--name" : "" }, value), h("span.sub", sub));
  const published = m && m.production_model;
  const test = m && m.test;
  const live = m && m.season_live;
  return h("section.model-strip", { attrs: { "aria-labelledby": "model-title" } },
    h("div.model-left",
      h("div.section-head", h("h2.section-title.cond", { attrs: { id: "model-title" } }, "Model"),
        h("span.section-note.cond", published ? "The model making tonight's picks" : "Model details publish with the next training run")),
      h("div.model-stats",
        stat("Live model", published ? modelName(m.production_model) : "Not published yet",
          m && m.trained_at ? `Trained ${dateTimeET(m.trained_at)}` : "Pending", true),
        stat("Test accuracy", test && isNum(test.accuracy) ? pct(test.accuracy, 1) : "—",
          test && isNum(test.games) ? `${test.games.toLocaleString("en-US")} held-out games` : "Pending"),
        stat("This season", live && isNum(live.accuracy) ? pct(live.accuracy, 1) : "—",
          live ? `${live.picks} picks so far` : ""),
        stat("Brier score", test && isNum(test.brier) ? test.brier.toFixed(3) : "—", "Lower is better"))),
    h("div.calib",
      m && m.calibration && m.calibration.length ? calibrationChart(m.calibration) : h("p.note-line", "Calibration appears once picks settle."),
      h("span.calib-label.cond", "Calibration · actual vs predicted")));
}

// ------------------------------------------------------------------ empty season
function emptySeason(ctx) {
  const prev = ctx.perf.seasons.find((s) => s !== ctx.perf.season && s !== "all");
  return h("div.empty-perf",
    h("div.section", h("span.title.cond", "No settled bets yet this season"),
      h("p.lede", `Results settle each morning at 6 AM. The first night's bets appear here the morning after. Bankroll starts at ${money(ctx.perf.kpis.start_bankroll)}.`)),
    h("div.links",
      prev ? h("button.btn.btn--accent.btn--big.cond", { attrs: { type: "button" }, on: { click: () => switchSeason(ctx, prev) } }, `See last season · ${seasonLabel(prev)}`) : null,
      h("a.btn.btn--outline.btn--big.cond", { attrs: { href: "#games" } }, "Tonight's picks")));
}

// ------------------------------------------------------------------ prediction log
function logSection(ctx) {
  const f = ctx.log;
  const team = h("input", { attrs: { type: "text", id: "log-team", placeholder: "Any team", autocomplete: "off", value: f.team, maxlength: "40" } });
  let debounce = null;
  team.addEventListener("input", () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => {
      f.team = team.value.trim();
      f.page = 1;
      loadLog(ctx);
    }, 300);
  });
  const segment = (label, key, options) => h("div.seg.seg--sm.cond", { attrs: { role: "group", "aria-label": label } },
    options.map(([value, text]) => h("button", {
      attrs: { type: "button", "aria-pressed": f[key] === value ? "true" : "false" },
      on: { click: (e) => {
        f[key] = value;
        f.page = 1;
        for (const b of e.currentTarget.parentElement.children) b.setAttribute("aria-pressed", b === e.currentTarget ? "true" : "false");
        loadLog(ctx);
      } },
    }, text)));
  const book = h("select", { attrs: { id: "log-book" } }, h("option", { attrs: { value: "" } }, "All books"));
  book.addEventListener("change", () => { f.book = book.value; f.page = 1; loadLog(ctx); });
  const edge = h("select", { attrs: { id: "log-edge" } },
    EDGE_OPTIONS.map(([value, text]) => h("option", { attrs: { value, selected: f.min_edge === value } }, text)));
  edge.addEventListener("change", () => { f.min_edge = edge.value; f.page = 1; loadLog(ctx); });
  ctx.bookSelect = book;
  return h("section.section", { attrs: { "aria-labelledby": "log-title" } },
    h("div.section-head", h("h2.section-title.cond", { attrs: { id: "log-title" } }, "Prediction log"),
      h("span.section-note.cond", "Rows open the game detail drawer")),
    h("div.log-filters",
      h("label.field.cond", { attrs: { for: "log-team" } }, "Team", team),
      segment("Picks or bets", "bets_only", [["false", "All picks"], ["true", "Bets only"]]),
      segment("Result", "result", RESULT_OPTIONS),
      h("label.field.cond", { attrs: { for: "log-book" } }, "Book", book),
      h("label.field.cond", { attrs: { for: "log-edge" } }, "Edge", edge)),
    h("div", { attrs: { id: "log-body", "aria-live": "polite", "aria-busy": "false" } }));
}

let logSeq = 0;
async function loadLog(ctx) {
  const body = ctx.view.querySelector("#log-body");
  if (!body) return;
  const seq = ++logSeq;
  const f = ctx.log;
  body.setAttribute("aria-busy", "true");
  let data;
  try {
    data = await api.predictions({
      season: ctx.season, team: f.team, bets_only: f.bets_only, result: f.result, book: f.book,
      min_edge: f.min_edge, page: f.page, page_size: PAGE_SIZE,
    });
  } catch {
    if (seq !== logSeq) return;
    mount(body, h("div.error-box", h("span.title.cond", "The log didn't load"),
      h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: () => loadLog(ctx) } }, "Retry")));
    body.setAttribute("aria-busy", "false");
    return;
  }
  if (seq !== logSeq) return;
  body.setAttribute("aria-busy", "false");
  fillBooks(ctx, data.books);
  if (!data.rows.length) {
    mount(body, h("div.empty-filter",
      h("span.msg.cond", "No picks match ", h("span.muted", filterSummary(f))),
      h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: () => clearFilters(ctx) } }, "Clear filters")));
    return;
  }
  const start = (data.page - 1) * data.page_size + 1;
  const end = start + data.rows.length - 1;
  const table = h("div.table-scroll",
    h("div.log-grid.log-head.cond",
      h("span", "Date"), h("span", "Matchup"), h("span", "Pick · pregame"), h("span", "Odds · book"),
      h("span", "Edge"), h("span", "Bet"), h("span", "Result"), h("span.r", "P/L")),
    h("div.log-rows", data.rows.map(logRow)));
  const pager = h("div.pager",
    h("span.pager-text.cond", `${start}–${end} of ${data.total} picks · newest first`),
    h("div.seg.seg--sm.cond",
      h("button", { attrs: { type: "button", disabled: data.page <= 1 }, on: { click: () => { f.page -= 1; loadLog(ctx); } } }, "‹ Newer"),
      h("button", { attrs: { type: "button", disabled: end >= data.total }, on: { click: () => { f.page += 1; loadLog(ctx); } } }, "Older ›")));
  mount(body, table, pager);
}

function fillBooks(ctx, books) {
  const select = ctx.bookSelect;
  if (!select || select.dataset.filled === String(books.length)) return;
  const current = ctx.log.book;
  clear(select);
  select.append(h("option", { attrs: { value: "" } }, "All books"));
  for (const b of books) select.append(h("option", { attrs: { value: b, selected: b === current } }, b));
  select.disabled = books.length === 0;
  select.title = books.length ? "" : "Sportsbooks are recorded from the 2026–27 season";
  select.dataset.filled = String(books.length);
}

function filterSummary(f) {
  const bits = [];
  if (f.team) bits.push(`Team “${f.team}”`);
  if (f.bets_only === "true") bits.push("Bets only");
  if (f.result !== "any") bits.push(f.result[0].toUpperCase() + f.result.slice(1));
  if (f.book) bits.push(f.book);
  if (f.min_edge) bits.push(`Edge ${EDGE_OPTIONS.find(([v]) => v === f.min_edge)[1]}`);
  return bits.length ? `· ${bits.join(", ")}` : "";
}

function clearFilters(ctx) {
  ctx.log = { team: "", bets_only: "false", result: "any", book: "", min_edge: "", page: 1 };
  const logEl = ctx.view.querySelector("#log-title").closest("section");
  logEl.replaceWith(logSection(ctx));
  loadLog(ctx);
  const team = ctx.view.querySelector("#log-team");
  if (team) team.focus();
}

function logRow(r) {
  const result = r.result === "hit" || r.result === "miss"
    ? h(`span.result-tag.result-tag--${r.result}.result-tag--sm.cond`, r.result === "hit" ? "Hit" : "Miss")
    : resultTag(r.result, null, "sm");
  return h("a.log-row.log-grid", { attrs: { href: `#game/${r.game_id}`, "aria-label": `Open ${r.away} at ${r.home}, ${dayShort(r.date)}` } },
    h("span.date.cond", dayShort(r.date)),
    h("span.mu.cond", logo(r.away, "xs"), `${r.away} @ ${r.home}`, logo(r.home, "xs")),
    h("span.pk.cond", `${r.pick || "—"} `, h("span.muted", pct(r.pick_prob))),
    h("span.od.cond", `${odds(r.odds)} `, h("span.muted", r.bookmaker || "")),
    h("span.ed.cond", { class: signClass(r.edge) }, isNum(r.edge) ? signedPct(r.edge, 1) : "—"),
    h("span.bt.cond", { class: r.bet_amount > 0 ? "" : "muted" }, r.bet_amount > 0 ? money(r.bet_amount) : "No bet"),
    h("span.rs", result),
    h("span.pl.cond", { class: signClass(r.profit_loss) }, r.bet_amount > 0 && isNum(r.profit_loss) ? signedMoney(r.profit_loss) : "—"));
}
