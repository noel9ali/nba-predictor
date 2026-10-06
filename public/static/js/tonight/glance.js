// The night at a glance: kicker, the h1 sentence, the six-cell board, and one mini court per game.
import { fmt, esc } from '../format.js';
import { renderBoard, signCls } from '../board.js';
import { glanceCourt, countUp } from '../court.js';
import { watch, motionOn } from '../reveal.js';
import { store, byTip, nextUp, pickSide, pickMargin, marginLabel, result, pl, now } from '../state.js';
import { sampleQuery } from '../api.js';

const $ = s => document.querySelector(s);
const populated = new Set();      // rows whose populate animation has played (T1–T4 never replay)
const NOBOARD = ['no_games', 'offseason', 'before_predictions', 'prediction_failed'];

const n = (txt, cls) => '<span class="n' + (cls ? ' ' + cls : '') + '">' + esc(txt) + '</span>';
const plural = (k, w) => k + ' ' + w + (k === 1 ? '' : 's');
const done = g => ['final', 'postponed', 'void'].includes(g.state);
const phaseOf = () => (store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase)) || null;

function setHTML(el, html) { if (el && el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; } }
function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }

// Server-settled night: every bet carries bet.result, or a past night with a recap.
function isOfficial() {
  if (store.isPast && store.slate && store.slate.recap) return true;
  const bets = store.games.filter(g => g.bet);
  return bets.length > 0 && bets.every(g => g.bet.result != null);
}

export function boardCells(s) {
  return [
    { label: 'At risk', value: fmt.money(s.staked) },
    { label: 'Settled', value: fmt.money(s.settled, true), cls: signCls(s.settled), testid: 'settled' },
    { label: 'If it ended now', value: fmt.money(s.ifEnded, true), cls: signCls(s.ifEnded) },
    { label: 'Live picks ahead', value: s.ahead + ' of ' + s.liveBets },
    { label: 'Bets W–L', value: s.betW + '–' + s.betL },
    { label: 'Picks W–L', value: s.pickW + '–' + s.pickL }
  ];
}

function sentence(s) {
  const phase = phaseOf();
  if (phase === 'no_games') return 'No games tonight';
  if (phase === 'offseason') return 'Offseason';
  if (phase === 'before_predictions') return 'Picks post about an hour before the first tip.';
  if (phase === 'prediction_failed') return "Tonight's picks didn't post.";
  const allDone = store.games.length > 0 && store.games.every(done);
  if (allDone) {
    if (s.bets > 0) {
      const off = isOfficial(), recap = store.slate && store.slate.recap;
      const rec = off && recap && recap.bets ? recap.bets.replace('-', '–') : s.betW + '–' + s.betL;
      const money = off && recap && recap.net_pl != null ? recap.net_pl : s.settled;
      return 'Night over. Bets went ' + n(rec) + ' for ' + n(fmt.money(money, true), signCls(money)) +
        (off ? '.' : ', unofficial until the 6 AM settle.');
    }
    return 'Night over. No bets tonight. Picks went ' + n(s.pickW + '–' + s.pickL) + '.';
  }
  if (s.bets === 0) return 'The model found no bets in ' + n(String(s.games)) + ' ' + (s.games === 1 ? 'game' : 'games') + ' tonight.';
  const nu = nextUp();
  if (!nu) return 'Every bet has tipped. If it ended now: ' + n(fmt.money(s.ifEnded, true), signCls(s.ifEnded)) + '.';
  const found = 'The model found ' + n(String(s.bets)) + ' ' + (s.bets === 1 ? 'bet' : 'bets') + ' in ' + n(String(s.games)) + ' ' + (s.games === 1 ? 'game' : 'games') + '.';
  if (nu.edge == null || nu.odds == null) return found;
  return found + ' Next up: ' + n(nu.pick + ' ' + fmt.odds(nu.odds)) + ' at ' + esc(fmt.time(nu.tip_time_utc)) + ', edge ' + n(fmt.pts(nu.edge), 'e') + '.';
}

function linkWithQuery(path, extra) {
  const hashAt = path.indexOf('#');
  const base = hashAt < 0 ? path : path.slice(0, hashAt), hash = hashAt < 0 ? '' : path.slice(hashAt);
  const q = [extra, sampleQuery()].filter(Boolean).join('&');
  return base + (q ? '?' + q : '') + hash;
}

export function renderLede(s, { error = false } = {}) {
  const eyebrow = $('[data-testid=date-eyebrow]'), counts = $('[data-testid=counts]'), sep = $('[data-kick-sep]');
  const h1 = $('[data-testid=hero]'), board = $('[data-testid=tape]'), links = $('[data-lede-links]'), retry = $('[data-retry]');
  const kick = $('[data-lede-kick]');
  if (error) {
    kick.hidden = true;
    setHTML(h1, esc("Can't load tonight's slate. Retrying…"));
    board.hidden = true; links.hidden = true; retry.hidden = false;
    return;
  }
  retry.hidden = true;
  if (!store.slate) {                       // loading
    kick.hidden = false; setText(eyebrow, ''); setText(counts, ''); sep.hidden = true;
    setHTML(h1, esc("Loading tonight's slate…"));
    renderBoard(board, Array.from({ length: 6 }, () => ({ label: '', value: '—' })));
    return;
  }
  const phase = phaseOf();
  const date = fmt.date(store.slate.date, { weekday: 'long', month: 'long', day: 'numeric' });
  kick.hidden = false;
  if (phase === 'no_games' || phase === 'offseason') {
    setText(eyebrow, date); setText(counts, phase === 'offseason' ? 'offseason' : 'no games'); sep.hidden = false;
  } else {
    setText(eyebrow, date + ' · ' + plural(s.games, 'game'));
    setText(counts, s.final + ' final · ' + s.live + ' live · ' + s.upcoming + ' to come' + (s.postponed > 0 ? ' · ' + s.postponed + ' postponed' : ''));
    sep.hidden = false;
  }
  setHTML(h1, sentence(s));
  board.hidden = NOBOARD.includes(phase);
  if (!board.hidden) renderBoard(board, boardCells(s));
  if (phase === 'no_games' || phase === 'offseason') {
    const last = store.slate.last_slate_date;
    let html = '<a class="more-link" href="#season">Season so far ›</a>';
    if (last) html += '<a class="more-link" href="' + esc(linkWithQuery('/', 'date=' + last)) + '">Last games, ' + esc(fmt.date(last, { month: 'short', day: 'numeric' })) + ' ›</a>';
    setHTML(links, html);
    links.hidden = false;
  } else links.hidden = true;
}

// ---------- court rows ----------
function stateHTML(g) {
  const pending = pickSide(g) == null;
  if (g.state === 'live') {
    const m = pickMargin(g);
    return '<span class="live">Live' + (g.clock ? ' · ' + esc(g.clock) : '') + '</span>' +
      (pending || m == null ? '' : '<small>' + esc(marginLabel(g)) + '</small>');
  }
  if (g.state === 'final') {
    const r = result(g), tail = '<small>' + esc(g.clock || 'Final') + (g.official ? '' : ' · unofficial') + '</small>';
    if (pending || r == null) return '<span>Final</span>' + tail;
    if (g.bet) return '<span class="' + (r === 'hit' ? 'pos' : 'neg') + '">' + (r === 'hit' ? 'Hit ' : 'Miss ') + esc(fmt.money(pl(g), true)) + '</span>' + tail;
    return '<span>' + (r === 'hit' ? 'Pick right' : 'Pick wrong') + '</span>' + tail;
  }
  if (g.state === 'postponed' || g.state === 'void') {
    return '<span>Postponed</span><small>' + (g.bet ? esc(fmt.money(g.bet.amount)) + ' returned' : 'No bet') + '</small>';
  }
  if (!g.tip_time_utc) return '<span>Time TBD</span>';
  return '<span>' + esc(fmt.time(g.tip_time_utc)) + ' ET</span><small>' + esc(fmt.until(g.tip_time_utc, now())) + ' to tip</small>';
}

function rowLabel(g) {
  const ps = pickSide(g), A = g.away.tricode, H = g.home.tricode;
  if (!ps) return A + ' at ' + H + '. Pick pending. Open details';
  const m = g.implied_prob;
  return A + ' at ' + H + '. Model ' + fmt.pct(g.pick_prob) + ' for ' + g.pick +
    (m != null ? ', market ' + fmt.pct(m) + ', edge ' + fmt.pts(g.edge) + ' points' : '') + '. ' +
    (g.bet ? 'Bet ' + fmt.money(g.bet.amount) : 'No bet') + '. Open details';
}

function labHTML(g) {
  const ps = pickSide(g);
  if (!ps) {
    return '<span class="who">Pick pending</span><b>' + esc(g.away.tricode + ' at ' + g.home.tricode) + '</b>' +
      '<span class="sub">' + (g.tip_time_utc ? esc(fmt.time(g.tip_time_utc)) + ' ET' : 'Time TBD') + '</span>';
  }
  const opp = ps === 'away' ? g.home.tricode : g.away.tricode;
  const em = g.edge != null && g.implied_prob != null ? fmt.pts(g.edge) : '';
  return '<span class="who">' + (g.bet ? 'Bet on' : 'Pick · no bet') + '</span>' +
    '<b>' + esc(g.pick) + ' <em class="' + (g.edge > 0 ? 'pe' : 'ne') + '">' + esc(em) + '</em></b>' +
    '<span class="sub">' + (ps === 'away' ? 'at ' : 'vs ') + esc(opp) + ' · ' +
    (g.bet ? esc(fmt.money(g.bet.amount)) + ' · ' + esc(fmt.odds(g.odds)) : 'no bet') + '</span>';
}

function courtRow(g, i, onOpen) {
  const row = document.createElement('div');
  const fresh = !populated.has(g.game_id) && motionOn();
  row.className = 'gl' + (fresh ? ' pre' : '');
  row.dataset.id = g.game_id;
  row.style.setProperty('--i', String(i));
  const hit = document.createElement('button');
  hit.className = 'gl__hit'; hit.type = 'button';
  hit.setAttribute('aria-label', rowLabel(g));
  hit.addEventListener('click', () => onOpen(g.game_id, hit));
  const lab = document.createElement('div');
  lab.className = 'gl__lab';
  lab.innerHTML = labHTML(g);
  const st = document.createElement('div');
  st.className = 'gl__st'; st.dataset.st = '';
  setHTML(st, stateHTML(g));
  row.append(hit, lab, glanceCourt(g, i), st);
  if (fresh) {
    watch(row, r => { r.classList.remove('pre'); populated.add(g.game_id); countUp(r); }, { threshold: 0.6 });
  } else populated.add(g.game_id);
  return row;
}

export function renderCourts(onOpen) {
  const host = $('[data-testid=chart]');
  host.querySelectorAll('.gl').forEach(x => x.remove());
  const list = byTip();
  host.hidden = !list.length || ['no_games', 'offseason'].includes(phaseOf());
  if (host.hidden) return;
  list.forEach((g, i) => host.append(courtRow(g, i, onOpen)));
}

export function updateCourtStates() {
  document.querySelectorAll('[data-testid=chart] .gl').forEach(r => {
    const g = store.games.find(x => x.game_id === r.dataset.id);
    if (!g) return;
    setHTML(r.querySelector('[data-st]'), stateHTML(g));
    const hit = r.querySelector('.gl__hit'), lbl = rowLabel(g);
    if (hit.getAttribute('aria-label') !== lbl) hit.setAttribute('aria-label', lbl);
  });
}
