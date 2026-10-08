// "How the model is doing": season board, pinned bankroll chart with three scroll steps
// (T13–T15), the last-33 W/L strip (T16) and the calibration card with model facts (T17).
import { fmt, esc, wl, MINUS, word, seasonLabel, modelLabel } from '../format.js';
import { renderBoard, signCls } from '../board.js';
import { renderCalibration } from '../calibration-chart.js';
import { watch, motionOn, replay } from '../reveal.js';
import { store, summary } from '../state.js';

const $ = s => document.querySelector(s);
let perf = null, model = null;
let host = null, geo = null, cur = -1, wired = false, stepsWired = false, drewOnce = false;
const TITLES = ['Bankroll', 'Bankroll · worst stretch', 'Bankroll · tonight'];
const md = d => fmt.date(d, { month: 'short', day: 'numeric' });
const r1 = v => Math.round(v * 10) / 10;
const spelled = n => (n >= 1 && n <= 12 ? word(n).charAt(0).toUpperCase() + word(n).slice(1) : String(n));

// ---------- board + step copy ----------
function renderSeasonBoard() {
  const k = perf.kpis, first = perf.series && perf.series.length ? md(perf.series[0].date) : null;
  $('[data-season-kick]').textContent = seasonLabel(perf.season === 'all' ? (store.slate && store.slate.season) || '' : perf.season) + ' season' + (first ? ' · since ' + first : '');
  const dd = k.max_drawdown && k.max_drawdown.amount ? k.max_drawdown.amount : 0;
  renderBoard($('[data-testid=season-board]'), [
    { label: 'Bankroll', value: fmt.money(k.bankroll) },
    { label: first ? 'Since ' + first : 'Since start', value: fmt.money(k.net_pl, true), cls: signCls(k.net_pl) },
    { label: 'ROI', value: k.roi == null ? '—' : (k.roi >= 0 ? '+' : MINUS) + Math.abs(k.roi * 100).toFixed(1) + '%', cls: k.roi == null ? '' : signCls(k.roi) },
    { label: 'Bets W–L', value: wl(k.bets) || '—' },
    { label: 'Pick accuracy', value: fmt.pct(k.accuracy) },
    { label: 'Max drawdown', value: dd ? MINUS + fmt.money(dd) : fmt.money(0) }
  ]);
}

function weeksIn(a, b) {
  const days = Math.round((Date.parse(b + 'T12:00:00Z') - Date.parse(a + 'T12:00:00Z')) / 86400000);
  if (days < 7) return days + ' nights in';
  const w = Math.round(days / 7);
  return (w <= 12 ? spelled(w) : String(w)) + (w === 1 ? ' week in' : ' weeks in');
}

function stepText(S, base) {
  const k = perf.kpis, start = k.start_bankroll ?? 1000, last = S[S.length - 1];
  const set = (n, h, p) => { const el = $('.bstep[data-bs="' + n + '"] .bstep__in'); el.querySelector('h4').textContent = h; el.querySelector('p').textContent = p; };
  const gain = (last.bankroll - start) / start * 100;
  set(1, 'From ' + fmt.money(start) + ' to ' + fmt.money(last.bankroll),
    "Every night the paper bankroll moves by that night's settled bets. " + weeksIn(S[0].date, last.date) + ', ' +
    (Math.abs(gain) < 0.05 ? "it's flat" : "it's " + (gain > 0 ? 'up ' : 'down ') + Math.abs(gain).toFixed(1) + '%') +
    '. Hover the line or use arrow keys for any night.');
  const dd = k.max_drawdown || {}, pI = S.findIndex(x => x.date === dd.peak_date), tI = S.findIndex(x => x.date === dd.trough_date);
  if (dd.amount && pI >= 0 && tI > pI) {
    const nights = tI - pI;
    set(2, 'The worst stretch', 'From the ' + md(dd.peak_date) + ' peak of ' + fmt.money(S[pI].bankroll) + ' to ' + md(dd.trough_date) +
      ', it gave back ' + fmt.money(dd.amount) + ' over ' + (nights <= 12 ? word(nights) : nights) + ' nights. Quarter-Kelly sizing is what keeps a stretch like this from doing real damage.');
  } else set(2, 'The worst stretch', "The bankroll hasn't had a down stretch yet.");
  const sm = summary(), phase = store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase);
  if (store.isPast && store.slate) {
    const night = S.find(x => x.date === store.slate.date);
    set(3, 'That night', night ? 'On ' + md(night.date) + ' the bankroll moved ' + fmt.money(night.nightly_pl, true) + ' (bets ' + night.bets + ', picks ' + night.picks + ').' : 'No bankroll change recorded for that night.');
  } else if (!store.slate || sm.bets === 0 || ['no_games', 'offseason'].includes(phase)) {
    set(3, 'Nothing on the line tonight', 'No bets tonight, so the bankroll holds at ' + fmt.money(base) + '.');
  } else if (sm.open === 0) {
    set(3, "Tonight's on the line", "Every game is final, so the dashed line shows where tonight's results leave the bankroll. It joins the line at the 6 AM settle.");
  } else {
    set(3, "Tonight's on the line", 'The dashed line is where the bankroll lands if every game ended right now. The bar shows the full range: every open bet losing, or every one cashing.');
  }
}

// ---------- the chart ----------
function renderBankroll(step) {
  if (!perf || !host) return;
  const S = (perf.series || []).filter(x => !x.pending || x.bets !== '0-0');
  if (S.length < 2) {
    $('[data-bscrolly]').hidden = true;
    let note = $('[data-chart-note]');
    if (!note) { note = document.createElement('div'); note.className = 'card'; note.dataset.chartNote = ''; $('[data-bscrolly]').after(note); }
    note.textContent = 'Not enough settled nights yet. The chart starts after the first settle.';
    return;
  }
  const k = perf.kpis, N = S.length, base = S[N - 1].bankroll, start = k.start_bankroll ?? 1000;
  const sm = summary(), phase = store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase);
  const tonightOn = !!store.slate && !store.isPast && !['no_games', 'offseason'].includes(phase) && store.games.length > 0;
  const tnNow = base + (tonightOn ? sm.ifEnded : 0), tnLo = base + (tonightOn ? sm.settled - sm.open : 0), tnHi = base + (tonightOn ? sm.settled + sm.toWinOpen : 0);
  const W = Math.max(300, host.clientWidth || 700), H = Math.round(Math.min(300, Math.max(200, W * 0.36)));
  const pad = { l: 58, r: 16, t: 22, b: 28 };
  const ys = S.map(x => x.bankroll);
  const plotH = H - pad.t - pad.b;

  // Domain per step: 1-2 use series only (+start), 3 also includes tonight's range
  let domainValues;
  if (step === 3 && tonightOn) {
    domainValues = [start, ...ys, tnLo, tnHi, tnNow];
  } else {
    domainValues = [start, ...ys];
  }

  const minVal = Math.min(...domainValues), maxVal = Math.max(...domainValues);
  const pad_val = Math.max(10, 0.06 * (maxVal - minVal));
  let lo = minVal - pad_val, hi = maxVal + pad_val;

  // Find tick step: smallest of [10, 20, 25, 50, 100, 200, 250, 500] where step × plotH / (hi - lo) ≥ 28
  const tickSteps = [10, 20, 25, 50, 100, 200, 250, 500];
  let tickStep = 50; // default
  for (const ts of tickSteps) {
    if (ts * plotH / (hi - lo) >= 28) {
      tickStep = ts;
      break;
    }
  }

  // Snap domain to tick boundaries
  lo = Math.floor(lo / tickStep) * tickStep;
  hi = Math.ceil(hi / tickStep) * tickStep;

  const xs = i => pad.l + i * (W - pad.l - pad.r - 14) / N;
  const yv = v => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo);
  const pts = S.map((x, i) => [xs(i), yv(x.bankroll)]);
  const path = p => 'M' + p.map(q => q[0].toFixed(1) + ',' + q[1].toFixed(1)).join('L');
  const d = path(pts), last = pts[N - 1], peakI = ys.indexOf(Math.max(...ys));
  let s = '';
  for (let v = lo; v <= hi; v += tickStep) {
    s += '<line class="gridl" x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + r1(yv(v)) + '" y2="' + r1(yv(v)) + '"/>' +
      '<text class="ax" x="' + (pad.l - 8) + '" y="' + r1(yv(v) + 4) + '" text-anchor="end">$' + v.toLocaleString('en-US') + '</text>';
  }
  s += '<line class="base" x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + r1(yv(start)) + '" y2="' + r1(yv(start)) + '"/>';
  s += '<path class="ar" d="' + d + 'L' + last[0].toFixed(1) + ',' + r1(yv(lo)) + 'L' + pad.l + ',' + r1(yv(lo)) + 'Z"/><path class="ln" d="' + d + '"/>';
  s += '<circle class="pk" cx="' + r1(pts[peakI][0]) + '" cy="' + r1(pts[peakI][1]) + '" r="5"/><text class="lbl" x="' + r1(pts[peakI][0]) + '" y="' + r1(pts[peakI][1] - 12) + '" text-anchor="middle">Peak ' + fmt.money(ys[peakI]) + '</text>';
  s += '<circle class="pk" cx="' + r1(last[0]) + '" cy="' + r1(last[1]) + '" r="5"/><g class="endg"><text class="lbl" x="' + r1(last[0] - 8) + '" y="' + r1(last[1] + 20) + '" text-anchor="end">' + fmt.money(base) + '</text></g>';
  // step 2: worst stretch
  const dd = k.max_drawdown || {}, pI = S.findIndex(x => x.date === dd.peak_date), tI = S.findIndex(x => x.date === dd.trough_date);
  if (dd.amount && pI >= 0 && tI > pI) {
    const lx = xs(tI) + 16, flip = lx + 50 > W - 2;
    s += '<g class="ov dd"><rect class="ddr" x="' + r1(xs(pI)) + '" y="' + pad.t + '" width="' + r1(xs(tI) - xs(pI)) + '" height="' + (H - pad.t - pad.b) + '"/>' +
      '<path class="ddl" d="' + path(pts.slice(pI, tI + 1)) + '"/>' +
      '<line class="ddb" x1="' + r1(xs(tI) + 10) + '" x2="' + r1(xs(tI) + 10) + '" y1="' + r1(pts[pI][1]) + '" y2="' + r1(pts[tI][1]) + '"/>' +
      '<text class="ddt" x="' + r1(flip ? xs(tI) - 6 : lx) + '" y="' + r1((pts[pI][1] + pts[tI][1]) / 2 + 4) + '"' + (flip ? ' text-anchor="end"' : '') + '>' + MINUS + fmt.money(dd.amount) + '</text></g>';
  }
  // step 3: tonight (or that night, on a past page)
  const tx = xs(N);
  if (store.isPast && store.slate) {
    const i = S.findIndex(x => x.date === store.slate.date);
    if (i >= 0) s += '<g class="ov pn"><circle class="tnp" cx="' + r1(pts[i][0]) + '" cy="' + r1(pts[i][1]) + '" r="7"/><text class="tnt" x="' + r1(pts[i][0]) + '" y="' + r1(pts[i][1] - 14) + '" text-anchor="middle">' + md(S[i].date) + ' ' + fmt.money(S[i].nightly_pl, true) + '</text></g>';
  } else if (tonightOn) {
    const yN = yv(tnNow), yHi = yv(tnHi), yLo = yv(tnLo), ranged = tonightOn && sm.open > 0;
    let o = '<g class="ov tn">';
    if (ranged) o += '<line class="tnr" x1="' + r1(tx) + '" x2="' + r1(tx) + '" y1="' + r1(yHi) + '" y2="' + r1(yLo) + '"/>';
    o += '<path class="tnl" d="M' + last[0].toFixed(1) + ',' + last[1].toFixed(1) + 'L' + tx.toFixed(1) + ',' + yN.toFixed(1) + '"/>' +
      '<circle class="tnp" cx="' + r1(tx) + '" cy="' + r1(yN) + '" r="6"/>' +
      '<text class="tnt" x="' + r1(tx - 12) + '" y="' + r1(yN - 12) + '" text-anchor="end">Tonight ' + fmt.money(tnNow) + '</text>';
    // Designer ruling 9: hide a range label that would sit within 18px of the Tonight label.
    const tY = yN - 12;
    if (ranged && Math.abs((yHi + 4) - tY) >= 18) o += '<text class="tns" x="' + r1(tx - 8) + '" y="' + r1(yHi + 4) + '" text-anchor="end">all cash ' + fmt.money(tnHi) + '</text>';
    if (ranged && Math.abs((yLo + 4) - tY) >= 18) o += '<text class="tns" x="' + r1(tx - 8) + '" y="' + r1(yLo + 4) + '" text-anchor="end">all lose ' + fmt.money(tnLo) + '</text>';
    s += o + '</g>';
  }
  const ticks = (N === 2 ? [0, 1] : [0, Math.floor(N / 2), N - 1]).map(i => '<text class="ax" x="' + r1(xs(i)) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? 'start' : i === N - 1 ? 'end' : 'middle') + '">' + md(S[i].date) + '</text>').join('');
  s += ticks + '<line class="cross" x1="0" x2="0" y1="' + pad.t + '" y2="' + (H - pad.b) + '" visibility="hidden"/>';
  host.classList.remove('pop');
  host.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" aria-hidden="true">' + s + '</svg><div class="tip" hidden></div>';
  const ln = host.querySelector('.ln');
  host.style.setProperty('--len', String(Math.ceil(ln.getTotalLength())));
  host.setAttribute('aria-label', 'Bankroll from ' + fmt.money(start) + ' on ' + md(S[0].date) + ' to ' + fmt.money(base) + ', peak ' + fmt.money(ys[peakI]) + ' on ' + md(S[peakI].date));
  geo = { S, pts, W, N, pad, lo, hi };
  if (cur >= 0 && document.activeElement === host) show(cur, false);
  stepText(S, base);
  measureStage();
  if (!drewOnce) { drewOnce = true; watch(host, el => el.classList.remove('pre'), { threshold: 0.4 }); }
}

function tipContent(x) {
  return ['<b>' + esc(fmt.date(x.date, { weekday: 'short', month: 'short', day: 'numeric' })) + '</b>',
    'Bankroll ' + esc(fmt.money(x.bankroll)),
    'Night ' + esc(fmt.money(x.nightly_pl, true)) + ' · bets ' + esc(x.bets) + ' · picks ' + esc(x.picks)];
}
function show(i, announce) {
  if (!geo) return;
  cur = i;
  const x = geo.S[i], p = geo.pts[i], cross = host.querySelector('.cross'), tip = host.querySelector('.tip');
  cross.setAttribute('x1', p[0]); cross.setAttribute('x2', p[0]); cross.setAttribute('visibility', 'visible');
  const sc = host.clientWidth / geo.W;
  tip.hidden = false;
  const parts = tipContent(x);
  tip.innerHTML = parts.join('<br>');
  // Measure tooltip after setting content
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  const PAD = 8;
  // X positioning: clamp with padding, or center if tooltip wider than available space
  const hostW = host.clientWidth;
  const px = p[0] * sc;
  let left;
  if (tw > hostW - 2 * PAD) {
    left = hostW / 2;
  } else {
    left = Math.max(PAD + tw / 2, Math.min(px, hostW - PAD - tw / 2));
  }
  // Y positioning: above by default (12px gap), below if would go above top
  const py = p[1] * sc;
  let top;
  if (py - 12 - th < 0) {
    top = py + 14;
  } else {
    top = py - 12 - th;
  }
  tip.style.setProperty('left', left + 'px');
  tip.style.setProperty('top', top + 'px');
  if (announce) $('[data-chart-live]').textContent = parts.map(t => t.replace(/<[^>]+>/g, '')).join('. ');
}
function hide() {
  if (!host) return;
  const cross = host.querySelector('.cross'), tip = host.querySelector('.tip');
  if (cross) cross.setAttribute('visibility', 'hidden');
  if (tip) tip.hidden = true;
}
function wireChart() {
  if (wired) return;
  wired = true;
  const idx = e => {
    const r = host.getBoundingClientRect(), x = (e.clientX - r.left) * geo.W / r.width;
    return Math.max(0, Math.min(geo.N - 1, Math.round((x - geo.pad.l) / ((geo.W - geo.pad.l - geo.pad.r - 14) / geo.N))));
  };
  host.addEventListener('pointermove', e => { if (geo && e.pointerType === 'mouse') show(idx(e), false); });
  host.addEventListener('pointerdown', e => { if (geo) show(idx(e), false); });
  host.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
  host.addEventListener('blur', hide);
  host.addEventListener('keydown', e => {
    if (!geo) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      show(Math.max(0, Math.min(geo.N - 1, (cur < 0 ? geo.N - 1 : cur) + (e.key === 'ArrowRight' ? 1 : -1))), true);
    } else if (e.key === 'Escape') hide();
  });
  document.addEventListener('pointerdown', e => { if (!host.contains(e.target)) hide(); });
  let lastW = host.clientWidth, t = 0;
  if ('ResizeObserver' in window) {
    new ResizeObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => { if (geo && Math.abs(host.clientWidth - geo.W) > 8 && host.clientWidth !== lastW) { lastW = host.clientWidth; const step = Number(host.dataset.step) || 1; renderBankroll(step); } measureStage(); }, 100);
    }).observe(host);
  }
}

function measureStage() {
  const sc = $('[data-bscrolly]'), stage = sc && sc.querySelector('.bstage');
  if (stage) sc.style.setProperty('--stageH', stage.offsetHeight + 'px');
}

function setStep(n) {
  // Check if domain group changes (1-2 ↔ 3)
  const oldGroup = host.dataset.step ? (Number(host.dataset.step) === 3 ? 3 : 1) : 1;
  const newGroup = n === 3 ? 3 : 1;

  host.dataset.step = String(n);
  document.querySelectorAll('.bstep').forEach(s => s.classList.toggle('act', s.dataset.bs === String(n)));
  $('[data-bstep-k]').textContent = n + ' of 3';
  $('[data-bstep-t]').textContent = n === 3 && store.isPast ? 'Bankroll · that night' : TITLES[n - 1];

  // Re-render chart if domain group changes
  if (oldGroup !== newGroup && geo) {
    renderBankroll(n);
  }

  host.classList.remove('pop');
  if (n === 3) { void host.offsetWidth; host.classList.add('pop'); }
}
function wireSteps() {
  if (stepsWired) return;
  stepsWired = true;
  setStep(1);
  if (!('IntersectionObserver' in window)) return;
  $('[data-bscrolly]').classList.add('drive');
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) setStep(Number(e.target.dataset.bs)); }), { rootMargin: '-50% 0px -50% 0px' });
  document.querySelectorAll('.bstep').forEach(s => io.observe(s));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measureStage);
}

// ---------- W/L strip ----------
function renderWL() {
  const card = $('[data-wl-card]'), list = (perf.recent_bets || []).filter(x => x === 'W' || x === 'L').slice(-33);
  const h3 = card.querySelector('h3'), sub = card.querySelector('.sub');
  let strip = card.querySelector('[data-testid=wl]');
  if (!list.length) {
    h3.textContent = 'Last bets'; sub.textContent = 'No settled bets yet.';
    if (strip) strip.remove();
    return;
  }
  const n = list.length, w = list.filter(x => x === 'W').length, l = n - w;
  let streak = 1; while (streak < n && list[n - 1 - streak] === list[n - 1]) streak++;
  const streakTxt = streak + ' ' + (list[n - 1] === 'W' ? (streak === 1 ? 'win' : 'wins') : (streak === 1 ? 'loss' : 'losses'));
  h3.textContent = 'Last ' + n + ' ' + (n === 1 ? 'bet' : 'bets');
  strip.textContent = '';
  list.forEach((r, i) => { const el = document.createElement('i'); el.className = r; el.textContent = r; el.style.setProperty('--k', String(i)); strip.append(el); });
  strip.setAttribute('aria-label', 'Last ' + n + ' bets, oldest first: ' + w + ' wins, ' + l + ' losses. Latest streak: ' + streakTxt + '. Sequence: ' + list.join(' ') + '.');
  if (motionOn()) watch(strip, el => el.classList.remove('pre'), { threshold: 0.6 });
  else strip.classList.remove('pre');
}

// ---------- public ----------
export function mountSeason(p) {
  perf = p;
  host = $('[data-testid=bankroll]');
  const err = $('[data-season-error]'); if (err) err.remove();
  $('[data-bscrolly]').hidden = false;
  renderSeasonBoard();
  wireChart();
  renderBankroll(1);
  wireSteps();
  renderWL();
}

export function seasonOnBatch(batch) {
  if (!perf) return;
  if (batch.some(c => ['slate', 'tip', 'score', 'final', 'clock'].includes(c.type))) {
    const step = Number(host.dataset.step) || 1;
    renderBankroll(step);
  }
}

function errorCard(after, text, retry, attr) {
  let el = document.querySelector('[' + attr + ']');
  if (!el) { el = document.createElement('div'); el.className = 'card'; el.setAttribute(attr, ''); after.after(el); }
  el.textContent = '';
  const p = document.createElement('p'); p.textContent = text;
  const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Retry';
  let tries = 0;
  const go = () => retry().catch(() => {});
  b.addEventListener('click', go);
  el.append(p, b);
  [5000, 15000, 30000].forEach(ms => setTimeout(() => { if (el.isConnected && tries++ < 3) go(); }, ms));
  return el;
}
export function seasonError(retry) {
  renderBoard($('[data-testid=season-board]'), ['Bankroll', 'Since start', 'ROI', 'Bets W–L', 'Pick accuracy', 'Max drawdown'].map(l => ({ label: l, value: '—' })));
  $('[data-bscrolly]').hidden = true;
  errorCard($('[data-bscrolly]'), "Can't load the season chart.", retry, 'data-season-error');
  const card = $('[data-wl-card]');
  card.querySelector('.sub').textContent = "Can't load recent bets.";
  const strip = card.querySelector('[data-testid=wl]'); if (strip) strip.hidden = true;
}

let calW = 0;
export function mountModelCard(m) {
  model = m;
  const err = $('[data-model-error]'); if (err) err.remove();
  const ch = $('[data-testid=calib]');
  ch.hidden = false;
  const draw = () => { calW = renderCalibration(ch, m.calibration, { variant: 'card' }).W; };
  draw();
  if (motionOn()) watch(ch, el => el.classList.remove('pre'), { threshold: 0.5 }); else ch.classList.remove('pre');
  if ('ResizeObserver' in window) {
    let t = 0;
    new ResizeObserver(() => { clearTimeout(t); t = setTimeout(() => { if (calW && Math.abs(Math.max(260, ch.clientWidth) - calW) > 8) draw(); }, 100); }).observe(ch);
  }
  const T = m.test || {}, live = m.season_live || {};
  const rows = [
    ['Live model', m.production_model ? modelLabel(m.production_model) : '—'],
    ['Retrained', m.trained_at ? new Date(m.trained_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' }) : '—'],
    ['This season', live.accuracy != null ? fmt.pct(live.accuracy) + ' of ' + (live.picks ?? 0) : '—', 'sep'],
    ['Test set', T.accuracy != null ? fmt.pct(T.accuracy) + ' of ' + (T.games != null ? T.games.toLocaleString('en-US') : '—') : '—'],
    ['Always pick home', T.baseline_home_win_rate != null ? fmt.pct(T.baseline_home_win_rate) : '—'],
    ['Brier score', T.brier != null ? T.brier.toFixed(3) : '—']
  ];
  // Filter out empty rows: "Live model" when production_model is null, "Retrained" when trained_at is null/invalid
  const filteredRows = rows.filter((row, i) => {
    const label = row[0];
    if (label === 'Live model' && !m.production_model) return false;
    if (label === 'Retrained' && (!m.trained_at || Number.isNaN(Date.parse(m.trained_at)))) return false;
    return true;
  });
  // If any rows precede "This season", apply sep class to the first "This season" row
  const thisSeasonIdx = filteredRows.findIndex(r => r[0] === 'This season');
  if (thisSeasonIdx > 0 && !filteredRows[thisSeasonIdx][2]) {
    filteredRows[thisSeasonIdx] = [filteredRows[thisSeasonIdx][0], filteredRows[thisSeasonIdx][1], 'sep'];
  } else if (thisSeasonIdx === 0 && filteredRows[thisSeasonIdx][2] === 'sep') {
    // Remove sep class if it's the first row
    filteredRows[thisSeasonIdx] = [filteredRows[thisSeasonIdx][0], filteredRows[thisSeasonIdx][1]];
  }
  const dl = $('[data-testid=mfacts]');
  dl.textContent = '';
  filteredRows.forEach(([a, b, cls]) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = a; dd.textContent = b;
    if (cls) { dt.className = cls; dd.className = cls; }
    dl.append(dt, dd);
  });
}
export function modelError(retry) {
  const ch = $('[data-testid=calib]');
  ch.hidden = true;
  errorCard(ch, "Can't load model facts.", retry, 'data-model-error');
}
