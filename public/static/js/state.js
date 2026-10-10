// Tonight's state engine: loads the slate, polls /api/live-scores every 30 s under fixed rules,
// merges scores into the games, emits change records and computes every number the page shows.
// A port of the prototype's common.js without its simulation. The DOM is touched only inside
// init() and the timers (html[data-feed]); the pure helpers import cleanly under Node.
import { api, ApiError, SAMPLE, SCENE, sampleNowIso, sampleTonight, sampleReplayStep } from './api.js';
import { fmt, dateET } from './format.js';

export const POLL_MS = 30000, WINDOW_MS = 15 * 60000, DOWN_MS = 5 * 60000, TICK_MS = 60000;
const SLATE_BACKOFF = [5000, 15000, 30000];
const BEFORE_REFETCH_MS = 60000, SETTLE_REFETCH_MS = 30 * 60000;

export const FEED_COPY = {
  delayed: asOfIso => 'Scores delayed · as of ' + fmt.time(asOfIso) + ' ET',
  down: 'Live scores are down. Final results post at the 6 AM settle.'
};

export const store = {
  slate: null, games: [], filter: 'all', sort: 'tip', isPast: false, sample: SAMPLE, scene: SCENE, status: 'loading', date: null,
  feed: { status: 'ok', asOf: null, failures: 0, lastFreshAt: Date.now(), source: null }
};
export const stamped = new Set();    // game ids whose stamp has landed (never replayed until reload)
export const revealed = new Set();   // ticket ids that have already slid in (T5)

const listeners = [];
export function on(fn) { listeners.push(fn); return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); }; }
function emit(changes) {
  if (!changes.length) return;
  for (const fn of listeners.slice()) {
    try { fn(changes); } catch (e) { console.warn('listener failed', e); }
  }
}

// ---------- pure helpers ----------
export const tipMs = g => (g.tip_time_utc ? Date.parse(g.tip_time_utc) : Infinity);
export function pickSide(g) {
  if (g.pick == null) return null;
  if (g.pick === g.home.tricode) return 'home';
  if (g.pick === g.away.tricode) return 'away';
  return null;
}
export function leader(g) { return (g.hs == null || g.as == null || g.hs === g.as) ? null : (g.hs > g.as ? 'home' : 'away'); }
export function result(g) {
  if (g.state === 'void' || g.state === 'postponed') return 'void';
  if (g.state !== 'final') return null;
  if (g.result) return g.result;
  const ps = pickSide(g), ld = leader(g);
  return (!ps || !ld) ? null : (ld === ps ? 'hit' : 'miss');
}
const hasBet = g => !!(g.bet && g.odds != null && g.bet.amount != null);
export function pl(g) {
  const b = g.bet; if (!b) return null;
  if (g.state === 'void' || g.state === 'postponed') return 0;
  if (g.state !== 'final') return null;
  if (b.profit_loss != null) return b.profit_loss;
  const r = result(g);
  if (r === 'hit') return g.odds == null ? null : fmt.payout(b.amount, g.odds);
  return r === 'miss' ? -b.amount : r === 'void' ? 0 : null;
}
export function pickMargin(g) {
  const ps = pickSide(g); if (!ps || g.hs == null || g.as == null) return null;
  const m = g.hs - g.as; return ps === 'home' ? m : -m;
}
export function marginLabel(g) {
  const m = pickMargin(g);
  return m == null ? (g.pick || '') : m > 0 ? g.pick + ' up ' + m : m < 0 ? g.pick + ' down ' + (-m) : g.pick + ' tied';
}
export const isStampState = g => g.state === 'final' || g.state === 'postponed' || g.state === 'void';

export function normalize(sg) {
  return Object.assign({}, sg, {
    state: sg.status,
    period: null,
    clock: sg.status === 'final' ? 'Final' : null,
    hs: (sg.home && sg.home.score != null) ? sg.home.score : null,
    as: (sg.away && sg.away.score != null) ? sg.away.score : null,
    official: sg.status === 'void' || (sg.status === 'final' && (sg.result != null || !!(sg.bet && sg.bet.result != null)))
  });
}

// Merge one LIVE_SCORES response into games; returns the change records (none when silent).
export function applyLive(games, resp, silent) {
  const changes = [], by = new Map((resp.games || []).map(l => [l.game_id, l]));
  for (const g of games) {
    const l = by.get(g.game_id); if (!l) continue;
    const before = { state: g.state, hs: g.hs, as: g.as, clock: g.clock, period: g.period };
    let next = l.postponed ? 'postponed' : l.status;
    if (g.state === 'final' || g.state === 'void') next = g.state;
    else if (g.state === 'live' && next === 'scheduled') next = 'live';
    if (!['scheduled', 'live', 'final', 'postponed', 'void'].includes(next)) next = g.state;
    g.state = next;
    if (next === 'live' || next === 'final') {
      if (l.home_score != null) g.hs = l.home_score;
      if (l.away_score != null) g.as = l.away_score;
    }
    g.period = next === 'scheduled' ? null : (l.period ?? g.period);
    g.clock = next === 'final' ? (before.state === 'final' ? (g.clock || 'Final') : (l.clock || 'Final'))
      : next === 'live' ? (l.clock ?? null) : next === 'postponed' ? null : g.clock;
    if (silent) continue;
    let any = false;
    if (before.state === 'scheduled' && g.state === 'live') { changes.push({ type: 'tip', id: g.game_id }); any = true; }
    if (g.hs !== before.hs) { changes.push({ type: 'score', id: g.game_id, side: 'home' }); any = true; }
    if (g.as !== before.as) { changes.push({ type: 'score', id: g.game_id, side: 'away' }); any = true; }
    if (before.state !== 'final' && g.state === 'final') { changes.push({ type: 'final', id: g.game_id, result: result(g), pl: pl(g) }); any = true; }
    if (!any && (g.clock !== before.clock || g.period !== before.period || g.state !== before.state)) changes.push({ type: 'clock', id: g.game_id });
  }
  return changes;
}

export function summarize(games) {
  const s = { games: 0, final: 0, live: 0, upcoming: 0, postponed: 0, bets: 0, staked: 0, settled: 0, open: 0, toWinOpen: 0,
    liveBets: 0, ahead: 0, betW: 0, betL: 0, pickW: 0, pickL: 0, ifEnded: 0 };
  for (const g of games) {
    s.games++;
    if (g.state === 'scheduled') s.upcoming++; else if (g.state === 'live') s.live++;
    else if (g.state === 'final') s.final++; else s.postponed++;
    const r = result(g);
    if (g.state === 'final') { if (r === 'hit') s.pickW++; else if (r === 'miss') s.pickL++; }
    if (hasBet(g) && g.state !== 'postponed' && g.state !== 'void') {
      s.bets++; s.staked += g.bet.amount;
      if (g.state === 'final') { s.settled += pl(g) || 0; if (r === 'hit') s.betW++; else if (r === 'miss') s.betL++; }
      else {
        s.open += g.bet.amount; s.toWinOpen += fmt.payout(g.bet.amount, g.odds);
        if (g.state === 'live') {
          s.liveBets++; const m = pickMargin(g);
          if (m > 0) s.ahead++;
          s.ifEnded += m > 0 ? fmt.payout(g.bet.amount, g.odds) : m < 0 ? -g.bet.amount : 0;
        }
      }
    }
  }
  s.ifEnded += s.settled;
  return s;
}
export const summary = () => summarize(store.games);

export function nextUpOf(games, nowMs = Date.now()) {
  const c = games.filter(g => g.state === 'scheduled' && hasBet(g) && tipMs(g) > nowMs);
  if (!c.length) return null;
  return c.sort((a, b) => (tipMs(a) - tipMs(b)) || ((b.edge ?? -Infinity) - (a.edge ?? -Infinity)) || a.game_id.localeCompare(b.game_id))[0];
}
export const nextUp = () => nextUpOf(store.games, now());

export const pendingBets = () => store.games.some(g => g.state === 'scheduled' && hasBet(g));

export const FILTERS = [['all', 'All'], ['bets', 'Bets'], ['live', 'Live'], ['upcoming', 'Upcoming'], ['final', 'Final']];
export const SORTS = [['tip', 'Tip-off'], ['edge', 'Edge'], ['bet', 'Bet size']];
export function matches(g, f) {
  return f === 'all' || (f === 'bets' && !!g.bet) || (f === 'live' && g.state === 'live') ||
    (f === 'upcoming' && g.state === 'scheduled') || (f === 'final' && g.state === 'final');
}
export function countsOf(games) { return Object.fromEntries(FILTERS.map(([k]) => [k, games.filter(g => matches(g, k)).length])); }
export const counts = () => countsOf(store.games);
const byTipCmp = (a, b) => (tipMs(a) - tipMs(b)) || a.game_id.localeCompare(b.game_id);
export function visibleOf(games, filter, sort) {
  const amt = g => (g.bet && g.bet.amount) || 0, e = g => g.edge ?? -Infinity;
  const by = {
    tip: byTipCmp,
    edge: (a, b) => (e(b) - e(a)) || byTipCmp(a, b),
    bet: (a, b) => (amt(b) - amt(a)) || byTipCmp(a, b)
  }[sort] || byTipCmp;
  return games.filter(g => matches(g, filter)).sort(by);
}
export const visible = () => visibleOf(store.games, store.filter, store.sort);
export const byTip = () => store.games.slice().sort(byTipCmp);
export const game = id => store.games.find(g => g.game_id === id);
export function setFilter(k) { if (FILTERS.some(([f]) => f === k)) store.filter = k; }
export function setSort(k) { if (SORTS.some(([s]) => s === k)) store.sort = k; }

// ---------- clock ----------
let lastLive = null;
export function now() {
  if (!SAMPLE) return Date.now();
  if (lastLive && lastLive.fetched_at && !Number.isNaN(Date.parse(lastLive.fetched_at))) return Date.parse(lastLive.fetched_at);
  return Date.parse(sampleNowIso() || (store.slate && store.slate.generated_at) || new Date().toISOString());
}
export function todayIso() { return SAMPLE ? sampleTonight() : dateET(new Date()); }

// ---------- lifecycle ----------
const allDone = () => store.games.length > 0 && store.games.every(g => ['final', 'postponed', 'void'].includes(g.state));
const noLiveNight = () => store.isPast || !store.slate || ['no_games', 'offseason'].includes(store.slate.phase) || store.slate.offseason === true || !store.games.length;
const wantsPoll = () => !noLiveNight() && !allDone() &&
  store.games.some(g => g.state === 'live' || (g.state === 'scheduled' && tipMs(g) - now() <= WINDOW_MS));

let pollIndex = 0, inFlight = null, pollTimer = null, tickTimer = null, slateTimer = null, slateAttempt = 0;
let refetchTimer = null, firstMergeDone = false, started = false, liveFirst = null;

function setFeed(status) {
  const prev = store.feed.status;
  if (prev === status) return;
  store.feed.status = status;
  document.documentElement.dataset.feed = status;
  emit([{ type: 'feed', status, prev }]);
}
function checkDown() {
  if (store.feed.status !== 'down' && Date.now() - store.feed.lastFreshAt > DOWN_MS && !allDone()) setFeed('down');
}

function mergeLive(resp) {
  if (!resp || !Array.isArray(resp.games)) throw new ApiError(502, 'bad_json');
  const stale = resp.stale === true || !resp.fetched_at || Number.isNaN(Date.parse(resp.fetched_at));
  lastLive = resp;
  store.feed.source = resp.source || null;
  store.feed.asOf = resp.fetched_at || store.feed.asOf;
  const silent = !firstMergeDone;
  firstMergeDone = true;
  const changes = applyLive(store.games, resp, silent);
  if (stale) setFeed('delayed');
  else { store.feed.failures = 0; store.feed.lastFreshAt = Date.now(); setFeed('ok'); }
  return changes;
}

async function poll(force) {
  if (inFlight) { await inFlight; if (!force) return; }
  if (!force && (!wantsPoll() || document.hidden)) return;
  const idx = ++pollIndex;
  inFlight = (async () => {
    try {
      const resp = await api.liveScores(store.date, idx);
      const changes = mergeLive(resp);
      emit(changes);
      if (allDone()) { stopPolling(); setFeed('ok'); scheduleSettleRefetch(); }
    } catch (e) {
      store.feed.failures++;
      if (SAMPLE && SCENE === 'feeddown') setFeed('down');
      else if (store.feed.failures >= 2 && store.feed.status === 'ok') setFeed('delayed');
      checkDown();
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

function stopPolling() { clearInterval(pollTimer); pollTimer = null; }
function startPolling() {
  if (pollTimer || noLiveNight() || allDone()) return;
  pollTimer = setInterval(() => {
    if (allDone()) { stopPolling(); setFeed('ok'); return; }
    if (wantsPoll()) { if (!document.hidden) poll(); checkDown(); }
  }, POLL_MS);
}
function startTick() {
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    if (store.games.some(g => g.state === 'scheduled')) emit([{ type: 'tick' }]);
    else { clearInterval(tickTimer); tickTimer = null; }
  }, TICK_MS);
}

// Reconcile a refetched slate: take the new slate fields, keep live fields where we are further along.
const RANK = { scheduled: 0, live: 1, final: 2, postponed: 2, void: 2 };
function reconcile(slate) {
  const old = new Map(store.games.map(g => [g.game_id, g]));
  store.games = (slate.games || []).map(sg => {
    const n = normalize(sg), o = old.get(sg.game_id);
    if (o && RANK[o.state] > RANK[n.state]) Object.assign(n, { state: o.state, period: o.period, clock: o.clock, hs: o.hs, as: o.as });
    return n;
  });
  setSlateMeta(slate);
}
function setSlateMeta(slate) {
  const meta = Object.assign({}, slate); delete meta.games;
  store.slate = meta;
  store.isPast = !!slate.is_past;
}

function scheduleBeforeRefetch() {
  clearTimeout(refetchTimer);
  if (!store.slate || store.slate.phase !== 'before_predictions' || store.isPast) return;
  refetchTimer = setTimeout(async () => {
    if (document.hidden) { scheduleBeforeRefetch(); return; }
    try {
      const s = await api.slate(store.date || undefined);
      const changed = s.phase !== store.slate.phase || (s.games || []).some(sg => { const o = game(sg.game_id); return !o || o.pick !== sg.pick || !!o.bet !== !!sg.bet; });
      if (changed) { reconcile(s); emit([{ type: 'slate', refetch: true }]); }
    } catch { /* try again next minute */ }
    scheduleBeforeRefetch();
  }, BEFORE_REFETCH_MS);
}
function scheduleSettleRefetch() {
  clearTimeout(refetchTimer);
  if (store.isPast || !allDone() || SAMPLE) return;
  if (!store.games.some(g => g.bet && !g.official)) return;
  refetchTimer = setTimeout(async () => {
    if (!document.hidden) {
      try { const s = await api.slate(store.date || undefined); reconcile(s); emit([{ type: 'slate', refetch: true }]); } catch { /* retry later */ }
    }
    scheduleSettleRefetch();
  }, SETTLE_REFETCH_MS);
}

async function loadSlate() {
  clearTimeout(slateTimer);
  try {
    const slate = await api.slate(store.date || undefined);
    store.status = 'ready';
    slateAttempt = 0;
    store.games = (slate.games || []).map(normalize);
    setSlateMeta(slate);
    if (!store.date) store.date = slate.date;
    // Merge a live response that is already in (or lands within 800 ms) silently.
    if (liveFirst && !store.isPast) {
      const lr = await Promise.race([liveFirst, new Promise(r => setTimeout(() => r(null), 800))]);
      if (lr) { try { mergeLive(lr); } catch { /* treat as a failed poll */ } liveFirst = null; }
      else liveFirst.then(r => { if (r && !firstMergeDone) { try { mergeLive(r); emit([{ type: 'slate', late: true }]); } catch { /* ignore */ } } });
    }
    emit([{ type: 'slate' }]);
    if (!started) {
      started = true;
      if (!store.isPast) { startPolling(); startTick(); }
      addEventListener('visibilitychange', () => { if (!document.hidden && wantsPoll()) poll(); });
      addEventListener('online', () => { if (wantsPoll()) poll(); });
    }
    scheduleBeforeRefetch();
    if (allDone()) scheduleSettleRefetch();
  } catch (e) {
    store.status = 'error';
    const nextInMs = SLATE_BACKOFF[Math.min(slateAttempt, SLATE_BACKOFF.length - 1)];
    slateAttempt++;
    emit([{ type: 'slate-error', attempt: slateAttempt, nextInMs }]);
    slateTimer = setTimeout(loadSlate, nextInMs);
  }
}

export function retrySlate() { clearTimeout(slateTimer); slateAttempt = 0; return loadSlate(); }
export function refreshNow() { return poll(); }

const validDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d) && !Number.isNaN(Date.parse(d + 'T12:00:00Z')) && new Date(d + 'T12:00:00Z').toISOString().slice(0, 10) === d;

export async function init(o = {}) {
  store.date = o.date && validDate(o.date) ? o.date : null;
  document.documentElement.dataset.feed = 'ok';
  const past = store.date && store.date < todayIso();
  if (!past) {
    pollIndex = 0;
    liveFirst = api.liveScores(store.date, 0).catch(() => {
      store.feed.failures++;
      if (SAMPLE && SCENE === 'feeddown') setFeed('down');
      return null;
    });
  }
  if (SAMPLE && typeof window !== 'undefined') {
    // Sample-only test hook: step the live-replay files (the shipped page has no control for it).
    window.__sampleFeed = Object.freeze({
      async step() { sampleReplayStep(); await poll(true); return summary(); }
    });
  }
  await loadSlate();
}
