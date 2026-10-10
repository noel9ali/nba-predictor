// The model page entry: parallel fetches, chapters in DOM order as their data lands, computed
// chapter numbers, the page error panel and the footer. No polling on this page.
import { initShell } from './shell.js';
import { initAmbient } from './ambient.js';
import { api, SAMPLE, SCENE } from './api.js';
import { fmtDate, TZ, modelLabel } from './format.js';
import { observeReveals } from './reveal.js';
import { initClaim } from './model/claim.js';
import { initAlltime } from './model/alltime.js';
import { initSeasons } from './model/seasons.js';
import { renderRowCard } from './model/rowcard.js';
import { initWalkthrough } from './model/walkthrough.js';
import { initWeights } from './model/weights.js';
import { initTryouts } from './model/tryouts.js';
import { initCalibration } from './model/calibration.js';

const $ = s => document.querySelector(s);
const ch = n => document.getElementById('ch' + n);

initShell({ page: 'model', sample: SAMPLE, scene: SCENE, dateParam: null });
initAmbient();

const soft = (p, what) => p.catch(e => { console.warn('model page: ' + what + ' unavailable', e && e.message); return null; });

function show(section, ok) { section.hidden = !ok; numberChapters(); }
export function numberChapters() {
  let n = 0;
  document.querySelectorAll('section.chapter').forEach(s => {
    n++;
    const k = s.querySelector('.ch .k');
    if (k) k.textContent = 'Chapter ' + n;
  });
}

function safe(fn, section, what) {
  try { return fn(); } catch (e) { console.warn('model page: ' + what + ' failed', e); if (section) section.hidden = true; return null; }
}

// ---------- footer ----------
function footer(model) {
  const parts = [];
  if (model.production_model) parts.push('Model ' + modelLabel(model.production_model));
  if (model.trained_at && !Number.isNaN(Date.parse(model.trained_at))) {
    const d = new Date(model.trained_at);
    const t = d.toLocaleTimeString('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' }).replace(/[  ]/g, ' ');
    parts.push('retrained ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: TZ }) + ', ' + t + ' ET');
  }
  const tr = model.training || {};
  const cutoff = tr.cutoff_date || model.cutoff_date;
  if (tr.first_game_date && cutoff) parts.push('training games ' + fmtDate(tr.first_game_date) + ' – ' + fmtDate(cutoff));
  if (cutoff && tr.last_game_date) parts.push('test games ' + fmtDate(cutoff) + ' – ' + fmtDate(tr.last_game_date));
  let text = parts.join(' · ');
  if (SAMPLE && text) text += ' · Sample data: record and calibration come from the sample season.';
  $('[data-foot]').textContent = text;
}

// ---------- model-dependent chapters ----------
let model = null, alltime = null, seasons = null, detail = null;
function renderModelChapters(m) {
  model = m;
  safe(() => initClaim(m), null, 'hero');
  seasons = safe(() => initSeasons(ch(2), m), ch(2), 'chapter 2');
  show(ch(2), !!seasons);
  show(ch(4), !!safe(() => initWeights(ch(4), m), ch(4), 'chapter 4'));
  show(ch(5), !!safe(() => initTryouts(ch(5), m), ch(5), 'chapter 5'));
  show(ch(6), !!safe(() => initCalibration(ch(6), m), ch(6), 'chapter 6'));
  footer(m);
  if (alltime && alltime.setModel) alltime.setModel(m);
}

function errorPanel(retry) {
  const el = document.createElement('div');
  el.className = 'card model-error';
  el.setAttribute('role', 'alert');
  el.dataset.error = '';
  const p = document.createElement('p'); p.textContent = "Can't load the model's numbers. Retrying…";
  const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Retry';
  b.addEventListener('click', retry);
  el.append(p, b);
  $('main#model').prepend(el);
  return el;
}

async function loadModelWithRetry() {
  let m = await soft(api.model(), '/api/model');
  if (m) return m;
  return new Promise(resolve => {
    let done = false;
    const attempt = async () => {
      if (done) return;
      const r = await soft(api.model(), '/api/model');
      if (r && !done) { done = true; panel.remove(); resolve(r); }
    };
    const panel = errorPanel(attempt);
    [5000, 20000, 50000].forEach(ms => setTimeout(attempt, ms));
  });
}

// ---------- boot: all requests in the same tick ----------
const modelP = loadModelWithRetry();
const perfP = soft(api.performance('all'), '/api/performance?season=all');
const detailP = soft(api.featuredPick(), '/api/featured-pick')
  .then(f => (f && f.game_id ? soft(api.gameDetail(f.game_id), '/api/game') : null));

const first = Promise.race([modelP, new Promise(r => setTimeout(() => r(null), 8000))]);

perfP.then(async perfAll => {
  if (!perfAll) { show(ch(1), false); return; }
  alltime = safe(() => initAlltime(ch(1), { model, perfAll }), ch(1), 'chapter 1');
  show(ch(1), !!alltime);
  observeReveals();
});

modelP.then(m => { if (m) { renderModelChapters(m); observeReveals(); } });

Promise.all([detailP, first]).then(([d, m]) => {
  detail = d;
  const walkthrough = ch(3);
  const body = walkthrough && walkthrough.querySelector('[data-body]');
  const lede = walkthrough && walkthrough.querySelector('[data-lede]');

  let walkthroughOk = false;
  if (d && safe(() => initWalkthrough(walkthrough, d, m || {}), walkthrough, 'chapter 3')) {
    walkthroughOk = true;
  } else if (body) {
    // Show fallback card when walkthrough fails
    body.textContent = '';
    const card = document.createElement('div');
    card.className = 'card walk-fallback';
    card.setAttribute('role', 'status');
    const p = document.createElement('p');
    p.textContent = 'Walkthrough unavailable: the featured game couldn\'t load.';
    card.append(p);
    body.append(card);
    if (lede) lede.textContent = '';
    walkthroughOk = true;  // Keep ch3 visible with fallback
  }
  show(ch(3), walkthroughOk);

  if (d && seasons && seasons.rowCardMount) {
    safe(() => renderRowCard(seasons.rowCardMount, { detail: d, rollingWindow: (m && m.training && m.training.rolling_window) || 10 }), null, 'row card');
  } else if (seasons && seasons.rowCardMount && seasons.rowCardMount.parentElement) {
    // Show fallback row card when detail is missing
    seasons.rowCardMount.textContent = '';
    const card = document.createElement('div');
    card.className = 'card rowcard-fallback';
    card.setAttribute('role', 'status');
    const p = document.createElement('p');
    p.textContent = '"One game, one row" is unavailable: the featured game couldn\'t load.';
    card.append(p);
    seasons.rowCardMount.append(card);
  }

  observeReveals();
});

Promise.allSettled([first, perfP, detailP]).then(() => {
  numberChapters();
  observeReveals();
  requestAnimationFrame(() => { document.documentElement.dataset.ready = ''; });
});
