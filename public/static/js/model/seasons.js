// Chapter 2, "What it studied": the pinned season strip (all games, then the held-back test set),
// the five-number strip and three plain-language notes. Every value is placed through the CSSOM
// (setProperty) or textContent; nothing here writes a style="" attribute or API markup.
import { fmtDate, pct1, fmtInt, Word, joinAnd, seasonLabel, FEATURE_COUNT, PANDEMIC_2019_20_GAMES, FULL_SEASON_GAMES } from '../format.js';
import { motionOn, hasIO, onScrollFrame, replay } from '../reveal.js';

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const num = n => fmtInt(n);
const isNum = v => typeof v === 'number' && Number.isFinite(v);

// Everything the copy needs, derived once from training.seasons.
function describe(t) {
  const seasons = (t.seasons || []).filter(s => s && s.games > 0);
  const split = seasons.find(s => s.train > 0 && s.test > 0) || null;
  const testOnly = seasons.filter(s => s.train === 0 && s.test > 0);
  const trainOnly = seasons.filter(s => s.test === 0);
  const first = seasons.length ? seasonLabel(seasons[0].season) : '';
  return {
    seasons, split, testOnly, trainOnly,
    first,
    splitLabel: split ? seasonLabel(split.season) : '',
    testOnlyLabels: joinAnd(testOnly.map(s => seasonLabel(s.season)))
  };
}

function headCopy(t, d) {
  const W = t.rolling_window || 10;
  const date = fmtDate(t.cutoff_date);
  let split;
  if (d.split && d.testOnly.length) {
    split = `Training stops ${date}. The ${num(d.split.test)} games after that in ${d.splitLabel} and all of ${d.testOnlyLabels} are kept for grading.`;
  } else if (d.split) {
    split = `Training stops ${date}. The ${num(d.split.test)} games after that in ${d.splitLabel} are kept for grading.`;
  } else {
    split = `Training stops ${date}. Every game after that, all of ${d.testOnlyLabels}, is kept for grading.`;
  }
  return {
    all: {
      k: '1 of 2 · everything it saw',
      t: `${num(t.games_total)} games, in date order`,
      x: `Every regular-season game since ${d.first} where both teams had ${W} games of history.`
    },
    split: {
      k: '2 of 2 · the games it never saw',
      t: `The newest ${num(t.test_games)} held back`,
      x: split
    }
  };
}

function stripLabel(t, d) {
  const N = d.seasons.length;
  const lead = `${Word(N)} seasons of games. `;
  if (d.split) {
    const late = d.testOnly.length ? `Late ${d.splitLabel} and all of ${d.testOnlyLabels}` : `Late ${d.splitLabel}`;
    return `${lead}${d.first} to early ${d.splitLabel} used for training, ${num(t.train_games)} games. ${late} used for testing, ${num(t.test_games)} games.`;
  }
  const lastTrain = d.trainOnly.length ? seasonLabel(d.trainOnly[d.trainOnly.length - 1].season) : d.first;
  const firstTest = d.testOnly.length ? seasonLabel(d.testOnly[0].season) : '';
  const lastTest = d.testOnly.length ? seasonLabel(d.testOnly[d.testOnly.length - 1].season) : '';
  const span = (a, b) => (a === b ? a : `${a} to ${b}`);
  return `${lead}${span(d.first, lastTrain)} used for training, ${num(t.train_games)} games. ${firstTest ? span(firstTest, lastTest) : 'None'} used for testing, ${num(t.test_games)} games.`;
}

function buildStrip(card, t, d) {
  const labels = el('div', 'slabels'), counts = el('div', 'scounts'), strip = el('div', 'seasons');
  labels.setAttribute('aria-hidden', 'true');
  counts.setAttribute('aria-hidden', 'true');
  strip.setAttribute('role', 'img');
  strip.setAttribute('aria-label', stripLabel(t, d));
  d.seasons.forEach((s, i) => {
    const g = String(s.games);
    const fullLabel = seasonLabel(s.season);
    const shortLabel = fullLabel.split('–').map(y => y.slice(-2)).join('–');
    const lab = el('span');
    lab.style.setProperty('--g', g);
    const lFull = el('b', 'l-full', fullLabel);
    const lShort = el('b', 'l-short', shortLabel);
    lab.append(lFull, lShort);

    const cnt = el('span');
    cnt.style.setProperty('--g', g);
    if (s.train > 0 && s.test > 0) {
      const cA = el('span', 'c-a', num(s.train));
      const cB = el('span', 'c-b', '+ ' + num(s.test));
      cnt.append(cA, document.createTextNode(' '), cB);
    } else {
      cnt.textContent = num(s.games);
    }

    const sz = el('span', 'sz');
    sz.style.setProperty('--g', g);
    sz.style.setProperty('--n', String(i));
    if (s.test === 0) { /* training only */ }
    else if (s.train === 0) sz.classList.add('test');
    else {
      sz.classList.add('split');
      const tr = el('span', 'tr'), te = el('span', 'te');
      tr.style.setProperty('--a', String(s.train));
      te.style.setProperty('--b', String(s.test));
      sz.append(tr, te);
    }
    labels.append(lab); counts.append(cnt); strip.append(sz);
  });
  return { labels, strip, counts };
}

function buildTable(d) {
  const table = el('table', 'sr');
  table.append(el('caption', null, 'Games per season'));
  const hr = el('tr');
  ['Season', 'Games', 'Training', 'Test'].forEach(h => { const th = el('th', null, h); th.scope = 'col'; hr.append(th); });
  table.append(el('thead')); table.tHead.append(hr);
  const body = el('tbody');
  d.seasons.forEach(s => {
    const tr = el('tr');
    const th = el('th', null, seasonLabel(s.season)); th.scope = 'row';
    tr.append(th, el('td', null, num(s.games)), el('td', null, num(s.train)), el('td', null, num(s.test)));
    body.append(tr);
  });
  table.append(body);
  return table;
}

function buildNums(t) {
  const dl = el('dl', 'nums');
  const cells = [
    [num(t.games_total), 'games with full history'],
    [num(t.train_games), 'to learn from'],
    [num(t.test_games), 'to grade it'],
    [String(FEATURE_COUNT), 'numbers per game'],
    [isNum(t.home_win_rate) ? pct1(t.home_win_rate) + '%' : '—', 'home teams won']
  ];
  cells.forEach(([v, l]) => {
    const div = el('div');
    div.append(el('dt', null, l), el('dd', null, v));
    dl.append(div);
  });
  return dl;
}

function buildNotes(t, d) {
  const notes = [];
  const W = t.rolling_window || 10;
  if (d.seasons.some(s => s.season === '2019-20')) {
    notes.push(['Why 2019–20 is short', `Each team needs ${W} games of history before its first row, so the data starts ${fmtDate(t.first_game_date)}; the pandemic then cut the season to ${num(PANDEMIC_2019_20_GAMES)} games.`]);
  }
  const s2021 = d.seasons.find(s => s.season === '2020-21');
  if (s2021) {
    notes.push(['Why 2020–21 is short', `A ${Math.round(s2021.games * 2 / 30)}-game season: ${num(s2021.games)} games instead of ${num(FULL_SEASON_GAMES)}.`]);
  }
  notes.push(['Why split by date', "Shuffling would let the model peek at the future. Splitting by date means it's graded the way it's used: on games that haven't happened yet."]);
  const wrap = el('div', 'notes3');
  wrap.style.setProperty('--n', String(notes.length));
  notes.forEach(([b, text]) => {
    const p = el('p');
    p.append(el('b', null, b), document.createTextNode(text));
    wrap.append(p);
  });
  return wrap;
}

function checkSums(t, d) {
  const sum = k => d.seasons.reduce((a, s) => a + (s[k] || 0), 0);
  if (sum('games') !== t.games_total || sum('train') !== t.train_games || sum('test') !== t.test_games) {
    console.warn('model: season totals do not match training totals', { games: sum('games'), train: sum('train'), test: sum('test') }, t);
  }
}

function buildScrolly(t, d, copy) {
  const F = t.games_total > 0 ? (t.train_games / t.games_total) * 100 : 100;
  const noTest = !(t.test_games > 0) || F >= 100;
  const motion = motionOn() && hasIO() && !noTest;

  const scrolly = el('div', 'scrolly s2'); scrolly.setAttribute('data-scrolly2', '');
  const pin = el('div', 'pin2'); pin.setAttribute('data-state', 'all');
  const card = el('div', 'card s2card');

  // Head
  const head = el('div', 's2head'); head.setAttribute('aria-live', 'polite');
  const kick = el('span', 'pin__k');
  const dashes = [el('i'), el('i')];
  dashes.forEach(i => i.setAttribute('aria-hidden', 'true'));
  const kText = el('span'); kText.setAttribute('data-s2k', '');
  kick.append(dashes[0], dashes[1], kText);
  const h3 = el('h3'), px = el('p');
  h3.setAttribute('data-s2t', ''); px.setAttribute('data-s2x', '');
  head.append(kick, h3, px);

  // Flag
  const flag = el('div', 'splitflag'); flag.setAttribute('aria-hidden', 'true');
  const fi = el('i', null, `${fmtDate(t.cutoff_date)} · training stops here`);
  fi.style.setProperty('left', `calc(${Math.round(F * 1000) / 1000}% + 3px)`);
  flag.append(fi);
  if (noTest) flag.hidden = true;

  const { labels, strip, counts } = buildStrip(card, t, d);

  const legend = el('div', 'legend'); legend.setAttribute('aria-hidden', 'true');
  const l1 = el('span'); l1.append(el('i', 'lg-p'), document.createTextNode('Training games'));
  legend.append(l1);
  if (!noTest) {
    const l2 = el('span', 'lg-test'); l2.append(el('i', 'lg-h'), document.createTextNode('Test games (held back)'));
    legend.append(l2);
  }

  card.append(head, flag, strip, labels, counts, legend, buildTable(d));
  pin.append(card);
  scrolly.append(pin);

  // Check for overflow on narrow widths and hide labels/counts that don't fit
  const checkOverflow = () => {
    if (window.innerWidth > 560) return;
    const labelSpans = labels.querySelectorAll('span');
    const countSpans = counts.querySelectorAll('span');
    labelSpans.forEach(span => {
      if (span.scrollWidth > span.clientWidth + 1) {
        span.style.setProperty('visibility', 'hidden');
      }
    });
    countSpans.forEach(span => {
      if (span.scrollWidth > span.clientWidth + 1) {
        span.style.setProperty('visibility', 'hidden');
      }
    });
  };
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { setTimeout(checkOverflow, 0); });
  } else {
    setTimeout(checkOverflow, 100);
  }

  // State handling
  let state = null;
  const write = k => {
    kText.textContent = copy[k].k; h3.textContent = copy[k].t; px.textContent = copy[k].x;
    dashes[0].classList.add('on');
    dashes[1].classList.toggle('on', k === 'split');
  };
  const set2 = k => {
    if (k === state) return;
    const first = state === null;      // the first state shown (even mid-section) never plays the swap
    state = k;
    pin.dataset.state = k;
    write(k);
    if (!first) { replay(h3, 'swap'); replay(px, 'swap'); }
  };

  if (!motion) {
    // Reduced motion, no IntersectionObserver, or no test set: the final state, nothing listening.
    scrolly.classList.add('flat');
    pin.classList.add('lit');
    set2(noTest ? 'all' : 'split');
    return scrolly;
  }

  // Head height reservation: measure both states in an off-screen clone.
  let lastW = -1;
  const reserve = () => {
    const w = head.offsetWidth;
    if (!w || w === lastW) return;
    lastW = w;
    const probe = head.cloneNode(true);
    probe.removeAttribute('aria-live');
    probe.classList.add('s2head--probe');
    probe.style.setProperty('width', w + 'px');
    probe.style.setProperty('min-height', '0px');
    card.append(probe);
    const pk = probe.querySelector('[data-s2k]'), pt = probe.querySelector('[data-s2t]'), pp = probe.querySelector('[data-s2x]');
    let max = 118;
    ['all', 'split'].forEach(k => {
      pk.textContent = copy[k].k; pt.textContent = copy[k].t; pp.textContent = copy[k].x;
      max = Math.max(max, probe.offsetHeight);
    });
    probe.remove();
    head.style.setProperty('min-height', max + 'px');
  };

  const on2 = () => {
    const r = scrolly.getBoundingClientRect();
    const range = r.height - innerHeight;
    const p = range > 0 ? Math.min(1, Math.max(0, -r.top / range)) : 1;
    if (r.top < innerHeight * 0.75) pin.classList.add('lit');
    reserve();
    set2(p > 0.35 ? 'split' : 'all');
  };

  on2();
  onScrollFrame(on2);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { lastW = -1; reserve(); });
  return scrolly;
}

export function initSeasons(section, model) {
  const body = section.querySelector('[data-body]');
  const lede = section.querySelector('[data-lede]');
  if (!body) return null;
  body.textContent = '';
  model = model || {};
  const t = model.training && Array.isArray(model.training.seasons) && model.training.seasons.length ? model.training : null;
  const mount = el('div'); mount.setAttribute('data-rowcard-mount', '');

  if (!t) {
    const cutoff = (model.training && model.training.cutoff_date) || model.cutoff_date || null;
    const games = model.test && isNum(model.test.games) ? model.test.games : (model.training && model.training.test_games);
    if (!cutoff || !isNum(games)) return null;
    if (lede) lede.textContent = `The model learned from every game before ${fmtDate(cutoff)} and was graded on the ${num(games)} games after it. It never saw the graded games while learning.`;
    body.append(mount);
    return { rowCardMount: mount };
  }

  const d = describe(t);
  if (!d.seasons.length) return null;
  checkSums(t, d);
  const trainPct = t.games_total > 0 ? Math.round((t.train_games / t.games_total) * 100) : 80;
  if (lede) lede.textContent = `Every regular-season game since the ${d.first} season, in date order. The oldest ${trainPct}% taught the model; the newest ${100 - trainPct}% graded it. It never saw the graded games while learning.`;

  body.append(buildScrolly(t, d, headCopy(t, d)), buildNums(t), buildNotes(t, d), mount);
  return { rowCardMount: mount };
}
