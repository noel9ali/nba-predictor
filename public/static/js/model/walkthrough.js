// Chapter 3, "How it thinks, one pick at a time": one settled pick through seven steps.
// buildWalkModel is pure (strings and numbers only, unit-testable); the renderer makes DOM with
// createElement/textContent and writes every dynamic length with style.setProperty. Nothing in
// this chapter animates.
import { fmt, pct1, monthDay, MINUS, fractionWord, kellyNoun, teamParts, joinAnd,
  FEATURE_COUNT, ELO_DEFAULTS, KELLY_FRACTION, MAX_STAKE } from '../format.js';
import { stepCourt } from '../court.js';
import { SAMPLE } from '../api.js';

const has = v => typeof v === 'number' && Number.isFinite(v);
const one = v => (has(v) ? v.toFixed(1) : '—');
const money = v => fmt.money(v);
const oddsText = o => (o > 0 ? '+' : MINUS) + Math.abs(o);
const trim = x => (Number.isInteger(Math.round(x * 10) / 10) ? String(Math.round(x * 10) / 10) : (Math.round(x * 10) / 10).toFixed(1));
const num0 = n => Math.round(n).toLocaleString('en-US');

function shiftDay(iso, delta) {
  const d = new Date(String(iso).slice(0, 10) + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

const FORM_ROWS = [
  { key: 'roll_pts', label: 'Points', word: 'points', fmt: one, lowerBetter: false },
  { key: 'roll_fg_pct', label: 'FG%', word: 'FG%', fmt: v => (has(v) ? pct1(v) + '%' : '—'), lowerBetter: false },
  { key: 'roll_reb', label: 'Rebounds', word: 'rebounds', fmt: one, lowerBetter: false },
  { key: 'roll_ast', label: 'Assists', word: 'assists', fmt: one, lowerBetter: false },
  { key: 'roll_tov', label: 'Turnovers ↓', word: 'turnovers', fmt: one, lowerBetter: true },
  { key: 'roll_stocks', label: 'Stl + blk', word: 'steals + blocks', fmt: one, lowerBetter: false }
];

export function buildWalkModel({ detail, model } = {}) {
  const g = detail && detail.game, tape = detail && detail.tape;
  if (!g || !g.home || !g.away || !tape || !tape.home || !tape.away) return null;
  model = model || {};
  const th = tape.home, ta = tape.away;
  const H = g.home.tricode, A = g.away.tricode;
  const hp = teamParts(g.home), ap = teamParts(g.away);
  const pickHome = g.pick === A ? false : true;
  const pickTri = g.pick || H;
  const pickCity = pickHome ? hp.city : ap.city;
  const P = g.pick_prob;
  const elo = Object.assign({}, ELO_DEFAULTS, model.elo || {});
  const W = (model.training && model.training.rolling_window) || 10;
  const prod = String(model.production_model || '');
  const date = g.date || null;
  const bet = g.bet || null;
  const labels = { left: A, right: H };

  const vm = { H, A, pickTri, pickHome, P, date, steps: [] };
  vm.lede = `Follow a single pick from ratings to a stamped ticket: ${ap.city} at ${hp.city}${date ? ', ' + monthDay(date) : ''}. Seven steps: six it runs before every game, one after the final.`;

  // ---- Step 1: rate both teams
  const s1 = { title: 'Rate both teams' };
  s1.text = `Every team carries an Elo rating that moves after each game: up for a win, down for a loss, more for an upset. The home team gets ${elo.home_advantage} points for the floor. Between seasons ratings slide ${fractionWord(elo.mean_reversion)} of the way back to ${elo.start}.`;
  let pElo = null;
  if (has(th.elo) && has(ta.elo)) {
    const hElo = Math.round(th.elo), aElo = Math.round(ta.elo), hEff = hElo + elo.home_advantage;
    const pHome = 1 / (1 + Math.pow(10, (aElo - hEff) / 400));
    pElo = pickHome ? pHome : 1 - pHome;
    const lo = Math.min(1450, Math.floor(Math.min(hElo, aElo) / 50) * 50);
    const hi = Math.max(1700, Math.ceil(Math.max(hEff, aElo) / 50) * 50);
    const span = hi - lo, pc = v => ((v - lo) / span) * 100;
    s1.math = [`${H} ${num0(hElo)} + ${elo.home_advantage} home = ${num0(hEff)} vs ${A} ${num0(aElo)}`, `Elo alone: ${pickTri} wins ${pct1(pElo)}%`];
    s1.chart = {
      aria: `${H} rating ${hElo} plus ${elo.home_advantage} home, ${A} ${aElo}`,
      home: { tri: H, fill: pc(hElo), value: num0(hEff), bumpLeft: pc(hElo), bumpWidth: (elo.home_advantage / span) * 100 },
      away: { tri: A, fill: pc(aElo), value: num0(aElo) },
      axis: [num0(lo), num0((lo + hi) / 2), num0(hi)],
      legend: ['Rating', `+${elo.home_advantage} home floor`]
    };
  }
  s1.cap = `K-factor ${elo.k} · home +${elo.home_advantage} · ${Math.round(elo.mean_reversion * 100)}% reset toward ${num0(elo.start)} each off-season`;
  vm.steps.push(s1);

  // ---- Step 2: recent form
  const s2 = { title: 'Check recent form' };
  s2.text = `Ratings move slowly, so the model also looks at each team's last ${W} games: scoring, shooting, rebounds, assists, turnovers, and steals plus blocks.`;
  const better = tape.better || {};
  const rows = FORM_ROWS.map(r => {
    const hv = th[r.key], av = ta[r.key];
    let side = null;
    if (better[r.key] === 'home' || better[r.key] === 'away') side = better[r.key];
    else if (has(hv) && has(av) && hv !== av) side = (r.lowerBetter ? hv < av : hv > av) ? 'home' : 'away';
    const mx = Math.max(has(hv) ? hv : 0, has(av) ? av : 0);
    return {
      label: r.label, word: r.word, side,
      hv: r.fmt(hv), av: r.fmt(av),
      hw: has(hv) && mx > 0 ? (hv / mx) * 100 : null,
      aw: has(av) && mx > 0 ? (av / mx) * 100 : null,
      level: has(hv) && has(av) && !side
    };
  });
  const homeN = rows.filter(r => r.side === 'home').length, awayN = rows.filter(r => r.side === 'away').length;
  const leadHome = homeN >= awayN, leadN = leadHome ? homeN : awayN;
  const lead = leadHome ? H : A, other = leadHome ? A : H;
  const otherWords = rows.filter(r => r.side === (leadHome ? 'away' : 'home')).map(r => r.word);
  const levelN = rows.filter(r => r.level).length;
  let m2 = leadN === 6 ? `${lead} better on all 6` : `${lead} better on ${leadN} of 6`;
  if (leadN < 6 && otherWords.length) m2 += ` · ${other} better on ${joinAnd(otherWords)}`;
  if (levelN) m2 += ` · level on ${levelN}`;
  s2.math = [m2];
  s2.chart = { aria: `Last ${W} games, ${H} against ${A}`, rows, cap: 'Teal marks the better side. Fewer turnovers is better.' };
  vm.steps.push(s2);

  // ---- Step 3: rest
  const s3 = { title: 'Count the rest' };
  s3.text = "Tired legs matter. The model uses the gap in days off since each team's last game.";
  if (has(th.rest_days) && has(ta.rest_days)) {
    const rh = Math.max(1, Math.round(th.rest_days)), ra = Math.max(1, Math.round(ta.rest_days));
    const cellsFor = r => {
      const lastIdx = 3 - r, cells = [];
      for (let i = 0; i < 4; i++) {
        if (i === 3) cells.push({ cls: 'd o', text: 'tip' });
        else if (i === lastIdx) cells.push({ cls: 'd g', text: 'game' });
        else if (i > lastIdx) cells.push({ cls: 'd', text: 'rest' });
        else cells.push({ cls: 'd', text: '' });
      }
      return cells;
    };
    const dateLabels = date ? [-3, -2, -1, 0].map(d => monthDay(shiftDay(date, d))) : null;
    const gap = rh - ra;
    const plural = n => (n === 1 ? '' : 's');
    s3.chart = {
      aria: date
        ? `${hp.city} last played ${monthDay(shiftDay(date, -rh))}, ${ap.city} ${monthDay(shiftDay(date, -ra))}`
        : `${hp.city} had ${rh} day${plural(rh)} of rest, ${ap.city} ${ra}`,
      dates: dateLabels,
      rows: [{ tri: H, cells: cellsFor(rh) }, { tri: A, cells: cellsFor(ra) }],
      notes: [[H, rh], [A, ra]].filter(([, r]) => r >= 4).map(([tri, r]) => `${tri}'s last game was ${r} days earlier.`)
    };
    const gapText = gap > 0 ? `+${gap} for ${H}` : gap < 0 ? `+${-gap} for ${A}` : '0 (even)';
    s3.math = [`${H} ${rh} day${plural(rh)} · ${A} ${ra} day${plural(ra)} · rest gap ${gapText}`];
  }
  vm.steps.push(s3);

  // ---- Step 4: make the call
  const s4 = { title: 'Make the call' };
  const modelPhrase = prod.includes('logistic') ? 'a logistic regression' : 'the model';
  const p100 = Math.round(P * 100);
  s4.text = `All ${FEATURE_COUNT} numbers are put on the same scale, weighed, and turned into one probability by ${modelPhrase}.`
    + (prod.includes('calibrated') ? ` A calibration step then adjusts it so that "${p100}%" means about ${p100} out of 100 such games.` : '');
  s4.math = [`Model: ${pickTri} wins ${pct1(P)}%`];
  if (pElo != null) {
    const a = Number(pct1(P)), b = Number(pct1(pElo));
    s4.math.push(a < b ? `Lower than Elo's ${pct1(pElo)}%: the rest of the inputs pulled it back`
      : a > b ? `Higher than Elo's ${pct1(pElo)}%: the rest of the inputs pushed it up`
        : `Same as Elo's ${pct1(pElo)}%: the rest of the inputs left it unchanged`);
    s4.court = {
      pickHome, p: P, ref: { value: pElo, text: 'Elo alone ' + pct1(pElo) + '%' }, modelText: 'Model ' + pct1(P) + '%',
      gap: 'none', labels, ariaLabel: `Elo alone ${pct1(pElo)} percent, model ${pct1(P)} percent for ${pickCity}`
    };
  } else {
    s4.court = { pickHome, p: P, ref: null, modelText: 'Model ' + pct1(P) + '%', gap: 'none', labels, ariaLabel: `Model ${pct1(P)} percent for ${pickCity}` };
  }
  s4.cap = `Painted from ${pickCity}'s baseline, like the courts on Tonight.`;
  const homeRate = model.training && has(model.training.home_win_rate) ? model.training.home_win_rate
    : model.test && has(model.test.baseline_home_win_rate) ? model.test.baseline_home_win_rate : null;
  const noFactors = !(Array.isArray(detail.factors) && detail.factors.length);
  s4.need = noFactors
    ? `Needs backend: store each input's push per pick (prediction_factors) so this step can build the ${p100}% factor by factor${homeRate != null ? ` from the ${pct1(homeRate)}% home rate` : ''}.`
    : null;
  vm.steps.push(s4);

  // ---- Step 5: compare with the market
  const s5 = { title: 'Compare with the market' };
  const noOdds = !has(g.odds) || g.skip_reason === 'no_odds';
  if (noOdds) {
    s5.text = 'No book price was available for this game, so the model made its pick but could not compare it with the market. No price, no bet.';
    s5.court = { pickHome, p: P, ref: null, modelText: 'Model ' + p100 + '%', gap: 'auto', labels, ariaLabel: `Model ${pct1(P)} percent, no market price` };
  } else {
    const impl = has(g.implied_prob) ? g.implied_prob : fmt.implied(g.odds);
    const edge = has(g.edge) ? g.edge : P - impl;
    const book = g.bookmaker || 'The book';
    s5.text = `${book} had ${pickTri} at ${oddsText(g.odds)}, which implies ${pct1(impl)}%. The model's ${pct1(P)}% is `
      + (edge > 0 ? `${pct1(edge)} points higher. That gap is the edge. No edge, no bet.`
        : `${edge < 0 ? pct1(Math.abs(edge)) + ' points lower' : 'no higher'}. There is no edge, so there was no bet: this one is a pick only.`);
    const a = g.odds > 0 ? 100 : Math.abs(g.odds), b = Math.abs(g.odds);
    s5.math = [`${a} ÷ (${b} + 100) = ${pct1(impl)}% · edge ${fmt.pts(edge)} pts`];
    s5.court = {
      pickHome, p: P, ref: { value: impl, text: 'Mkt ' + Math.round(impl * 100) + '%' }, modelText: 'Model ' + p100 + '%', gap: 'auto', labels,
      ariaLabel: `Market ${pct1(impl)} percent, model ${pct1(P)} percent, ` + (edge < 0 ? `model is ${pct1(Math.abs(edge))} points below the market` : `edge ${pct1(edge)} points`)
    };
    s5.legend = ["Market's chance", 'Edge'];
  }
  vm.steps.push(s5);

  // ---- Step 6: size the bet
  const s6 = { title: 'Size the bet' };
  if (bet && has(bet.amount) && has(bet.kelly_full) && has(bet.bankroll_at_bet)) {
    const bankroll = bet.bankroll_at_bet, full = bet.kelly_full, frac = has(bet.kelly_fraction) ? bet.kelly_fraction : KELLY_FRACTION;
    const quarter = full * frac, used = Math.min(MAX_STAKE, quarter), capped = quarter > MAX_STAKE;
    s6.text = `The Kelly formula says how much of the bankroll an edge is worth. The model bets ${fractionWord(frac)} of that, and never more than ${Math.round(MAX_STAKE * 100)}%.`;
    const usedText = capped ? Math.round(MAX_STAKE * 100) + '%' : (used * 100).toFixed(2) + '%';
    s6.math = [`Full Kelly ${pct1(full)}% → ${kellyNoun(frac)} ${pct1(quarter)}%${capped ? ' → cap ' + Math.round(MAX_STAKE * 100) + '%' : ''}`,
      `${usedText} of ${money(bankroll)} = ${money(bet.amount)}`];
    if (Math.abs(used * bankroll - bet.amount) > 0.01) console.warn('model: stake does not match Kelly arithmetic', { derived: used * bankroll, amount: bet.amount });
    s6.chart = {
      aria: `Full Kelly ${pct1(full)} percent of bankroll, bet ${trim(used * 100)} percent, ${bet.amount.toFixed(2)} dollars`,
      topL: 'Bankroll', topR: money(bankroll),
      fullW: Math.min(100, full * 100), qW: Math.min(100, used * 100),
      bold: money(bet.amount), betText: ` bet (${trim(used * 100)}%)`,
      fullText: `full Kelly would bet $${num0(full * bankroll)} (${pct1(full)}%)`
    };
  } else {
    const reason = g.skip_reason === 'no_odds' ? 'There was no book price, so the formula had nothing to work with and the model staked nothing.'
      : g.skip_reason === 'missing_data' ? 'Some inputs were missing, so the model made no bet.'
        : 'This pick had no edge over the market, so the formula says to stake nothing.';
    s6.text = `The Kelly formula says how much of the bankroll an edge is worth. ${reason}`;
    s6.chart = { aria: 'No bet: stake $0.00', topL: 'Bet size', topR: '$0.00', empty: true, note: 'No stake on this pick.' };
  }
  vm.steps.push(s6);

  // ---- Step 7: grade it
  const s7 = { title: 'Grade it' };
  const res = detail.result || null;
  const final = !!(res && has(res.home_score) && has(res.away_score) && res.winner);
  const closing = 'The 6 AM job makes it official, then retrains the model with last night\'s games added.';
  const outcome = bet ? (bet.result || g.result) : g.result;
  const pickRight = g.result === 'hit' ? true : g.result === 'miss' ? false : res && res.correct != null ? res.correct === 1 : final ? res.winner === pickTri : null;
  const ticket = {
    stubLabel: bet ? 'Bet on' : 'Pick', stubTri: pickTri,
    stubMeta: [has(g.odds) ? oddsText(g.odds) : null, g.bookmaker || null].filter(Boolean).join(' · '),
    rows: [{ tri: A, score: final ? String(res.away_score) : '—', lo: final && res.winner !== A }, { tri: H, score: final ? String(res.home_score) : '—', lo: final && res.winner !== H }],
    note: bet && has(bet.amount) ? (has(g.odds) ? `${money(bet.amount)} to win ${money(fmt.payout(bet.amount, g.odds))}` : `${money(bet.amount)} staked`) : 'No bet placed',
    stamp: null
  };
  if (!final) {
    s7.text = `${ap.city} at ${hp.city} hasn't finished yet. The ticket is graded when the 6 AM job posts the final score.`;
  } else {
    const winCity = res.winner === A ? ap.city : hp.city;
    const ws = res.winner === A ? res.away_score : res.home_score, ls = res.winner === A ? res.home_score : res.away_score;
    let mid;
    if (bet && has(bet.amount)) {
      if (outcome === 'hit') {
        const pl = has(bet.profit_loss) ? bet.profit_loss : fmt.payout(bet.amount, g.odds);
        mid = `The ticket paid ${money(pl)} on ${money(bet.amount)}.`;
        ticket.stamp = { cls: 'cash', word: 'Cashed', sub: fmt.money(pl, true) };
      } else if (outcome === 'miss') {
        mid = `The ticket lost ${money(bet.amount)}.`;
        ticket.stamp = { cls: 'lost', word: 'Lost', sub: fmt.money(has(bet.profit_loss) ? bet.profit_loss : -bet.amount, true) };
      } else {
        mid = `The game didn't count, so the ${money(bet.amount)} stake was returned.`;
        ticket.stamp = { cls: 'void', word: 'Void', sub: `${money(bet.amount)} returned` };
      }
    } else if (outcome === 'void') {
      mid = "The game didn't count.";
      ticket.stamp = { cls: 'void', word: 'Void', sub: 'no bet' };
    } else {
      mid = `The model had no bet on this one, but its pick was ${pickRight ? 'right' : 'wrong'}.`;
      ticket.stamp = { cls: pickRight ? 'cash' : 'lost', word: pickRight ? 'Pick right' : 'Pick wrong', sub: 'no bet' };
    }
    s7.text = `${winCity} won ${ws}${'–'}${ls}. ${mid} ${closing}`;
  }
  s7.ticket = ticket;
  vm.steps.push(s7);
  return vm;
}

// ---------------- rendering ----------------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const pctStr = v => String(Math.round(v * 1000) / 1000) + '%';
const setPx = (n, prop, v) => n.style.setProperty(prop, pctStr(v));
const legendOf = list => {
  const lg = el('div', 'legend');
  const a = el('span'); a.append(el('i', 'lg-p'), document.createTextNode(list[0]));
  const b = el('span'); b.append(el('i', 'lg-h'), document.createTextNode(list[1]));
  lg.append(a, b);
  return lg;
};
const mathBox = lines => {
  const m = el('div', 'math');
  lines.forEach(l => m.append(el('span', 'ml', l)));
  return m;
};
const unavailable = text => el('p', 'cap', text);

function gfxElo(c) {
  const wrap = el('div', 'elo'); wrap.setAttribute('role', 'img'); wrap.setAttribute('aria-label', c.aria);
  [c.home, c.away].forEach((side, i) => {
    const r = el('div', 'r');
    const tri = el('span'); tri.append(el('b', null, side.tri));
    const track = el('span', 'track');
    const fill = el('i', 'fill'); setPx(fill, 'width', side.fill);
    track.append(fill);
    if (i === 0) {
      const bump = el('i', 'floor-bump');
      setPx(bump, 'left', side.bumpLeft); setPx(bump, 'width', side.bumpWidth);
      track.append(bump);
    }
    r.append(tri, track, el('span', 'v', side.value));
    wrap.append(r);
  });
  const axis = el('div', 'axis'); axis.setAttribute('aria-hidden', 'true');
  c.axis.forEach(t => axis.append(el('span', null, t)));
  wrap.append(axis, legendOf(c.legend));
  return [wrap];
}

function gfxForm(c, H, A) {
  const card = el('div', 'tape'); card.setAttribute('role', 'group'); card.setAttribute('aria-label', c.aria);
  const hd = el('div', 'tth');
  hd.append(el('span', null, H), el('span', null, A));
  card.append(hd);
  c.rows.forEach(r => {
    const row = el('div', 'tt');
    const v = (txt, side, cls) => {
      const s = el('span', cls);
      if (r.side === side) s.append(el('b', null, txt)); else s.textContent = txt;
      return s;
    };
    const bar = (w, cls, on) => {
      const b = el('span', 'b ' + cls + (on ? ' bt' : '')); b.setAttribute('aria-hidden', 'true');
      if (w != null) { const i = el('i'); setPx(i, 'width', w); b.append(i); }
      return b;
    };
    row.append(v(r.hv, 'home', 'v'), bar(r.hw, 'l', r.side === 'home'), el('span', 'lb', r.label), bar(r.aw, 'r', r.side === 'away'), v(r.av, 'away', 'v r'));
    card.append(row);
  });
  card.append(el('p', 'cap', c.cap));
  return [card];
}

function gfxRest(c) {
  const wrap = el('div', 'rest'); wrap.setAttribute('role', 'img'); wrap.setAttribute('aria-label', c.aria);
  if (c.dates) {
    const r = el('div', 'r');
    r.append(el('span'));
    c.dates.forEach(d => r.append(el('span', 'cap', d)));
    wrap.append(r);
  }
  c.rows.forEach(row => {
    const r = el('div', 'r');
    r.append(el('b', null, row.tri));
    row.cells.forEach(cell => r.append(el('span', cell.cls, cell.text)));
    wrap.append(r);
  });
  const out = [wrap];
  c.notes.forEach(n => out.push(el('p', 'cap', n)));
  return out;
}

function gfxCourt(params, cap, legend) {
  const out = [stepCourt(params)];
  if (legend) out.push(legendOf(legend));
  if (cap) out.push(el('p', 'cap', cap));
  return out;
}

function gfxKelly(c) {
  const wrap = el('div', 'kelly'); wrap.setAttribute('role', 'img'); wrap.setAttribute('aria-label', c.aria);
  const top = el('div', 'lab'); top.append(el('span', null, c.topL), el('b', null, c.topR));
  const bar = el('div', 'bar');
  if (!c.empty) {
    const f = el('i', 'full'), q = el('i', 'q');
    setPx(f, 'width', c.fullW); setPx(q, 'width', c.qW);
    bar.append(f, q);
  }
  wrap.append(top, bar);
  if (c.empty) {
    wrap.append(el('p', 'cap', c.note));
  } else {
    const bot = el('div', 'lab');
    const s1 = el('span'); s1.append(el('b', null, c.bold), document.createTextNode(c.betText));
    bot.append(s1, el('span', null, c.fullText));
    wrap.append(bot);
  }
  return [wrap];
}

function gfxTicket(t) {
  const tk = el('div', 'mini-ticket');
  const stub = el('div', 'stub');
  const s1 = el('span', null, t.stubLabel + ' ');
  s1.append(el('b', null, t.stubTri));
  stub.append(s1);
  if (t.stubMeta) stub.append(el('span', null, t.stubMeta));
  const body = el('div', 'body');
  t.rows.forEach(r => {
    const row = el('div', 'tm' + (r.lo ? ' lo' : ''));
    row.append(el('span', null, r.tri), el('span', null, r.score));
    body.append(row);
  });
  body.append(el('div', 'sp'), el('div', 'mt-note', t.note));
  tk.append(stub, body);
  if (t.stamp) {
    const st = el('div', 'mini-stamp ' + t.stamp.cls, t.stamp.word);
    st.append(el('small', null, t.stamp.sub));
    tk.append(st);
  }
  return [tk];
}

export function initWalkthrough(section, detail, model) {
  const body = section && section.querySelector('[data-body]');
  const lede = section && section.querySelector('[data-lede]');
  if (!body || !detail || !detail.game || !detail.tape) return false;
  let vm;
  try { vm = buildWalkModel({ detail, model }); } catch (e) { console.warn('model: walkthrough failed', e); return false; }
  if (!vm) return false;
  if (lede) lede.textContent = vm.lede;
  body.textContent = '';
  const steps = el('div', 'steps'); steps.setAttribute('data-steps', '');

  vm.steps.forEach((s, i) => {
    const n = i + 1;
    const art = el('article', 'step'); art.setAttribute('data-step', String(n)); art.setAttribute('aria-labelledby', 'walk-h' + n);
    const txt = el('div', 'txt');
    const no = el('span', 'no', String(n)); no.setAttribute('aria-hidden', 'true');
    const h3 = el('h3'); h3.id = 'walk-h' + n;
    h3.append(el('span', 'sr', `Step ${n}. `), document.createTextNode(s.title));
    txt.append(no, h3, el('p', null, s.text));
    if (s.math && s.math.length) txt.append(mathBox(s.math));
    if (s.need && SAMPLE) txt.append(el('div', 'need', s.need));

    const gfx = el('div', n === 7 ? 'gfx' : 'gfx card');
    let kids;
    if (n === 1) kids = s.chart ? gfxElo(s.chart) : [unavailable('Ratings are not available for this game.')];
    else if (n === 2) kids = gfxForm(s.chart, vm.H, vm.A);
    else if (n === 3) kids = s.chart ? gfxRest(s.chart) : [unavailable('Rest days are not available for this game.')];
    else if (n === 4) kids = gfxCourt(s.court, s.cap);
    else if (n === 5) kids = gfxCourt(s.court, null, s.legend);
    else if (n === 6) kids = gfxKelly(s.chart);
    else kids = gfxTicket(s.ticket);
    if (n === 1) kids.push(el('p', 'cap', s.cap));
    gfx.append(...kids);
    art.append(txt, gfx);
    steps.append(art);
  });
  body.append(steps);
  return true;
}
