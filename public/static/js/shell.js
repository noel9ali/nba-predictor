// App shell: tab hrefs and aria-current, the run-status pill, the "Sample data" tag and the
// migration note. Tabs are plain links; nothing here takes input.
import { api, onEnvelope, SAMPLE, sampleQuery, sampleTonight } from './api.js';
import { fmt, dateET } from './format.js';

const $ = s => document.querySelector(s);
let opts = null;
let slateInfo = null;
let lastWS = null;
let wsTimer = null;

function withQuery(path, extra) {
  const hashAt = path.indexOf('#');
  const base = hashAt < 0 ? path : path.slice(0, hashAt), hash = hashAt < 0 ? '' : path.slice(hashAt);
  const q = [extra, sampleQuery()].filter(Boolean).join('&');
  return base + (q ? '?' + q : '') + hash;
}

function yesterdayET() {
  const today = SAMPLE ? sampleTonight() : dateET(new Date());
  const d = new Date(today + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

function setCurrent(tab) {
  document.querySelectorAll('nav.tabs a').forEach(a => {
    if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
}

function renderTabs() {
  const tabs = {};
  document.querySelectorAll('nav.tabs a').forEach(a => { tabs[a.dataset.tab] = a; });
  const pastDate = (opts.dateParam && (!slateInfo || slateInfo.is_past)) ? opts.dateParam
    : (slateInfo && slateInfo.last_slate_date) || yesterdayET();
  if (tabs.tonight) tabs.tonight.href = withQuery('/');
  if (tabs.past) tabs.past.href = withQuery('/', 'date=' + pastDate);
  if (tabs.season) tabs.season.href = withQuery('/#season');
  if (tabs.model) tabs.model.href = withQuery('/model');
  if (opts.page === 'model') setCurrent('model');
  else if (slateInfo) setCurrent(slateInfo.is_past ? 'past' : 'tonight');
  else setCurrent(opts.dateParam ? 'past' : 'tonight');
}

function renderStatus() {
  const el = $('[data-status]');
  if (!el) return;
  const ws = lastWS;
  if (!ws || (slateInfo && slateInfo.is_past)) { el.hidden = true; return; }
  let state;
  const p = ws.latest && ws.latest.predict;
  if (ws.running === true) state = 'running';
  else if (!p) state = 'none';
  else if (opts.page === 'tonight' && slateInfo && p.run_date != null && p.run_date !== slateInfo.date) state = 'none';
  else state = p.state || 'none';
  let text = { running: 'Picks running…', failed: 'Picks failed', missed: 'Picks missed', none: 'No picks yet' }[state];
  if (state === 'ok') {
    const when = p.finished_at || p.started_at;
    if (when && !Number.isNaN(Date.parse(when))) text = 'Picks posted ' + fmt.time(when) + ' ET';
    else { state = 'none'; text = 'No picks yet'; }
  }
  if (!text) { state = 'none'; text = 'No picks yet'; }
  el.dataset.state = state;
  el.querySelector('[data-status-text]').textContent = text;
  el.hidden = false;
}

async function loadStatus() {
  clearTimeout(wsTimer);
  try {
    lastWS = await api.workflowStatus();
  } catch {
    lastWS = null;
  }
  renderStatus();
  if (!lastWS) return;
  const wait = lastWS.running === true ? 30000 : 300000;
  wsTimer = setTimeout(function again() {
    if (document.hidden) { wsTimer = setTimeout(again, wait); return; }
    loadStatus();
  }, wait);
}

export function initShell(o) {
  opts = o;
  const tag = $('[data-sample-tag]');
  if (tag) tag.hidden = !SAMPLE;
  onEnvelope(body => { if (body.migration_pending === true) setMigrationPending(true); });
  renderTabs();
  loadStatus();
}

export function setPageDate(slate) {
  slateInfo = { date: slate.date, is_past: !!slate.is_past, last_slate_date: slate.last_slate_date || null };
  if (opts) { renderTabs(); renderStatus(); }
}

export function setMigrationPending(on) {
  const note = $('[data-migration-note]');
  if (note && on) note.hidden = false;
}
