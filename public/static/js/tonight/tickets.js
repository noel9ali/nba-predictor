// Paper tickets: one printed bet slip per game, the grid that holds them, the stamp that lands when
// a game is over, and the in-place live updates (band, scores, stamp). All API text is escaped
// before it enters an HTML string; the only style writes are --d (slide-in delay) via CSSOM.
import {
  store, visible, game, on, stamped, revealed, pickSide, leader, result, pl, marginLabel, pickMargin, isStampState, FEED_COPY
} from '../state.js';
import { fmt, esc, wl, TRICODE } from '../format.js';
import { logo } from '../logo.js';
import { watch, motionOn, hasIO, replay } from '../reveal.js';
import { updateToolbar, showAllGames } from './toolbar.js';

const gridEl = () => document.querySelector('[data-testid="grid"]');
const findTicket = (grid, id) => [...grid.children].find(c => c.dataset && c.dataset.id === id) || null;
const pressedFilter = () => document.querySelector('[data-testid="filters"] [aria-pressed="true"]');

// ---------- stamp observer (T6) ----------
let stampIO = null, stampIOMade = false;
function stampObserver() {
  if (!stampIOMade) {
    stampIOMade = true;
    if (motionOn() && hasIO()) {
      stampIO = new IntersectionObserver(entries => entries.forEach(e => { if (e.isIntersecting) landStamp(e.target); }),
        { rootMargin: '0px 0px -30% 0px', threshold: 0.5 });
    }
  }
  return stampIO;
}

export function landStamp(t) {
  const s = t.querySelector('.stamp.waiting');
  if (!s) return;
  s.classList.remove('waiting');
  s.classList.add('in');
  stamped.add(t.dataset.id);
  replay(t, 'thunk');   // T7
}

// ---------- pure builders ----------
const money = fmt.money;

// What the stamp says for a game, or null when it has none (not over, or no result to print).
function stampInfo(g) {
  if (!isStampState(g)) return null;
  const r = result(g), b = g.bet;
  if (r === 'void') return { cls: 'void', word: 'Void', small: b ? money(b.amount) + ' returned' : 'No bet', label: 'Void' };
  if (r !== 'hit' && r !== 'miss') return null;
  const hit = r === 'hit';
  if (b) {
    const p = money(pl(g), true), word = hit ? 'Cashed' : 'Lost';
    return { cls: hit ? 'cash' : 'lost', word, small: p + (g.official ? '' : ' · unofficial'), label: word + ' ' + p };
  }
  const word = 'Pick ' + (hit ? 'right' : 'wrong');
  return { cls: 'pass', word, small: 'No bet', label: word + ', no bet' };
}

function stampHTML(g, info) {
  if (!info) return '';
  const waiting = stampObserver() && !stamped.has(g.game_id) ? ' waiting' : '';
  return '<div class="stamp ' + info.cls + waiting + '" aria-hidden="true"><span class="ink">' + esc(info.word) +
    '<small>' + esc(info.small) + '</small></span></div>';
}

function ariaLabel(g, info) {
  const parts = [];

  // 1. Matchup + time/status
  const matchup = g.away.tricode + ' at ' + g.home.tricode;
  let timeStatus;
  if (g.state === 'scheduled') {
    timeStatus = g.tip_time_utc ? fmt.time(g.tip_time_utc) + ' ET' : 'Time TBD';
  } else if (g.state === 'live') {
    timeStatus = 'live' + (g.clock ? ', ' + g.clock : '');
  } else if (g.state === 'final') {
    timeStatus = (g.as != null && g.hs != null) ? 'final ' + g.as + '–' + g.hs : 'final';
  } else if (g.state === 'postponed') {
    timeStatus = 'postponed';
  } else if (g.state === 'void') {
    timeStatus = 'void';
  }
  parts.push(matchup + ', ' + timeStatus + '.');

  // 2. Pick/bet
  if (g.pick == null && !g.bet && !g.skip_reason) {
    // Pick pending
    parts.push('Pick pending.');
  } else if (g.bet && g.odds != null && g.bet.amount != null) {
    // Bet on [team], [amount] at [odds]
    parts.push('Bet on ' + g.pick + ', ' + fmt.money(g.bet.amount) + ' at ' + fmt.odds(g.odds) + '.');
  } else if (g.pick) {
    // Pick [team], no bet
    parts.push('Pick ' + g.pick + ', no bet.');
  }

  // 3. Model vs market when both known
  if (g.pick_prob != null && g.implied_prob != null) {
    parts.push('Model ' + fmt.pct(g.pick_prob) + ' vs market ' + fmt.pct(g.implied_prob) + '.');
  }

  // 4. Status/result when known
  if (g.state === 'live' && g.pick) {
    const m = pickMargin(g);
    if (m != null) {
      parts.push(marginLabel(g) + '.');
    }
  } else if (info) {
    let label = info.label;
    if (g.bet && !g.official) {
      label += ', unofficial';
    }
    parts.push(label + '.');
  }

  // 5. Open details.
  parts.push('Open details.');

  return parts.join(' ');
}

const payoutOf = g => (g.bet && g.bet.amount != null && g.odds != null ? fmt.payout(g.bet.amount, g.odds) : null);

function teamRow(g, side) {
  const t = g[side] || {}, ps = pickSide(g), isPick = ps === side, ld = leader(g);
  const sc = side === 'home' ? g.hs : g.as;
  let score;
  if (g.state === 'scheduled') score = '<span class="score pre-tip">' + esc(fmt.pct(t.win_prob, 0)) + '</span>';
  else score = '<span class="score' + (ld && ld !== side ? ' trail' : '') + '" data-score="' + esc(g.game_id + '-' + side) + '">' + (sc == null ? '—' : esc(sc)) + '</span>';
  const tag = isPick ? '<span class="bet-tag' + (g.bet ? '' : ' nobet') + '">' + (g.bet ? 'Bet on' : 'Pick') + '</span>' : '';
  let name = '';
  if (t.name) {
    name = '<span class="tname">';
    name += '<span class="tn-n">' + esc(t.name) + '</span>';
    if (t.record) name += '<span class="tn-r"> · ' + esc(wl(t.record)) + '</span>';
    name += '</span>';
  }
  const img = TRICODE.test(String(t.tricode || '')) ? '<i data-logo="' + esc(t.tricode) + '"></i>' : '';
  return '<div class="team ' + (isPick ? 'is-pick' : 'not-pick') + '">' + img + '<span class="t-tri">' + esc(t.tricode) + '</span>' + tag + name + '</div>' + score;
}

function stubHTML(g, no) {
  const b = g.bet, pending = g.pick == null && !b && !g.skip_reason;
  let who, pick, odds, stake, win;
  if (pending) { who = 'Pick pending'; pick = '—'; odds = '—'; stake = '—'; win = '—'; }
  else {
    who = b ? 'Bet on' : 'Pick<span class="who-sep"> · </span><span class="who-2">no bet</span>';
    pick = g.pick == null ? '—' : esc(g.pick);
    odds = fmt.odds(g.odds);
    stake = b ? money(b.amount) : '$0.00';
    win = b ? money(payoutOf(g)) : '—';
  }
  return '<div class="stub"><span class="who">' + who + '<b class="stub-pick">' + pick + '</b></span><span>Odds<b>' + esc(odds) +
    '</b></span><span>Stake<b>' + esc(stake) + '</b></span><span>To win<b>' + esc(win) + '</b></span><span class="no">Ticket No. ' + no + '</span></div>';
}

function linesHTML(g) {
  const b = g.bet;
  if (b) {
    const edge = g.edge != null ? ' · <span class="edge">edge ' + esc(fmt.pts(g.edge)) + '</span>' : '';
    return '<dl class="lines"><dt>Moneyline</dt><dd><b>' + esc(g.pick) + ' ' + esc(fmt.odds(g.odds)) + '</b>' + (g.bookmaker ? ' · ' + esc(g.bookmaker) : '') +
      '</dd><dt>Risk</dt><dd>' + esc(money(b.amount)) + ' to win ' + esc(money(payoutOf(g))) +
      '</dd><dt>Model · market</dt><dd>' + esc(fmt.pct(g.pick_prob)) + ' vs ' + esc(fmt.pct(g.implied_prob)) + edge + '</dd></dl>';
  }
  if (g.pick == null && !g.skip_reason) {
    return '<dl class="lines"><dt>Pick</dt><dd>Pending</dd><dt>Status</dt><dd>Picks post about an hour before the first tip</dd></dl>';
  }
  const pick = g.pick == null ? '—' : '<b>' + esc(g.pick) + '</b>' + (g.pick_prob != null ? ' ' + esc(fmt.pct(g.pick_prob)) : '') +
    (g.odds != null ? ' at ' + esc(fmt.odds(g.odds)) : '');
  const why = g.skip_reason === 'no_odds' ? 'No odds posted'
    : g.skip_reason === 'missing_data' ? 'Team data missing'
    : (g.edge != null && g.edge <= 0) ? 'Edge ' + fmt.pts(g.edge) + ' pts, below zero'
    : 'No bet placed';
  return '<dl class="lines"><dt>Pick</dt><dd>' + pick + '</dd><dt>Pass</dt><dd>' + esc(why) + '</dd></dl>';
}

function statusHTML(g) {
  if (g.state === 'live') {
    if (store.feed.status === 'delayed' || store.feed.status === 'down') {
      return '<span class="st live">' + esc(store.feed.asOf ? FEED_COPY.delayed(store.feed.asOf) : 'Scores delayed') + '</span>';
    }
    return '<span class="st live">' + (g.clock ? 'Live · ' + esc(g.clock) : 'Live') + '</span>';
  }
  if (g.state === 'final') return '<span class="st">' + esc(g.clock || 'Final') + '</span>';
  if (g.state === 'postponed') return '<span class="st">Postponed</span>';
  if (g.state === 'void') return '<span class="st">Void</span>';
  return '<span class="st">' + (g.tip_time_utc ? esc(fmt.time(g.tip_time_utc)) + ' ET' : 'Time TBD') + '</span>';
}

function footHTML(g) {
  let left = '<span>' + esc(g.away.tricode) + ' at ' + esc(g.home.tricode) + '</span>';
  if (g.state === 'live' && g.pick) {
    const m = pickMargin(g);
    left = '<span' + (m > 0 ? ' class="ahead"' : m < 0 ? ' class="behind"' : '') + '>' + esc(marginLabel(g)) + '</span>';
  }
  return '<div class="foot">' + left + '<span class="more">Back of ticket ›</span></div>';
}

function ticketInner(g, info) {
  const no = esc(String(g.game_id).slice(-4));
  return stubHTML(g, no) + '<div class="ticket__body"><div class="band"><span>Paper ticket · No. ' + no + '</span>' + statusHTML(g) +
    '</div><div class="match">' + teamRow(g, 'away') + teamRow(g, 'home') + '</div>' + linesHTML(g) + footHTML(g) + '</div>' + stampHTML(g, info);
}

// Set .inner's markup, then swap each logo placeholder for a real <img>/chip node.
function fillInner(inner, g, info) {
  inner.innerHTML = ticketInner(g, info);
  inner.querySelectorAll('[data-logo]').forEach(p => p.replaceWith(logo(p.dataset.logo, 't-logo', 40)));
}

function createTicket(g, pre) {
  const info = stampInfo(g);
  const el = document.createElement('article');
  el.className = 'ticket' + (pre ? ' pre' : '') + (info ? ' is-final' : '');
  el.dataset.id = g.game_id;
  el.dataset.testid = 'ticket';
  const hit = document.createElement('button');
  hit.className = 'ticket__hit';
  hit.type = 'button';
  hit.setAttribute('aria-label', ariaLabel(g, info));
  const inner = document.createElement('div');
  inner.className = 'inner';
  fillInner(inner, g, info);
  if (info && !stampObserver()) stamped.add(g.game_id);   // no motion: the stamp renders landed
  el.append(hit, inner);
  return el;
}

// ---------- T5: slide in ----------
function colOf(t, grid) {
  const gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
  const shift = motionOn() && t.classList.contains('pre') ? 72 : 0;   // undo the -72px pre-state translate
  return Math.max(0, Math.round((t.getBoundingClientRect().left + shift - grid.getBoundingClientRect().left) / ((t.offsetWidth + gap) || 1)));
}
function reveal(t) {
  if (!t.isConnected) return;
  if (motionOn() && t.parentElement) t.style.setProperty('--d', (colOf(t, t.parentElement) * 140) + 'ms');
  t.classList.add('on');
  t.classList.remove('pre');
  revealed.add(t.dataset.id);
}

// ---------- grid ----------
const EMPTY_COPY = {
  bets: 'No bets tonight.', live: 'No live games right now.', upcoming: 'No upcoming games right now.',
  final: 'No final games yet.', all: 'No games to show.'
};
function emptyBlock() {
  const d = document.createElement('div');
  d.className = 'empty';
  d.append(document.createTextNode(EMPTY_COPY[store.filter] || EMPTY_COPY.all), document.createElement('br'));
  const b = document.createElement('button');
  b.className = 'btn';
  b.type = 'button';
  b.dataset.f = 'all';
  b.textContent = 'Show all games';
  d.append(b);
  return d;
}

export function renderGrid({ replay: doReplay = false } = {}) {
  const grid = gridEl();
  if (!grid) return;
  const hadFocus = grid.contains(document.activeElement);
  const focusId = hadFocus && document.activeElement.closest('.ticket') ? document.activeElement.closest('.ticket').dataset.id : null;
  if (doReplay) revealed.clear();
  const io = stampObserver();
  if (io) io.disconnect();
  grid.textContent = '';
  const list = visible();
  if (!list.length) grid.append(emptyBlock());
  for (const g of list) {
    const seen = revealed.has(g.game_id);
    const el = createTicket(g, !seen);
    grid.append(el);
    if (!seen) watch(el, reveal, { threshold: 0.15 });
    if (io) io.observe(el);
  }
  if (hadFocus && !grid.contains(document.activeElement)) {
    const t = focusId && findTicket(grid, focusId);
    const target = (t && t.querySelector('.ticket__hit')) || pressedFilter();
    if (target) target.focus();
  }
}

export function updateTicket(id) {
  const grid = gridEl(), g = game(id);
  if (!grid || !g) return;
  const el = findTicket(grid, id);
  if (!el) return;
  const info = stampInfo(g);
  el.classList.toggle('is-final', !!info);
  fillInner(el.querySelector('.inner'), g, info);
  el.querySelector('.ticket__hit').setAttribute('aria-label', ariaLabel(g, info));
  if (!info) return;
  const io = stampObserver();
  if (!io) { stamped.add(id); return; }
  if (!stamped.has(id) && el.querySelector('.stamp.waiting')) {
    const r = el.getBoundingClientRect();
    if (r.top < innerHeight * 0.7 && r.bottom > 0) landStamp(el);   // on screen: stamp now; else the IO lands it on scroll
  }
}

// Per-batch live logic: re-render when the visible set changed, else patch tickets in place; then T8.
export function ticketsOnBatch(changes) {
  const grid = gridEl();
  if (!grid || !changes || !changes.length) return;
  updateToolbar();
  const want = visible().map(g => g.game_id);
  const have = [...grid.querySelectorAll('.ticket')].map(t => t.dataset.id);
  const reslate = changes.some(c => c.type === 'slate' && (c.refetch || c.late));
  if (reslate || want.length !== have.length || want.some((id, i) => id !== have[i])) {
    renderGrid({ replay: false });
  } else {
    const ids = new Set();
    for (const c of changes) {
      if (c.type === 'feed') store.games.forEach(g => { if (g.state === 'live') ids.add(g.game_id); });
      else if (c.id && ['tip', 'score', 'final', 'clock'].includes(c.type)) ids.add(c.id);
    }
    ids.forEach(updateTicket);
  }
  for (const c of changes) {
    if (c.type !== 'score') continue;
    const key = c.id + '-' + c.side;
    grid.querySelectorAll('[data-score]').forEach(el => { if (el.dataset.score === key) replay(el, 'bump'); });   // T8
  }
}

let wired = false;
export function initTickets({ onOpen } = {}) {
  const grid = gridEl();
  if (!grid || wired) return;
  wired = true;
  grid.addEventListener('click', e => {
    const t = e.target instanceof Element ? e.target : null;
    if (!t) return;
    const hit = t.closest('.ticket__hit');
    if (hit) {
      const tk = hit.closest('.ticket');
      if (tk && onOpen) onOpen(tk.dataset.id, hit);
      return;
    }
    const all = t.closest('.empty [data-f]');
    if (all) showAllGames();
  });
}

// Convenience for callers that want tickets wired to the store on their own.
export function bindTickets() { return on(ticketsOnBatch); }
