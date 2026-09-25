// Same-origin JSON API (04-API-CONTRACT), plus sample mode: ?sample=1 answers every call
// from public/sample/*.json (files shaped exactly like the API responses), so the whole
// design can be reviewed in the offseason. &scene= picks which night to show.
import { dateET } from "./format.js";
import { nickname } from "./teams.js";

const params = new URLSearchParams(window.location.search);
export const SAMPLE = params.get("sample") === "1";

export const SCENES = {
  live: { label: "Tonight, 9:05 PM", now: "2026-11-18T02:05:00Z", slate: "", live: ["live"] },
  nextup: { label: "Before the first tip", now: "2026-11-17T23:59:00Z", slate: "", live: ["pre"] },
  sofar: { label: "Every bet has tipped", now: "2026-11-18T03:40:00Z", slate: "", live: ["sofar"] },
  final: { label: "Every game final", now: "2026-11-18T06:05:00Z", slate: "", live: ["final"] },
  nobets: { label: "No bets tonight", now: "2026-11-17T23:30:00Z", slate: "-nobets", live: ["pre"] },
  before: { label: "Before the prediction run", now: "2026-11-17T19:00:00Z", slate: "-before", live: ["pre"] },
  failed: { label: "Prediction run failed", now: "2026-11-18T00:12:00Z", slate: "-failed", live: ["failed"] },
  offseason: { label: "Offseason", now: "2027-07-20T19:00:00Z", slate: "-offseason", live: [], tonight: "2027-07-20" },
  edges: { label: "Card edge cases", now: "2026-11-18T03:50:00Z", slate: "-edges", live: ["edges"] },
  stale: { label: "Scores delayed", now: "2026-11-18T02:05:00Z", slate: "", live: ["live", "FAIL"] },
  feeddown: { label: "Live feed down", now: "2026-11-18T02:09:30Z", slate: "", live: ["FAIL"], lastGood: "2026-11-18T02:03:00Z" },
  replay: { label: "Tip-off and final buzzer replay", now: "2026-11-17T23:59:00Z", slate: "",
    live: ["replay-0", "replay-1", "replay-2", "replay-3", "replay-4", "replay-5", "replay-6"], pollMs: 6000 },
  early: { label: "Early season (Performance)", now: "2026-11-18T02:05:00Z", slate: "", live: ["live"] },
};
const requestedScene = params.get("scene");
export const SCENE = SAMPLE ? (Object.prototype.hasOwnProperty.call(SCENES, requestedScene) ? requestedScene : "live") : null;
export const SAMPLE_TONIGHT = "2026-11-17";
const LOCAL_PREVIEW = SAMPLE && params.get("view") === "local";

export class ApiError extends Error {
  constructor(status, code) {
    super(`API ${status}${code ? ` ${code}` : ""}`);
    this.status = status;
    this.code = code || null;
  }
}

// ------------------------------------------------------------------ clock
// Real mode: the real time. Sample mode: the scene's moment, ticking forward in real time
// (a replay snapshot can move it).
const loadedAt = Date.now();
let sampleBase = SAMPLE ? Date.parse(SCENES[SCENE].now) : 0;
let sampleSetAt = loadedAt;

export function now() {
  return SAMPLE ? new Date(sampleBase + (Date.now() - sampleSetAt)) : new Date();
}
export function setSampleNow(iso) {
  if (!SAMPLE || !iso) return;
  sampleBase = Date.parse(iso);
  sampleSetAt = Date.now();
}
export function todayET() {
  return dateET(now());
}

// ------------------------------------------------------------------ real fetches
async function getJSON(path, query = {}, headers = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = `/api/${path}${qs.toString() ? `?${qs}` : ""}`;
  const response = await fetch(url, { headers: { Accept: "application/json", ...headers }, credentials: "same-origin" });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) throw new ApiError(response.status, body && typeof body.error === "string" ? body.error : null);
  return body;
}

// ------------------------------------------------------------------ sample files
const sampleCache = new Map();
async function sampleFile(name) {
  if (!/^[a-z0-9-]+$/.test(name)) throw new ApiError(404, "not_found");
  if (!sampleCache.has(name)) {
    sampleCache.set(name, fetch(`/sample/${name}.json`, { headers: { Accept: "application/json" } }).then((r) => {
      if (!r.ok) throw new ApiError(r.status === 404 ? 404 : 503, r.status === 404 ? "not_found" : "sample_unavailable");
      return r.json();
    }));
  }
  try {
    return structuredClone(await sampleCache.get(name));
  } catch (err) {
    sampleCache.delete(name);
    throw err;
  }
}

function sampleEnvelope(body) {
  return { ...body, generated_at: now().toISOString().replace(/\.\d{3}Z$/, "Z") };
}

async function sampleSlate(date) {
  const day = date || sampleTonight();
  if (day === sampleTonight()) return sampleFile(`slate-${SAMPLE_TONIGHT}${SCENES[SCENE].slate}`);
  try {
    return await sampleFile(`slate-${day}`);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) throw err;
    const days = await sampleFile("days");
    const earlier = days.days.map((d) => d.date).filter((d) => d < day).sort();
    return sampleEnvelope({
      migration_pending: false, date: day, season: "2026-27", is_past: day < SAMPLE_TONIGHT,
      phase: "no_games", offseason: false, last_slate_date: earlier.length ? earlier[earlier.length - 1] : null,
      summary: { games: 0, final: 0, live: 0, upcoming: 0, bets_placed: 0, staked: 0, settled_pl: 0 },
      games: [], recap: null,
    });
  }
}

async function sampleDays(end, n) {
  const all = (await sampleFile("days")).days;
  const upTo = end || SAMPLE_TONIGHT;
  const eligible = all.filter((d) => d.date <= upTo);
  const count = Number(n) || 7;
  return sampleEnvelope({ migration_pending: false, days: eligible.slice(0, count), has_earlier: eligible.length > count });
}

function teamMatches(row, query) {
  const q = query.trim().toLowerCase();
  return [row.home, row.away].some((code) =>
    (code || "").toLowerCase() === q || nickname(code).toLowerCase().includes(q));
}

async function samplePredictions(query) {
  const body = await sampleFile(SCENE === "early" ? "predictions-early" : "predictions");
  let rows = body.rows;
  if (query.team) rows = rows.filter((r) => teamMatches(r, query.team));
  if (query.bets_only === "true") rows = rows.filter((r) => r.bet_amount > 0);
  if (query.result && query.result !== "any") rows = rows.filter((r) => r.result === query.result);
  if (query.book) rows = rows.filter((r) => r.bookmaker === query.book);
  if (query.min_edge !== undefined && query.min_edge !== "") {
    const min = Number(query.min_edge);
    rows = rows.filter((r) => typeof r.edge === "number" && r.edge >= min);
  }
  const page = Number(query.page) || 1;
  const size = Number(query.page_size) || 25;
  const start = (page - 1) * size;
  return sampleEnvelope({
    migration_pending: false, season: body.season, total: rows.length, page, page_size: size,
    books: body.books, rows: rows.slice(start, start + size),
  });
}

let liveStep = 0;
let lastGoodLive = null;
async function sampleLive() {
  const steps = SCENES[SCENE].live;
  if (!steps.length) throw new ApiError(404, "not_found");
  const step = steps[Math.min(liveStep, steps.length - 1)];
  liveStep += 1;
  if (step === "FAIL") {
    // The feed is down: the real route would answer 200 + stale:true with the last good data.
    if (!lastGoodLive && SCENES[SCENE].lastGood) {
      lastGoodLive = await sampleFile("live-live");
      lastGoodLive.fetched_at = SCENES[SCENE].lastGood;
    }
    if (!lastGoodLive) throw new ApiError(503, "live_unavailable");
    return { ...structuredClone(lastGoodLive), stale: true };
  }
  const body = await sampleFile(`live-${step}`);
  if (step.startsWith("replay")) setSampleNow(body.fetched_at);
  else body.fetched_at = now().toISOString().replace(/\.\d{3}Z$/, "Z");
  body.generated_at = body.fetched_at;
  lastGoodLive = structuredClone(body);
  return body;
}

// ------------------------------------------------------------------ public API
export const api = {
  slate(date) {
    return SAMPLE ? sampleSlate(date) : getJSON("slate", { date });
  },
  game(id) {
    return SAMPLE ? sampleFile(`game-${id}`) : getJSON(`game/${encodeURIComponent(id)}`);
  },
  days(end, n = 7) {
    return SAMPLE ? sampleDays(end, n) : getJSON("days", { end, n });
  },
  performance(season) {
    if (SAMPLE) {
      return sampleFile(SCENE === "early" ? "performance-early" : "performance").then((body) =>
        season === "all" ? { ...body, season: "all" } : body);
    }
    return getJSON("performance", { season });
  },
  predictions(query) {
    return SAMPLE ? samplePredictions(query) : getJSON("predictions", query);
  },
  model(season) {
    return SAMPLE ? sampleFile("model") : getJSON("model", { season });
  },
  workflowStatus() {
    if (SAMPLE) {
      return sampleFile(SCENE === "failed" ? "workflow-status-failed" : "workflow-status").then((body) =>
        ({ ...body, controls_allowed: LOCAL_PREVIEW }));
    }
    // The custom header lets the local laptop view pass run_controls_allowed(); it's inert
    // anywhere else (the route never allows controls on Vercel).
    return getJSON("workflow-status", {}, { "X-Requested-With": "run-now" });
  },
  liveScores(date) {
    return SAMPLE ? sampleLive() : getJSON("live-scores", { date });
  },
  async runWorkflow() {
    if (SAMPLE) return { started: false, sample: true };
    const response = await fetch("/api/run-workflow", {
      method: "POST",
      headers: { Accept: "application/json", "X-Requested-With": "run-now" },
      credentials: "same-origin",
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) throw new ApiError(response.status, body && body.error);
    return body;
  },
};

// The sample scene's "tonight" (the offseason scene sits in the following July).
export function sampleTonight() {
  return SAMPLE ? SCENES[SCENE].tonight || SAMPLE_TONIGHT : null;
}
