// Chapter 1, "Every pick so far": season switcher, six-cell board, two compare cards.
// initAlltime(section, { model, perfAll }) -> { setModel(model) } | null (perfAll unusable).
import { api } from '../api.js';
import { renderBoard, signCls } from '../board.js';
import { compareCourt, updateCompareCourt } from '../court.js';
import { observeReveals } from '../reveal.js';
import { fmt, fmtInt, pct1, MINUS, parseWL, seasonLabel, kellyNoun, KELLY_FRACTION, MAX_STAKE } from '../format.js';

const NDASH = '–';
const isNum = v => typeof v === 'number' && Number.isFinite(v);
const plural = (n, one, many) => (n === 1 ? one : many);

function el(tag, attrs, text) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}

function makeCard(host, key, title) {
  const card = el('div', { class: 'card', 'data-card': key });
  const copy = el('p');
  copy.setAttribute('data-copy', '');
  const cap = el('p', { class: 'cap' });
  cap.setAttribute('data-cap', '');
  card.append(el('h3', null, title), copy, cap);
  host.append(card);
  return { card, copy, cap, strip: null };
}

// Show the strip (creating it on first use) or hide it.
function setStrip(c, spec) {
  if (!spec) { if (c.strip) c.strip.hidden = true; return; }
  if (!c.strip) {
    c.strip = compareCourt(spec);
    c.card.insertBefore(c.strip, c.cap);
  } else {
    updateCompareCourt(c.strip, spec);
  }
  c.strip.hidden = false;
}

function setCap(c, text) {
  c.cap.textContent = text || '';
  c.cap.hidden = !text;
}

export function initAlltime(section, { model, perfAll } = {}) {
  const body = section && section.querySelector('[data-body]');
  if (!body || !perfAll || typeof perfAll !== 'object' || !perfAll.kpis) return null;

  const seasons = (Array.isArray(perfAll.seasons) ? perfAll.seasons.filter(s => typeof s === 'string' && s) : [])
    .slice().sort().reverse();

  // ---- markup (no API strings in the template; they go through textContent) ----
  body.textContent = '';
  const bar = el('div', { class: 'seasonbar', role: 'group', 'aria-label': 'Season' });
  bar.append(el('span', null, 'Season'));
  const buttons = new Map();
  const addBtn = (key, label) => {
    const b = el('button', { type: 'button', 'aria-pressed': key === 'all' ? 'true' : 'false' }, label);
    b.dataset.season = key;
    buttons.set(key, b);
    bar.append(b);
  };
  addBtn('all', 'All time');
  seasons.forEach(s => addBtn(s, seasonLabel(s)));

  const alertSlot = el('div');
  const status = el('p', { class: 'sr', role: 'status' });
  status.setAttribute('data-status', '');
  const board = el('dl', { class: 'board rv', 'aria-busy': 'false' });
  board.setAttribute('data-reveal', '');
  board.setAttribute('data-board', '');
  const vs = el('div', { class: 'vs rv' });
  vs.setAttribute('data-reveal', '');
  const live = makeCard(vs, 'live-vs-test', 'Live vs test');
  const bets = makeCard(vs, 'picks-vs-bets', 'Picks vs bets');
  body.append(bar, alertSlot, status, board, vs);
  observeReveals(body);

  // ---- state ----
  const cache = new Map([['all', perfAll]]);
  let current = perfAll, shown = 'all', token = 0, mdl = model || null;

  function renderCards(perf) {
    const k = perf.kpis || {};
    const [pw, pl] = parseWL(k.picks), [bw, bl] = parseWL(k.bets);
    const picksSettled = pw + pl, betsSettled = bw + bl;
    const noPicks = picksSettled === 0 || !isNum(k.accuracy);
    const picksP = noPicks ? null : Number(pct1(k.accuracy));
    const NONE = 'No settled picks yet. The strip appears once the first pick is graded.';

    // Card 1: live vs test
    live.card.hidden = !mdl;
    if (mdl) {
      const test = mdl.test || null;
      const testAcc = test && isNum(test.accuracy) ? test.accuracy : null;
      const testGames = test && isNum(test.games) ? test.games : null;
      if (noPicks) {
        live.copy.textContent = NONE;
        setStrip(live, null); setCap(live, '');
      } else if (testAcc == null) {
        live.copy.textContent = "Test-set accuracy isn't available right now.";
        setStrip(live, null);
        setCap(live, 'Live: ' + picksSettled + ' settled ' + plural(picksSettled, 'pick', 'picks') + '.');
      } else {
        const testP = Number(pct1(testAcc));
        const d = Math.round((testP - picksP) * 10) / 10;
        const gamesTxt = testGames != null ? fmtInt(testGames) : null;
        live.copy.textContent = d >= 0.1
          ? 'Live picks are running ' + d + ' points under the test set. Expect some drop: the test set was scored once, live picks face new rosters and injuries.'
          : d <= -0.1
            ? 'Live picks are running ' + Math.abs(d) + ' points above the test set. That is a short run: the test set covers ' + (gamesTxt || 'many') + ' games, live picks ' + picksSettled + '.'
            : 'Live picks are matching the test set.';
        setStrip(live, {
          subject: { label: 'Live', value: picksP / 100 },
          reference: { label: 'Test', value: testP / 100 },
          ariaLabel: 'Test ' + testP.toFixed(1) + ' percent, live ' + picksP.toFixed(1) + ' percent'
        });
        setCap(live, 'Live: ' + picksSettled + ' settled ' + plural(picksSettled, 'pick', 'picks') + '.' + (gamesTxt ? ' Test: ' + gamesTxt + ' games.' : ''));
      }
    }

    // Card 2: picks vs bets
    if (noPicks) {
      bets.copy.textContent = NONE;
      setStrip(bets, null); setCap(bets, '');
    } else if (betsSettled === 0) {
      bets.copy.textContent = "No bets placed yet in this view: the model only bets when its chance beats the market's.";
      setStrip(bets, null); setCap(bets, '');
    } else {
      const betsP = Number(pct1(bw / betsSettled));
      const share = betsSettled / picksSettled;
      const s1 = share >= 0.4 && share <= 0.6
        ? "It bets on about half its picks, only when its chance beats the market's."
        : 'It bets on about ' + Math.round(share * 100) + "% of its picks, only when its chance beats the market's.";
      const diff = Math.round((picksP - betsP) * 10) / 10;
      const s2 = diff >= 0.5
        ? "Bets win less often than picks because they're the closer calls where the price is good."
        : diff <= -0.5 ? 'Bets are winning more often than picks so far.' : 'Bets win about as often as picks.';
      bets.copy.textContent = s1 + ' ' + s2;
      setStrip(bets, {
        subject: { label: 'Bets', value: betsP / 100 },
        reference: { label: 'Picks', value: picksP / 100 },
        ariaLabel: 'Bets win ' + betsP.toFixed(1) + ' percent, picks ' + picksP.toFixed(1) + ' percent'
      });
      setCap(bets, betsSettled + ' settled ' + plural(betsSettled, 'bet', 'bets') + ', ' + kellyNoun(KELLY_FRACTION) + '-Kelly, never more than ' + Math.round(MAX_STAKE * 100) + '% of the bankroll.');
    }
  }

  function renderBoardCells(perf) {
    const k = perf.kpis || {};
    const [pw, pl] = parseWL(k.picks), [bw, bl] = parseWL(k.bets);
    const empty = pw + pl === 0;
    const staked = empty ? 0 : (isNum(k.staked) ? k.staked : 0);
    const net = isNum(k.net_pl) ? k.net_pl : 0;
    const dd = k.max_drawdown && isNum(k.max_drawdown.amount) ? k.max_drawdown.amount : 0;
    const cells = [
      { id: 'picks', label: 'Picks W–L', value: pw + NDASH + pl },
      { id: 'acc', label: 'Pick accuracy', value: isNum(k.accuracy) && !empty ? pct1(k.accuracy) + '%' : '—' },
      { id: 'bets', label: 'Bets W–L', value: bw + NDASH + bl },
      { id: 'staked', label: 'Staked', value: '$' + Math.round(staked).toLocaleString('en-US') },
      empty
        ? { id: 'pl', label: 'Profit · ROI', value: '$0.00' }
        : { id: 'pl', label: 'Profit · ROI', value: fmt.money(net, true), cls: signCls(net), small: isNum(k.roi) ? fmt.pts(k.roi) + '%' : undefined },
      { id: 'dd', label: 'Worst drawdown', value: !empty && dd > 0 ? MINUS + '$' + dd.toFixed(2) : '$0.00', cls: !empty && dd > 0 ? 'neg' : '' }
    ];
    renderBoard(board, cells);
  }

  function render(perf, key) {
    current = perf; shown = key;
    renderBoardCells(perf);
    renderCards(perf);
    const k = perf.kpis || {};
    const [pw, pl] = parseWL(k.picks);
    const label = key === 'all' ? 'All time' : seasonLabel(key);
    status.textContent = 'Showing ' + label + ': ' + pw + NDASH + pl + ' picks' +
      (isNum(k.accuracy) && pw + pl > 0 ? ', ' + pct1(k.accuracy) + '% right.' : '.');
  }

  function press(key) {
    buttons.forEach((b, k) => b.setAttribute('aria-pressed', k === key ? 'true' : 'false'));
  }
  function clearAlert() { alertSlot.textContent = ''; }

  async function select(key) {
    const my = ++token;
    press(key);
    if (cache.has(key)) {
      clearAlert();
      board.setAttribute('aria-busy', 'false');
      render(cache.get(key), key);
      return;
    }
    board.setAttribute('aria-busy', 'true');
    try {
      const perf = await api.performance(key);
      if (!perf || !perf.kpis) throw new Error('bad performance response');
      cache.set(key, perf);
      if (my !== token) return;
      clearAlert();
      board.setAttribute('aria-busy', 'false');
      render(perf, key);
    } catch (e) {
      if (my !== token) return;
      board.setAttribute('aria-busy', 'false');
      press(shown);
      alertSlot.textContent = '';
      alertSlot.append(el('p', { class: 'cap', role: 'alert' }, "Couldn't load that season. Try again."));
    }
  }

  buttons.forEach((b, key) => b.addEventListener('click', () => select(key)));
  render(perfAll, 'all');

  return {
    setModel(m) {
      mdl = m || null;
      renderCards(current);
    }
  };
}
