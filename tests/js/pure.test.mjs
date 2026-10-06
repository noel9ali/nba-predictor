// node --test tests/js/  — pure helpers of the Hardwood frontend (no DOM).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fmt, pct1, wl, seasonOf } from '../../public/static/js/format.js';
import { normalize, applyLive, summarize, nextUpOf, visibleOf, countsOf, pl, result, pickMargin, marginLabel } from '../../public/static/js/state.js';
import { courtGeometry } from '../../public/static/js/court.js';

const sample = f => JSON.parse(fs.readFileSync(new URL('../../public/sample/' + f + '.json', import.meta.url)));
const night = () => sample('slate-2026-11-17').games.map(normalize);
const close = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, a + ' vs ' + b);

test('fmt', () => {
  assert.equal(fmt.money(58.359, true), '+$58.36');
  assert.equal(fmt.money(-41.96, true), '−$41.96');
  assert.equal(fmt.money(0, true), '±$0.00');
  assert.equal(fmt.money(-0.004, true), '±$0.00');
  assert.equal(fmt.money(1111.67), '$1,111.67');
  assert.equal(fmt.odds(-105), '−105');
  assert.equal(fmt.odds(105), '+105');
  assert.equal(fmt.odds(null), '—');
  assert.equal(fmt.pct(0.4878), '48.8%');
  assert.equal(fmt.pct(0.61, 0), '61%');
  assert.equal(fmt.pts(0.0978), '+9.8');
  assert.equal(fmt.pts(-0.0333), '−3.3');
  assert.equal(fmt.time('2026-11-17T23:31:40Z'), '6:31 PM');
  close(fmt.payout(55.58, -105), 52.9333);
  assert.equal(pct1(0.6811), '68.1');
  assert.equal(wl('54-41'), '54–41');
  assert.equal(seasonOf('2026-11-17'), '2026-27');
  assert.equal(seasonOf('2027-02-01'), '2026-27');
});

test('court geometry', () => {
  const a = courtGeometry({ p: 0.61, m: 0.5122, fromLeft: false });
  close(a.edgeLeft, 39); close(a.mkLeft, 48.78); close(a.paintWidth, 51.22);
  assert.equal(a.gap.kind, 'hat'); close(a.gap.left, 39); close(a.gap.width, 9.78);
  const b = courtGeometry({ p: 0.55, m: 0.5833, fromLeft: true });
  assert.equal(b.gap.kind, 'short'); close(b.gap.left, 55); close(b.gap.width, 3.33); close(b.paintWidth, 55);
  assert.equal(courtGeometry({ p: 0.61, m: 0.4878, fromLeft: true, gap: 'none' }).gap, null);
  assert.equal(courtGeometry({ p: null, m: 0.5, fromLeft: true }), null);
  assert.equal(courtGeometry({ p: 0.5, m: 0.5, fromLeft: true }).gap, null);
});

test('live snapshot summary (9:05 PM)', () => {
  const g = night();
  assert.deepEqual(applyLive(g, sample('live-live'), true), []);        // first merge is silent
  const s = summarize(g);
  assert.equal(s.games, 6); assert.equal(s.final, 1); assert.equal(s.live, 3); assert.equal(s.upcoming, 2);
  assert.equal(s.bets, 5); close(s.staked, 218.27); close(s.settled, 58.359); close(s.open, 162.69);
  close(s.toWinOpen, 152.638); close(s.ifEnded, -5.4096);
  assert.equal(s.ahead, 1); assert.equal(s.liveBets, 3);
  assert.deepEqual(countsOf(g), { all: 6, bets: 5, live: 3, upcoming: 2, final: 1 });
  const ids = list => list.map(x => x.game_id.slice(-3)).join(',');
  assert.equal(ids(visibleOf(g, 'all', 'tip')), '190,191,192,193,194,195');
  assert.equal(ids(visibleOf(g, 'all', 'edge')), '190,195,192,193,191,194');
  assert.equal(ids(visibleOf(g, 'all', 'bet')), '190,195,192,193,191,194');
  assert.equal(ids(visibleOf(g, 'live', 'tip')), '191,192,193');
  const nyk = g.find(x => x.game_id.endsWith('191')), min = g.find(x => x.game_id.endsWith('192'));
  assert.equal(pickMargin(nyk), 5); assert.equal(marginLabel(nyk), 'NYK up 5'); assert.equal(marginLabel(min), 'MIN down 4');
});

test('replay to the end of the night', () => {
  const g = night();
  applyLive(g, sample('live-replay-0'), true);
  let finals = [];
  for (let i = 1; i <= 6; i++) finals.push(...applyLive(g, sample('live-replay-' + i), false).filter(c => c.type === 'final'));
  assert.equal(finals.length, 5);
  const s = summarize(g);
  close(s.settled, 117.007); assert.equal(s.betW, 4); assert.equal(s.betL, 1); assert.equal(s.final, 6);
  assert.equal(nextUpOf(g), null);
  const sac = g.find(x => x.game_id.endsWith('195'));
  assert.equal(result(sac), 'hit'); close(pl(sac), 52.933);
});

test('merge safety', () => {
  const g = night();
  applyLive(g, sample('live-live'), true);
  const back = { games: [{ game_id: g[1].game_id, status: 'scheduled', period: null, clock: null, home_score: null, away_score: null, postponed: false },
    { game_id: g[0].game_id, status: 'live', period: 4, clock: 'Q4 1:00', home_score: 1, away_score: 1, postponed: false }] };
  applyLive(g, back, false);
  assert.equal(g[1].state, 'live');
  assert.equal(g[0].state, 'final');
});
