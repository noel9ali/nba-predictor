// The day's money: bankroll, what's at stake, what it pays if every bet wins. Real bets only; a temporary pick is never a bet.
import { fmt } from '../format.js';
import { renderBoard, signCls } from '../board.js';
import { store, pl, pickSide } from '../state.js';

const $ = s => document.querySelector(s);
const HIDE = ['no_games', 'offseason', 'prediction_failed'];
let bankroll = null;                       // settled balance going into tonight (/api/performance kpis), null until it lands

const plural = (k, w) => k + ' ' + w + (k === 1 ? '' : 's');
const stakeOf = g => (g.bet && !g.provisional && g.bet.amount > 0 ? g.bet.amount : 0);

// Pure: totals for a list of normalized games. Postponed/void bets are returned, so they count nowhere.
export function daySummary(games) {
  const d = { bets: 0, staked: 0, open: 0, openStake: 0, openReturn: 0, openProfit: 0, payoutKnown: true,
    settled: 0, settledStake: 0, settledPL: 0, settledReturn: 0, official: true, waiting: 0 };
  for (const g of games) {
    const amt = stakeOf(g);
    if (!amt) {
      // no bet yet: a temporary pick or a game with no pick at all is waiting on its final pick
      if (!g.bet && g.state === 'scheduled' && (g.provisional || pickSide(g) == null)) d.waiting++;
      continue;
    }
    if (g.state === 'postponed' || g.state === 'void') continue;
    d.bets++; d.staked += amt;
    const p = g.state === 'final' ? pl(g) : null;
    if (p != null) {
      d.settled++; d.settledStake += amt; d.settledPL += p; d.settledReturn += amt + p;
      if (g.bet.result == null) d.official = false;
    } else {
      d.open++; d.openStake += amt;
      if (g.odds == null) d.payoutKnown = false;
      else { d.openProfit += fmt.payout(amt, g.odds); d.openReturn += amt + fmt.payout(amt, g.odds); }
      d.official = false;
    }
  }
  return d;
}

// Cells and the one line of copy under them, for one state of the day. Pure.
export function dayView(d, { isPast, bankroll: br, recap }) {
  const money = v => fmt.money(v), signed = v => ({ value: fmt.money(v, true), cls: signCls(v) });
  const when = isPast ? 'that night' : 'tonight';
  const waitNote = d.waiting > 0 ? plural(d.waiting, 'game') + (d.waiting === 1 ? ' is' : ' are') + ' still waiting on a final pick, so ' + (d.waiting === 1 ? 'its' : 'any') + ' bet is not counted yet.' : '';
  if (d.bets === 0) {
    if (isPast) return { mode: 'none', cells: [], note: 'No bets ' + when + '.' };
    const note = d.waiting > 0
      ? 'No bets yet. Final picks come about an hour before each tip.'
      : 'No bets ' + when + '. The model found nothing worth a stake.';
    return { mode: 'bank', cells: [{ label: 'Current bankroll', value: money(br), small: 'settled, before tonight', testid: 'day-bankroll' }], note };
  }
  if (isPast || d.open === 0) {
    const off = !!recap && d.open === 0;               // the server's own numbers once the night is settled
    const staked = off && recap.staked != null ? recap.staked : d.staked;
    const net = off && recap.net_pl != null ? recap.net_pl : d.settledPL;
    const has = d.settled > 0;
    const cells = [
      { label: 'Staked', value: money(staked), testid: 'day-stake' },
      { label: 'Returned', value: has ? money(staked + net) : '—', testid: 'day-returned' },
      Object.assign({ label: 'Net P/L', testid: 'day-pl' }, has ? signed(net) : { value: '—' })
    ];
    if (!isPast) cells.unshift({ label: 'Current bankroll', value: money(br), small: d.official ? 'settled' : 'settled, before tonight', testid: 'day-bankroll' });
    const notes = [];
    if (d.open > 0) notes.push(plural(d.open, 'bet') + ' of ' + d.bets + ' still open.');
    else if (!d.official && !isPast) notes.push('Unofficial until the 6 AM settle.');
    if (waitNote && !isPast) notes.push(waitNote);
    return { mode: isPast ? 'past' : 'done', cells, note: notes.join(' ') };
  }
  const cells = [
    { label: 'Current bankroll', value: money(br), small: 'settled, before tonight', testid: 'day-bankroll' },
    { label: 'At stake today', value: money(d.openStake), small: d.settled > 0 ? plural(d.open, 'open bet') + ' of ' + d.bets : plural(d.open, 'bet'), testid: 'day-stake' },
    { label: 'Potential payout', value: d.payoutKnown ? money(d.openReturn) : '—', small: d.payoutKnown ? '+' + money(d.openProfit).replace(/^−?/, '') + ' profit if all win' : 'odds missing', testid: 'day-payout' }
  ];
  if (d.settled > 0) cells.push(Object.assign({ label: 'Settled so far', small: plural(d.settled, 'bet'), testid: 'day-pl' }, signed(d.settledPL)));
  return { mode: 'open' + cells.length, cells, note: waitNote };
}

export function setDayBankroll(v) {
  bankroll = typeof v === 'number' && !Number.isNaN(v) ? v : null;
  renderDaySummary();
}

export function renderDaySummary() {
  const host = $('[data-testid=day-summary]');
  if (!host) return;
  const phase = store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase);
  host.hidden = store.status === 'error' || !store.slate || HIDE.includes(phase) || !store.games.length;
  if (host.hidden) return;
  const isPast = store.isPast, v = dayView(daySummary(store.games), { isPast, bankroll, recap: store.slate.recap });
  $('[data-day-title]').textContent = isPast ? "That night's bets" : "Tonight's bets";
  const board = $('[data-day-board]'), note = $('[data-day-note]');
  if (board.dataset.mode !== v.mode) { board.textContent = ''; board.dataset.mode = v.mode; }
  board.hidden = !v.cells.length;
  if (v.cells.length) renderBoard(board, v.cells);
  note.hidden = !v.note;
  if (note.textContent !== v.note) note.textContent = v.note;
}
