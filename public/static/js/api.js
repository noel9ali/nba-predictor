// Same-origin JSON API, plus sample mode: ?sample=1 answers every call from public/sample/*.json
// (files shaped exactly like the API responses; tests/contract_shapes.py is the contract).
// &scene= picks which night to show. Nothing here builds HTML.

const params = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();
export const SAMPLE = params.get('sample') === '1';

// Each sample scene: the slate file suffix, the live-scores files in poll order, and the clock.
export const SCENES = {
  live: { now: '2026-11-18T02:05:00Z', slate: '', live: ['live'] },
  nextup: { now: '2026-11-17T23:40:00Z', slate: '', live: ['pre'] },
  sofar: { now: '2026-11-18T03:40:00Z', slate: '', live: ['sofar'] },
  final: { now: '2026-11-18T06:05:00Z', slate: '', live: ['final'] },
  nobets: { now: '2026-11-17T23:30:00Z', slate: '-nobets', live: ['pre'] },
  before: { now: '2026-11-17T19:00:00Z', slate: '-before', live: ['pre'] },
  failed: { now: '2026-11-18T00:12:00Z', slate: '-failed', live: ['failed'] },
  offseason: { now: '2027-07-20T19:00:00Z', slate: '-offseason', live: [], tonight: '2027-07-20' },
  edges: { now: '2026-11-18T03:50:00Z', slate: '-edges', live: ['edges'] },
  stale: { now: '2026-11-18T02:05:00Z', slate: '', live: ['live'], stale: true },
  feeddown: { now: '2026-11-18T02:09:30Z', slate: '', live: ['FAIL'] },
  early: { now: '2026-11-18T02:05:00Z', slate: '', live: ['live'] },
  replay: { now: '2026-11-18T02:05:00Z', slate: '', live: ['replay-0', 'replay-1', 'replay-2', 'replay-3', 'replay-4', 'replay-5', 'replay-6'] }
};
const askedScene = params.get('scene');
export const SCENE = SAMPLE ? (Object.prototype.hasOwnProperty.call(SCENES, askedScene) ? askedScene : 'live') : null;
export const SAMPLE_TONIGHT = '2026-11-17';
export const sampleTonight = () => (SAMPLE ? SCENES[SCENE].tonight || SAMPLE_TONIGHT : null);
export const sampleNowIso = () => (SAMPLE ? SCENES[SCENE].now : null);

export class ApiError extends Error {
  constructor(status, code) {
    super('API ' + status + (code ? ' ' + code : ''));
    this.status = status;
    this.code = code || null;
  }
}

// Every response envelope passes through here (the shell shows the migration note).
const envelopeHooks = [];
export function onEnvelope(fn) { envelopeHooks.push(fn); }
function seen(body) {
  if (body && typeof body === 'object') envelopeHooks.forEach(fn => { try { fn(body); } catch (e) { console.warn(e); } });
  return body;
}

const TIMEOUT_MS = 10000;
async function getJSON(path, query = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const url = '/api/' + path + (qs.toString() ? '?' + qs : '');
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: ctl.signal });
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    if (!r.ok) throw new ApiError(r.status, body && typeof body.error === 'string' ? body.error : null);
    if (!body || typeof body !== 'object') throw new ApiError(502, 'bad_json');
    return seen(body);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, e && e.name === 'AbortError' ? 'timeout' : 'network');
  } finally {
    clearTimeout(timer);
  }
}

// ---------- sample files ----------
const cache = new Map();
async function sampleFile(name) {
  if (!/^[a-z0-9-]+$/.test(name)) throw new ApiError(404, 'not_found');
  if (!cache.has(name)) {
    cache.set(name, fetch('/sample/' + name + '.json', { headers: { Accept: 'application/json' } }).then(r => {
      if (!r.ok) throw new ApiError(r.status === 404 ? 404 : 503, r.status === 404 ? 'not_found' : 'sample_unavailable');
      return r.json();
    }));
  }
  try {
    return seen(structuredClone(await cache.get(name)));
  } catch (e) {
    cache.delete(name);
    throw e;
  }
}

async function sampleSlate(date) {
  const tonight = sampleTonight();
  const day = date || tonight;
  if (day === tonight) return sampleFile('slate-' + SAMPLE_TONIGHT + SCENES[SCENE].slate);
  try {
    return await sampleFile('slate-' + day);
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 404) throw e;
    const days = await sampleFile('days');
    const earlier = days.days.map(d => d.date).filter(d => d < day).sort();
    return {
      generated_at: SCENES[SCENE].now, migration_pending: false, date: day, season: '2026-27', is_past: day < tonight,
      phase: 'no_games', offseason: false, last_slate_date: earlier.length ? earlier[earlier.length - 1] : null,
      summary: { games: 0, final: 0, live: 0, upcoming: 0, bets_placed: 0, staked: 0, settled_pl: 0 }, games: [], recap: null
    };
  }
}

// Replay stepping (sample only). The test hook in state.js moves through live-replay-1..6.
let replayIdx = null;
export function sampleReplayStep() { replayIdx = replayIdx == null ? 1 : Math.min(6, replayIdx + 1); return replayIdx; }

async function sampleLive(pollIndex) {
  const sc = SCENES[SCENE];
  if (replayIdx != null) return sampleFile('live-replay-' + replayIdx);
  if (!sc.live.length) throw new ApiError(404, 'not_found');
  const step = sc.live[Math.min(pollIndex || 0, sc.live.length - 1)];
  if (step === 'FAIL') throw new ApiError(503, 'live_unavailable');
  const body = await sampleFile('live-' + step);
  if (!step.startsWith('replay')) body.fetched_at = body.generated_at = sc.now;
  if (sc.stale) body.stale = true;
  return body;
}

// ---------- public API ----------
export const api = {
  slate(date) { return SAMPLE ? sampleSlate(date) : getJSON('slate', { date }); },
  liveScores(date, pollIndex = 0) { return SAMPLE ? sampleLive(pollIndex) : getJSON('live-scores', { date }); },
  gameDetail(id) {
    if (!/^\d{10}$/.test(String(id))) return Promise.reject(new ApiError(404, 'not_found'));
    return SAMPLE ? sampleFile('game-' + id) : getJSON('game/' + encodeURIComponent(id));
  },
  async performance(season) {
    if (!SAMPLE) return getJSON('performance', { season });
    if (SCENE === 'early' && season !== 'all') return sampleFile('performance-early');
    if (season === 'all') {
      try { return await sampleFile('performance-all'); } catch { return { ...(await sampleFile('performance')), season: 'all' }; }
    }
    try { return await sampleFile('performance-' + season); } catch { return sampleFile('performance'); }
  },
  model() { return SAMPLE ? sampleFile('model') : getJSON('model'); },
  featuredPick() { return SAMPLE ? sampleFile('featured-pick') : getJSON('featured-pick'); },
  workflowStatus() {
    if (SAMPLE) return sampleFile(SCENE === 'failed' ? 'workflow-status-failed' : 'workflow-status').then(b => ({ ...b, controls_allowed: false }));
    return getJSON('workflow-status');
  }
};

// Query string that keeps sample mode on internal links: "sample=1&scene=x" or "".
export function sampleQuery() {
  if (!SAMPLE) return '';
  return 'sample=1' + (askedScene && SCENE === askedScene ? '&scene=' + encodeURIComponent(SCENE) : '');
}
