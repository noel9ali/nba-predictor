// Tonight page entry: shell, ambient, the state engine, and one coalesced render per frame.
import { initShell, setPageDate } from './shell.js';
import { initAmbient } from './ambient.js';
import { api, SAMPLE, SCENE, sampleQuery } from './api.js';
import { fmt, seasonOf } from './format.js';
import * as state from './state.js';
import { store, summary, FEED_COPY } from './state.js';
import { renderLede, renderCourts, updateCourtStates } from './tonight/glance.js';
import { initTickets, renderGrid, ticketsOnBatch } from './tonight/tickets.js';
import { mountToolbar, updateToolbar } from './tonight/toolbar.js';
import { initDrawer, openDetail, openFromHash } from './tonight/drawer.js';
import { initToasts } from './tonight/toasts.js';
import { mountRibbon, updateRibbon } from './tonight/ribbon.js';
import { mountSeason, seasonOnBatch, mountModelCard, seasonError, modelError } from './tonight/season.js';

const $ = s => document.querySelector(s);
const params = new URLSearchParams(location.search);
const dateParam = params.get('date');

initShell({ page: 'tonight', sample: SAMPLE, scene: SCENE, dateParam });
initAmbient();
initDrawer();
initTickets({ onOpen: openDetail });

const modelLink = $('[data-model-link]');
if (modelLink && sampleQuery()) modelLink.href = '/model?' + sampleQuery();

let firstSlate = true, toolbarMounted = false, ribbonMounted = false, toastsOn = false;
let pending = [], frame = 0;

function phaseOf() { return (store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase)) || null; }

function renderPageStates() {
  const phase = phaseOf();
  const noTickets = store.status === 'error' || phase === 'no_games' || phase === 'offseason';
  $('[data-tix-section]').hidden = noTickets;
  $('[data-toolbar]').hidden = noTickets || !store.games.length;
  const pb = $('[data-pred-banner]');
  pb.hidden = phase !== 'prediction_failed';
  if (!pb.hidden) pb.textContent = "Tonight's prediction run failed. Scores still update.";
  const fb = $('[data-feed-banner]');
  fb.hidden = store.feed.status !== 'down' || store.isPast;
  if (!fb.hidden) fb.textContent = FEED_COPY.down;
  if (store.isPast && store.slate) document.title = 'NBA Predictor · ' + fmt.date(store.slate.date, { month: 'short', day: 'numeric' });
}

function onSlate() {
  const s = summary();
  renderLede(s);
  renderCourts(openDetail);
  renderPageStates();
  if (!toolbarMounted && store.games.length) { mountToolbar({ renderGrid }); toolbarMounted = true; }
  else if (toolbarMounted) updateToolbar();
  renderGrid({ replay: false });
  if (!ribbonMounted) { mountRibbon(); ribbonMounted = true; }
  updateRibbon(s);
  setPageDate(store.slate);
  seasonOnBatch([{ type: 'slate' }]);
  if (firstSlate) {
    firstSlate = false;
    openFromHash();
    if (!toastsOn) { initToasts(); toastsOn = true; }
    slateSettled();
  }
}

function flush() {
  frame = 0;
  const batch = pending; pending = [];
  if (!batch.length) return;
  if (batch.some(c => c.type === 'slate')) { onSlate(); return; }
  const err = batch.find(c => c.type === 'slate-error');
  if (err) {
    renderLede(null, { error: true });
    renderPageStates();
    if (firstSlate) slateSettled();
    return;
  }
  const s = summary();
  renderLede(s);
  updateCourtStates();
  if (toolbarMounted) updateToolbar();
  ticketsOnBatch(batch);
  updateRibbon(s);
  renderPageStates();
  seasonOnBatch(batch);
}

state.on(changes => {
  pending.push(...changes);
  if (!frame) frame = requestAnimationFrame(flush);
});

$('[data-retry]').addEventListener('click', () => state.retrySlate());

// ---------- parallel loads ----------
renderLede(null);
let resolveSlate;
const slateDone = new Promise(r => { resolveSlate = r; });
function slateSettled() { resolveSlate(); }

const season = dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam) ? seasonOf(dateParam) : seasonOf(state.todayIso());
const perfP = api.performance(season).then(async perf => {
  await slateDone;
  if (store.slate && store.slate.season && store.slate.season !== perf.season && perf.season !== 'all') {
    try { perf = await api.performance(store.slate.season); } catch { /* keep the first answer */ }
  }
  mountSeason(perf);
}).catch(() => { seasonError(() => api.performance(season).then(mountSeason)); });
const modelP = api.model().then(m => mountModelCard(m)).catch(() => { modelError(() => api.model().then(mountModelCard)); });

state.init({ date: dateParam, sample: SAMPLE, scene: SCENE });

Promise.allSettled([slateDone, perfP, modelP]).then(async () => {
  try { await document.fonts.ready; } catch { /* ignore */ }
  if (location.hash === '#season' && scrollY <= 100) {
    const el = document.getElementById('season');
    if (el) el.scrollIntoView({ block: 'start' });
  }
  requestAnimationFrame(() => { document.documentElement.dataset.ready = 'true'; });
});

addEventListener('hashchange', () => {
  if (location.hash === '#season') { const el = document.getElementById('season'); if (el) el.scrollIntoView({ block: 'start' }); }
});
