// node --test tests/js/  — the day summary strip: totals and copy (no DOM).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { normalize } from '../../public/static/js/state.js';
import { daySummary, dayView } from '../../public/static/js/tonight/daysummary.js';

const tm = t => ({ tricode: t, name: t });
const G = (id, over) => normalize(Object.assign({ game_id: id, status: 'scheduled', home: tm('BOS'), away: tm('NYK'), pick: 'BOS', odds: -110, bet: null }, over));
const bet = (amount, over) => Object.assign({ amount }, over);
const money = v => Math.round(v * 100) / 100;

test('open bets: stake and payout use decimal odds, both signs', () => {
  const d = daySummary([G('1', { bet: bet(100), odds: 150 }), G('2', { bet: bet(55), odds: -110 })]);
  assert.equal(d.bets, 2);
  assert.equal(d.openStake, 155);
  assert.equal(money(d.openProfit), money(150 + 50));       // 100 * 1.5 + 55 * 100/110
  assert.equal(money(d.openReturn), money(155 + 200));
  const v = dayView(d, { isPast: false, bankroll: 956.27 });
  assert.deepEqual(v.cells.map(c => c.label), ['Current bankroll', 'At stake today', 'Potential payout']);
  assert.equal(v.cells[0].value, '$956.27');
  assert.equal(v.cells[2].value, '$355.00');
  assert.match(v.cells[2].small, /\+\$200\.00 profit/);
});

test('temporary picks are never bets', () => {
  const games = [G('1', { provisional: true, bet: null }), G('2', { provisional: true, bet: bet(40) }), G('3', { pick: null })];
  const d = daySummary(games);
  assert.equal(d.bets, 0);
  assert.equal(d.staked, 0);
  assert.equal(d.waiting, 2);                                // the pick-less game and the temp pick (the bet-carrying temp is ignored)
  const v = dayView(d, { isPast: false, bankroll: 956.27 });
  assert.equal(v.cells.length, 1);
  assert.match(v.note, /No bets yet\. Final picks come about an hour before each tip/);
  assert.ok(!v.cells.some(c => /stake|payout/i.test(c.label)));
});

test('missing bankroll shows a dash, never zero', () => {
  const v = dayView(daySummary([G('1', { bet: bet(10) })]), { isPast: false, bankroll: null });
  assert.equal(v.cells[0].value, '—');
});

test('settled and open bets are split, not double counted', () => {
  const d = daySummary([
    G('1', { status: 'final', result: 'hit', bet: bet(100), odds: 100 }),
    G('2', { status: 'final', result: 'miss', bet: bet(50) }),
    G('3', { bet: bet(30), odds: 200 })
  ]);
  assert.equal(d.settled, 2);
  assert.equal(d.settledPL, 50);
  assert.equal(d.openStake, 30);
  assert.equal(d.openReturn, 90);
  const v = dayView(d, { isPast: false, bankroll: 1000 });
  assert.equal(v.cells.length, 4);
  assert.equal(v.cells[1].value, '$30.00');
  assert.equal(v.cells[3].value, '+$50.00');
});

test('everything settled: result state', () => {
  const d = daySummary([G('1', { status: 'final', result: 'miss', bet: bet(61.92) })]);
  const v = dayView(d, { isPast: false, bankroll: 956.27 });
  assert.deepEqual(v.cells.map(c => c.label), ['Current bankroll', 'Staked', 'Returned', 'Net P/L']);
  assert.equal(v.cells[2].value, '$0.00');
  assert.equal(v.cells[3].value, '−$61.92');
  assert.match(v.note, /Unofficial until the 6 AM settle/);
});

test('past night: staked, returned, P/L; no bankroll; temp picks and voids ignored', () => {
  const games = [
    G('1', { status: 'final', result: 'miss', bet: bet(61.92, { result: 'loss' }) }),
    G('2', { status: 'final', provisional: true, result: 'hit' }),
    G('3', { status: 'postponed', bet: bet(20) })
  ];
  const v = dayView(daySummary(games), { isPast: true, bankroll: 956.27, recap: { staked: 61.92, net_pl: -61.92 } });
  assert.deepEqual(v.cells.map(c => c.label), ['Staked', 'Returned', 'Net P/L']);
  assert.deepEqual(v.cells.map(c => c.value), ['$61.92', '$0.00', '−$61.92']);
});

test('past night with only temporary picks', () => {
  const v = dayView(daySummary([G('1', { status: 'final', provisional: true, result: 'hit' })]), { isPast: true, bankroll: 956.27 });
  assert.equal(v.cells.length, 0);
  assert.equal(v.note, 'No bets that night.');
});

test('page wiring: strip sits between the lede and the tickets, no inline script or style', () => {
  const html = fs.readFileSync(new URL('../../public/index.html', import.meta.url), 'utf8');
  const a = html.indexOf('<section class="lede"'), b = html.indexOf('data-testid="day-summary"'), c = html.indexOf('data-tix-section');
  assert.ok(a > 0 && a < b && b < c);
  const js = fs.readFileSync(new URL('../../public/static/js/tonight/daysummary.js', import.meta.url), 'utf8');
  assert.ok(!/innerHTML/.test(js));
});
