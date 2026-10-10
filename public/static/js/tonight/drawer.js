// Ticket drawer ("Back of ticket"): stake math, prices at bet time and a head-to-head tale of the tape.
// The panel is built with DOM APIs and textContent: no API string is ever parsed as HTML. Spec: components/ticket-drawer.md.
import { on, game, pickSide } from '../state.js';
import { api } from '../api.js';
import { fmt, NDASH, wl, modelLabel } from '../format.js';
import { logo } from '../logo.js';
import { reduceMotion } from '../reveal.js';

const HASH_RE = /^#g(\d{10})$/;
const TAPE = [   // [label, field, decimals, [lo, hi]]
  ['Elo', 'elo', 0, [1300, 1750]], ['Rest days', 'rest_days', 0, [0, 4]], ['Points', 'roll_pts', 1, [100, 125]], ['FG%', 'roll_fg_pct', 'pct', [0.42, 0.52]],
  ['Rebounds', 'roll_reb', 1, [38, 52]], ['Assists', 'roll_ast', 1, [20, 32]], ['Turnovers', 'roll_tov', 1, [10, 18]], ['Stl+blk', 'roll_stocks', 1, [10, 20]]
];
const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

const detailCache = new Map();    // game id -> GAME_DETAIL (page lifetime)
const detailInflight = new Map(); // game id -> Promise
let active = null;                // { id, opener, token } while open
let hideTimer = 0;
let token = 0;
let ready = false;

const $drawer = () => document.querySelector('.drawer');
const $panel = () => document.querySelector('.drawer .panel');

// ---------- tiny DOM helpers (text only) ----------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
function append(parent, ...kids) { for (const k of kids) if (k != null) parent.append(k); return parent; }
const dash = v => (v == null ? '—' : v);

function closeGlyph() {
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg'), path = document.createElementNS(NS, 'path');
  for (const [k, v] of [['aria-hidden', 'true'], ['focusable', 'false'], ['width', '14'], ['height', '14'], ['viewBox', '0 0 14 14']]) svg.setAttribute(k, v);
  for (const [k, v] of [['d', 'M2 2l10 10M12 2L2 12'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '2']]) path.setAttribute(k, v);
  svg.append(path);
  return svg;
}

function focusables(root) {
  return Array.from(root.querySelectorAll(FOCUSABLE)).filter(n => n.offsetParent !== null || n === document.activeElement);
}

// ---------- text pieces ----------
// The meta line, built from nodes so records, the time and the score never break mid-number.
function setMeta(p, g) {
  p.textContent = '';
  const add = (text) => p.append(document.createTextNode(text));
  const addNW = (text) => p.append(el('span', 'nw', text));

  // Away team name
  const awayName = (g.away && (g.away.name || g.away.tricode)) || '';
  add(awayName);
  if (g.away && g.away.record) addNW(' (' + wl(g.away.record) + ')');
  add(' at ');

  // Home team name
  const homeName = (g.home && (g.home.name || g.home.tricode)) || '';
  add(homeName);
  if (g.home && g.home.record) addNW(' (' + wl(g.home.record) + ')');
  add(' · ');

  // Time
  addNW(fmt.time(g.tip_time_utc) + ' ET');
  add(' · ');

  // State and score
  const A = g.away.tricode, H = g.home.tricode, sc = () => dash(g.as) + NDASH + dash(g.hs);
  if (g.state === 'live') {
    add('Live' + (g.clock ? ' ' + g.clock : '') + ', ');
    add(A + ' ');
    addNW(sc());
    add(' ' + H);
  } else if (g.state === 'final') {
    add('Final ');
    add(A + ' ');
    addNW(sc());
    add(' ' + H);
  } else if (g.state === 'postponed') {
    add('Postponed');
  } else if (g.state === 'void') {
    add('Void');
  } else {
    add('Not started');
  }
}
function fineText(d) {
  const model = d && d.model_name, at = d && d.predicted_at;
  const modelDisplay = model ? modelLabel(model) : null;
  if (at) return 'Predicted ' + fmt.time(at) + ' ET' + (modelDisplay ? ' by ' + modelDisplay : '') + '. Paper money only.';
  return modelDisplay ? 'Predicted by ' + modelDisplay + '. Paper money only.' : 'Paper money only.';
}

// ---------- sections ----------
function header(g) {
  const ph = el('div', 'ph'), left = el('div');
  const kk = el('p', 'kk', 'Back of ticket · No. ' + String(g.game_id).slice(-4));
  const h2 = el('h2', 'd-title');
  h2.id = 'd-title';
  append(h2, logo(g.away.tricode, 'd-logo', 42), document.createTextNode(g.away.tricode + ' '), el('span', null, 'at'),
    document.createTextNode(' '), logo(g.home.tricode, 'd-logo', 42), document.createTextNode(g.home.tricode));
  const btn = el('button', 'btn');
  btn.type = 'button';
  btn.setAttribute('data-close', '');
  btn.setAttribute('data-autofocus', '');
  btn.setAttribute('aria-label', 'Close details');
  btn.append(closeGlyph());
  append(left, kk, h2);
  return append(ph, left, btn);
}

function mathSection(g) {
  const dl = el('dl', 'math');
  const row = (dt, dd, tot) => {
    const a = el('dt', tot ? 'tot' : null, dt), b = el('dd', tot ? 'tot' : null, dd);
    dl.append(a, b);
  };
  const why = text => dl.append(el('dd', 'why', text));
  const b = g.bet, pick = g.pick || (b && b.side) || null, o = g.odds;
  const modelLabel = pick ? 'Model: ' + pick + ' wins' : 'Model';
  if (!b) {
    const skip = g.skip_reason;
    row(modelLabel, skip === 'missing_data' ? '—' : fmt.pct(g.pick_prob));
    row('Market implies', skip === 'no_odds' || skip === 'missing_data' ? '—' : fmt.pct(g.implied_prob));
    row('Edge', skip === 'no_odds' || skip === 'missing_data' ? '—' : fmt.pts(g.edge) + ' pts', true);
    why(skip === 'no_odds' ? 'No bet. No odds were posted for this game.'
      : skip === 'missing_data' ? 'No bet. Team data was missing for this game.'
      : "No bet. The model only bets when its chance is above the market's.");
    return dl;
  }
  const frac = b.kelly_fraction, kf = b.kelly_full, br = b.bankroll_at_bet;
  row(modelLabel, fmt.pct(g.pick_prob));
  row('Market: ' + (o == null ? '—' : fmt.odds(o)) + ' implies', o == null ? '—' : fmt.pct(g.implied_prob));
  if (o != null) {
    const n = Math.abs(o);
    why(o > 0 ? '100 ÷ (' + n + ' + 100)' : n + ' ÷ (' + n + ' + 100)');
  }
  row('Edge', g.edge == null ? '—' : fmt.pts(g.edge) + ' pts', true);
  row('Full Kelly', fmt.pct(kf));
  const fracLabel = frac == null || frac === 0.25 ? '× quarter-Kelly' : '× ' + Math.round(frac * 10000) / 100 + '% Kelly';
  row(fracLabel, kf == null || frac == null ? '—' : fmt.pct(kf * frac));
  row('Cap per bet', '5.0%');
  row('Bankroll at bet', fmt.money(br));
  row('Stake', fmt.money(b.amount), true);
  const pays = o == null ? '—' : fmt.money(fmt.payout(b.amount, o));
  if (g.state === 'void' || g.state === 'postponed') {
    why('Game ' + g.state + '. The ' + fmt.money(b.amount) + ' stake is returned.');
  } else if (kf == null || frac == null || br == null) {
    why('Stake ' + fmt.money(b.amount) + '. Pays ' + pays + ' if ' + pick + ' wins.');
  } else {
    why(fmt.pct(Math.min(0.05, kf * frac)) + ' of ' + fmt.money(br) + '. Pays ' + pays + ' if ' + pick + ' wins.');
  }
  return dl;
}

function pricesNodes(g, grid) {
  if (!grid || !Array.isArray(grid.books) || !grid.books.length) {
    return [el('p', 'd-legend', "Book prices weren't saved for this game.")];
  }
  const wrap = el('div', 'books-wrap'), table = el('table', 'books');
  const thead = el('thead'), hr = el('tr');
  for (const t of ['Book', g.away.tricode, g.home.tricode]) {
    const th = el('th', null, t);
    th.scope = 'col';
    hr.append(th);
  }
  thead.append(hr);
  const tbody = el('tbody');
  const takenSide = g.bet ? pickSide(g) : null;
  grid.books.forEach((name, i) => {
    const tr = el('tr'), th = el('th', null, name);
    th.scope = 'row';
    tr.append(th);
    for (const side of ['away', 'home']) {
      const td = el('td', null, fmt.odds((grid[side] || [])[i]));
      if (takenSide === side && g.bookmaker === name) td.className = 'taken';
      else if (grid['best_' + side + '_idx'] === i) td.className = 'best';
      tr.append(td);
    }
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  return [wrap, el('p', 'd-legend', 'Filled: price taken. Underlined: best price on that side.')];
}

// ---------- tale of the tape ----------
export function tapeWidth(field, v) {
  // Find the domain for this field
  const tapeEntry = TAPE.find(t => t[1] === field);
  if (!tapeEntry || !tapeEntry[3]) return 0;
  const [lo, hi] = tapeEntry[3];
  // Clamp the value to the domain and normalize to [0, 1]
  const clamped = Math.min(Math.max(v, lo), hi);
  const normalized = (clamped - lo) / (hi - lo);
  return normalized * 100;
}

function betterSide(field, a, h, better) {
  const given = better && better[field];
  if (given === 'home' || given === 'away') return given;
  if (a == null || h == null || a === h) return null;
  const homeHigher = h > a;
  if (field === 'roll_tov') return homeHigher ? 'away' : 'home';
  return homeHigher ? 'home' : 'away';
}
function tapeRows(tape) {
  const rows = [];
  if (!tape || !tape.away || !tape.home) return rows;
  for (const [label, field, dec] of TAPE) {
    const a = tape.away[field], h = tape.home[field];
    if (a == null || h == null) continue;
    const better = betterSide(field, a, h, tape.better);
    const show = v => (dec === 'pct' ? (v * 100).toFixed(1) + '%' : Number(v).toFixed(dec));
    const width = v => Number(tapeWidth(field, v).toFixed(1)) + '%';
    const value = (v, side, cls) => {
      const s = el('span', cls);
      if (better === side) s.append(el('b', null, show(v))); else s.textContent = show(v);
      return s;
    };
    const bar = (v, side, cls) => {
      const b = el('span', 'b ' + cls + (better === side ? ' better' : '')), i = document.createElement('i');
      b.append(i);
      i.style.setProperty('width', width(v));
      return b;
    };
    const tt = el('div', 'tt');
    append(tt, value(a, 'away', 'v'), bar(a, 'away', 'l'), el('span', 'lb', label), bar(h, 'home', 'r'), value(h, 'home', 'v r'));
    rows.push(tt);
  }
  return rows;
}

function setTapeLoading(panel) {
  const host = panel.querySelector('[data-tape]');
  host.replaceChildren(el('p', 'd-legend', 'Loading team stats…'));
  panel.querySelector('[data-key]').hidden = true;
}
function setTapeError(panel, id) {
  const host = panel.querySelector('[data-tape]');
  const retry = el('button', 'btn', 'Retry');
  retry.type = 'button';
  retry.addEventListener('click', () => {
    const hadFocus = document.activeElement === retry;
    setTapeLoading(panel);
    if (hadFocus) { const c = panel.querySelector('[data-autofocus]'); if (c) c.focus(); }
    fetchInto(id, active && active.token);
  });
  host.replaceChildren(el('p', 'd-legend', "Couldn't load team stats."), retry);
  panel.querySelector('[data-key]').hidden = true;
}
function fillDetail(panel, g, d) {
  const host = panel.querySelector('[data-tape]'), rows = tapeRows(d && d.tape);
  if (rows.length) host.replaceChildren(...rows);
  else host.replaceChildren(el('p', 'd-legend', 'No team stats for this game.'));
  panel.querySelector('[data-key]').hidden = !rows.length;
  panel.querySelector('[data-fine]').textContent = fineText(d);
  const hasGrid = g.book_grid && Array.isArray(g.book_grid.books) && g.book_grid.books.length;
  if (!hasGrid && d && d.game && d.game.book_grid) panel.querySelector('[data-prices]').replaceChildren(...pricesNodes(g, d.game.book_grid));
}

function loadDetail(id) {
  if (detailCache.has(id)) return Promise.resolve(detailCache.get(id));
  if (detailInflight.has(id)) return detailInflight.get(id);
  const p = api.gameDetail(id).then(d => { detailCache.set(id, d); detailInflight.delete(id); return d; },
    e => { detailInflight.delete(id); throw e; });
  detailInflight.set(id, p);
  return p;
}
function fetchInto(id, tk) {
  loadDetail(id).then(d => {
    if (!active || active.id !== id || active.token !== tk) return;
    const g = game(id), panel = $panel();
    if (g && panel) fillDetail(panel, g, d);
  }, () => {
    if (!active || active.id !== id || active.token !== tk) return;
    const panel = $panel();
    if (panel) setTapeError(panel, id);
  });
}

// ---------- open / close ----------
function buildPanel(g) {
  const panel = $panel();
  const tapeHost = el('div');
  tapeHost.setAttribute('data-tape', '');
  const prices = el('div');
  prices.setAttribute('data-prices', '');
  prices.append(...pricesNodes(g, g.book_grid));
  const meta = el('p', 'meta');
  meta.setAttribute('data-meta', '');
  setMeta(meta, g);
  const key = el('p', 'd-legend', 'Teal marks the better side. Fewer turnovers is better.');
  key.setAttribute('data-key', '');
  const fine = el('p', 'fine', 'Paper money only.');
  fine.setAttribute('data-fine', '');
  panel.replaceChildren(header(g), meta,
    el('h3', null, 'How the stake was set'), mathSection(g),
    el('h3', null, 'Prices at bet time'), prices,
    el('h3', null, 'Tale of the tape · last 10 · ' + g.away.tricode + ' left, ' + g.home.tricode + ' right'), tapeHost, key, fine);
  panel.scrollTop = 0;
  return panel;
}

function setInert(on_) {
  const wrap = document.querySelector('.wrap');
  if (wrap) wrap.inert = on_;
}

export function openDetail(gameId, opener) {
  const g = game(gameId), drawer = $drawer();
  if (!g || !drawer || !$panel()) return;
  const wasOpen = !!active;
  clearTimeout(hideTimer);
  const prevOpener = active ? active.opener : null;
  const from = opener || prevOpener || (document.activeElement && document.activeElement !== document.body ? document.activeElement : null);
  const tk = ++token;
  active = { id: gameId, opener: from, token: tk };
  const panel = buildPanel(g);
  const cached = detailCache.get(gameId);
  if (cached) fillDetail(panel, g, cached);
  else { setTapeLoading(panel); fetchInto(gameId, tk); }
  if (location.hash !== '#g' + gameId) history.replaceState(null, '', location.pathname + location.search + '#g' + gameId);
  drawer.hidden = false;
  void drawer.offsetWidth;                  // force a reflow so the slide-in (T11) runs from the closed position
  drawer.setAttribute('data-open', '');
  document.documentElement.classList.add('drawer-open');
  setInert(true);
  const focusClose = () => { const c = panel.querySelector('[data-autofocus]') || focusables(panel)[0]; if (c) c.focus(); };
  if (wasOpen) focusClose();
  else requestAnimationFrame(focusClose);
}

function returnFocus(a) {
  let t = a.opener && a.opener.isConnected ? a.opener : null;
  if (t && t.offsetParent === null && getComputedStyle(t).position !== 'fixed') t = null;
  if (!t) t = document.querySelector('.ticket[data-id="' + a.id + '"] .ticket__hit') || document.querySelector('.ticket__hit');
  if (!t) t = document.querySelector('.gl__hit') || document.querySelector('.wrap a[href], .wrap button');
  if (t) t.focus();
}

export function closeDrawer() {
  const drawer = $drawer();
  if (!active || !drawer) return;
  const a = active;
  active = null;
  drawer.removeAttribute('data-open');
  document.documentElement.classList.remove('drawer-open');
  setInert(false);
  clearTimeout(hideTimer);
  if (reduceMotion()) drawer.hidden = true;
  else hideTimer = setTimeout(() => { drawer.hidden = true; }, 260);
  if (location.hash.startsWith('#g')) history.replaceState(null, '', location.pathname + location.search);
  returnFocus(a);
}

export function openFromHash() {
  const m = HASH_RE.exec(location.hash);
  if (!m) return;
  if (game(m[1])) { if (!active || active.id !== m[1]) openDetail(m[1], null); }
  else history.replaceState(null, '', location.pathname + location.search);
}

function onHashChange() {
  const m = HASH_RE.exec(location.hash);
  if (m) {
    if (game(m[1]) && (!active || active.id !== m[1])) openDetail(m[1], null);
  } else if (active) closeDrawer();
}

function onKeydown(e) {
  if (!active) return;
  if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); return; }
  if (e.key !== 'Tab') return;
  const panel = $panel(), list = focusables(panel);
  if (!list.length) { e.preventDefault(); return; }
  const first = list[0], last = list[list.length - 1], cur = document.activeElement;
  if (!panel.contains(cur)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
  else if (e.shiftKey && cur === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
}

function onBatch(changes) {
  if (!active) return;
  for (const c of changes) {
    if (c.id === active.id && (c.type === 'tip' || c.type === 'score' || c.type === 'final' || c.type === 'clock')) {
      const g = game(active.id), m = document.querySelector('.drawer [data-meta]');
      if (g && m) setMeta(m, g);
      return;
    }
  }
}

export function initDrawer() {
  if (ready) return;
  ready = true;
  document.addEventListener('keydown', onKeydown);
  document.addEventListener('click', e => {
    if (active && e.target.closest && e.target.closest('[data-close]')) closeDrawer();
  });
  window.addEventListener('hashchange', onHashChange);
  on(onBatch);
}
