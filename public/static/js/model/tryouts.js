// Chapter 5, "Six models tried out": rank bump chart, leaderboard table, "why" card.
// initTryouts(section, model) -> true if rendered, false if fewer than 2 usable rows / 2 columns.
import { observeReveals } from '../reveal.js';
import { esc, fmtInt, Word, word, ord, joinAnd, modelLabel } from '../format.js';

const isNum = v => typeof v === 'number' && Number.isFinite(v);
const r2 = v => String(Math.round(v * 100) / 100);

const COLS = [
  { key: 'accuracy', head: 'Accuracy', short: 'Acc.', name: 'accuracy', higher: true, sub: 'higher is better', f: v => (v * 100).toFixed(1) + '%' },
  { key: 'brier_score', head: 'Brier', short: 'Brier', name: 'Brier', higher: false, sub: 'lower is better', f: v => v.toFixed(3) },
  { key: 'log_loss', head: 'Log loss', short: 'Log loss', name: 'log loss', higher: false, sub: 'lower is better', f: v => v.toFixed(3) },
  { key: 'roc_auc', head: 'AUC', short: 'AUC', name: 'AUC', higher: true, sub: 'higher is better', f: v => v.toFixed(3) }
];

const norm = s => String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]/g, '');

function findProduction(rows, productionModel) {
  const flagged = rows.find(r => r.is_production === true);
  if (flagged) return flagged;
  const p = norm(productionModel);
  if (!p) return null;
  let best = null, bestLen = -1;
  const take = (test) => {
    rows.forEach(r => {
      const n = norm(r.model);
      if (n && test(n) && n.length > bestLen) { best = r; bestLen = n.length; }
    });
    return best;
  };
  return take(n => n === p) || take(n => p.endsWith(n)) || take(n => n.endsWith(p));
}

const ceil1 = x => Math.ceil(x * 10 - 1e-9) / 10;

function familyOf(key) {
  const k = String(key).toLowerCase().replace(/^legacy-/, '').replace(/^(calibrated|current)-/, '');
  const map = { logistic: 'logistic', 'gradient-boosting': 'gradient boosting', 'random-forest': 'random forest', lstm: 'LSTM', xgboost: 'XGBoost' };
  return Object.prototype.hasOwnProperty.call(map, k) ? map[k] : k.replace(/[-_]+/g, ' ');
}

function abbreviate(name) {
  return name.replace(/^Calibrated /, 'Cal. ').replace('Gradient boosting', 'Grad. boost').replace('Random forest', 'Rand. forest');
}

function rankMatrix(rows, cols) {
  const ranks = rows.map(() => []);
  cols.forEach((c, j) => {
    const order = rows.map((r, i) => i).sort((a, b) => {
      const d = rows[a][c.key] - rows[b][c.key];
      return d === 0 ? a - b : (c.higher ? -d : d);
    });
    order.forEach((i, pos) => { ranks[i][j] = pos + 1; });
  });
  return ranks;
}

export function whyCopy(rows, cols, ranks, prodIdx, model) {
  const N = rows.length;
  const ib = cols.findIndex(c => c.key === 'brier_score'), ia = cols.findIndex(c => c.key === 'accuracy');
  const il = cols.findIndex(c => c.key === 'log_loss');
  if (ib < 0 || ia < 0) return '';
  const prod = rows[prodIdx];
  const rBrier = ranks[prodIdx][ib];
  const out = [];

  // Check if production ranks 1st on log loss
  const rLL = il >= 0 ? ranks[prodIdx][il] : 0;
  if (rLL === 1) {
    out.push('It has the best log loss of the ' + word(N) + ', the score the training run ranks models by.');
  }

  const brierPart = rBrier === 1 ? 'It has the best Brier score of the ' + word(N) : 'Its Brier score ranks ' + ord(rBrier) + ' of the ' + word(N);
  const bestAcc = Math.max.apply(null, rows.map(r => r.accuracy));
  const gap = (bestAcc - prod.accuracy) * 100;
  const accPart = gap < 1e-9 ? 'and has the best accuracy'
    : gap <= 1 ? 'and sits within ' + ceil1(gap) + ' points of the best accuracy'
      : 'but trails the best accuracy by ' + gap.toFixed(1) + ' points';
  out.push(brierPart + ' ' + accPart + '.');

  if (/logistic/i.test(model.production_model || prod.model)) {
    out.push("It's also the one whose answer can be explained input by input, which this page depends on.");
  }
  if (rLL > rBrier) {
    out.push('It ranks ' + (rLL === N ? 'last' : ord(rLL)) + " on log loss because it's occasionally more confident than it should be.");
  }
  return out.join(' ');
}

export function initTryouts(section, model) {
  const body = section && section.querySelector('[data-body]');
  const lb = model && Array.isArray(model.leaderboard) ? model.leaderboard : null;
  if (!body || !lb) return false;

  const rows = lb.filter(r => r && r.model != null && r.model !== '').map(r => Object.assign({}, r, { name: modelLabel(r.model) }));
  if (rows.length < 2) return false;
  const cols = COLS.filter(c => rows.every(r => isNum(r[c.key])));
  if (cols.length < 2) return false;
  const hasCal = rows.every(r => isNum(r.calibration_ece));
  const N = rows.length;
  const C = cols.length;
  const ranks = rankMatrix(rows, cols);
  const prod = findProduction(rows, model.production_model);
  const prodIdx = prod ? rows.indexOf(prod) : -1;

  // Test games: the rows' own count when they all agree, else the model-level one.
  const tg = rows.map(r => r.test_games);
  const testGames = tg.every(v => isNum(v) && v === tg[0]) ? tg[0]
    : (model.test && isNum(model.test.games) ? model.test.games : null);

  // Head
  const h2 = section.querySelector('h2');
  if (h2) h2.textContent = Word(N) + ' models tried out';
  const lede = section.querySelector('[data-lede]');
  if (lede) {
    const accCol = cols.find(c => c.key === 'accuracy');
    let spread = null;
    if (accCol) { const v = rows.map(r => r.accuracy); spread = (Math.max.apply(null, v) - Math.min.apply(null, v)) * 100; }
    lede.textContent = 'The training run fits ' + word(N) + ' kinds of model on the same games and grades them on the same ' +
      (testGames != null ? fmtInt(testGames) + ' ' : '') + 'test games.' +
      (spread != null && spread < 2 ? ' They finish close together: the hard part is the data, not the algorithm.' : '');
  }

  // ---- markup ----
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML =
    '<h3 class="bh">Finishing order on each test</h3>' +
    '<p class="cap">1st is best on every column. Hover a line for exact scores.</p>' +
    '<div class="bump rv" data-bump data-reveal></div>' +
    '<div class="tblwrap"><table class="board-tbl"><caption class="sr">Test-set scores for each model</caption>' +
    '<thead><tr><th scope="col">Model</th>' + cols.map(c => '<th scope="col">' + esc(c.head) + '</th>').join('') +
    (hasCal ? '<th scope="col">Calib. error</th>' : '') + '</tr></thead><tbody data-tbl></tbody></table></div>';
  const host = card.querySelector('[data-bump]');
  const tblwrap = card.querySelector('.tblwrap');

  // ---- table ----
  const bestOf = (key, higher) => {
    const v = rows.map(r => r[key]);
    return higher ? Math.max.apply(null, v) : Math.min.apply(null, v);
  };
  const tcols = cols.map(c => ({ key: c.key, f: c.f, best: bestOf(c.key, c.higher) }));
  if (hasCal) tcols.push({ key: 'calibration_ece', f: v => v.toFixed(3), best: bestOf('calibration_ece', false) });
  card.querySelector('[data-tbl]').innerHTML = rows.map((r, i) =>
    '<tr' + (i === prodIdx ? ' class="prod"' : '') + '><th scope="row">' + esc(r.name) + (i === prodIdx ? ' · live' : '') + '</th>' +
    tcols.map(c => '<td' + (r[c.key] === c.best ? ' class="best"' : '') + '>' + esc(c.f(r[c.key])) + '</td>').join('') + '</tr>').join('');

  // ---- why card ----
  let why = null;
  if (prodIdx >= 0) {
    const copy = whyCopy(rows, cols, ranks, prodIdx, model);
    if (copy) {
      why = document.createElement('div');
      why.className = 'why';
      why.setAttribute('data-why', '');
      const t = document.createElement('h3');
      t.textContent = 'Why the ' + familyOf(prod.model) + ' model has the job';
      const p = document.createElement('p');
      p.textContent = copy;
      why.append(t, p);
    }
  }

  body.textContent = '';
  body.append(card);
  if (why) body.append(why);

  // ---- chart ----
  const ariaLabel = 'Rank of each model on ' + joinAnd(cols.map(c => c.name)) + '.' +
    (prodIdx >= 0 ? ' ' + prod.name + ' ranks ' + joinAnd(ranks[prodIdx].map(ord)) + '.' : '');

  let drawnW = 0;
  function drawBump() {
    const W = Math.max(300, Math.round(host.clientWidth));
    drawnW = W;
    const narrow = W < 560;
    const H = narrow ? 300 : 350, L = narrow ? 96 : 170, R = narrow ? 24 : 170, T = narrow ? 40 : 58, B = narrow ? 16 : 30;
    const cx = j => L + j * (W - L - R) / (C - 1);
    const ry = r => T + (r - 1) * (H - T - B) / (N - 1);
    const label = r => (narrow ? abbreviate(r.name) : r.name);
    let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(ariaLabel) + '" focusable="false">';
    for (let r = 1; r <= N; r++) s += '<line class="gl" x1="' + r2(cx(0)) + '" x2="' + r2(cx(C - 1)) + '" y1="' + r2(ry(r)) + '" y2="' + r2(ry(r)) + '"/>';
    cols.forEach((c, j) => {
      s += '<text class="col" x="' + r2(cx(j)) + '" y="18" text-anchor="middle">' + esc(narrow ? c.short : c.head) + '</text>';
      if (!narrow) s += '<text class="colsub" x="' + r2(cx(j)) + '" y="34" text-anchor="middle">' + esc(c.sub) + '</text>';
    });
    if (!narrow) for (let r = 1; r <= N; r++) s += '<text class="rk" x="' + r2(cx(0) - L + 8) + '" y="' + r2(ry(r) + 5) + '">' + r + '</text>';
    const order = rows.map((r, i) => i).filter(i => i !== prodIdx);
    if (prodIdx >= 0) order.push(prodIdx);
    order.forEach(i => {
      const r = rows[i], isProd = i === prodIdx;
      s += '<g' + (isProd ? ' class="prod"' : '') + '><title>' + esc(r.name + ': ' + cols.map(c => c.head + ' ' + c.f(r[c.key])).join(', ')) + '</title>';
      s += '<path class="ln" pathLength="1" d="' + cols.map((c, j) => (j ? 'L' : 'M') + r2(cx(j)) + ',' + r2(ry(ranks[i][j]))).join('') + '"/>';
      cols.forEach((c, j) => {
        const rk = ranks[i][j];
        s += '<circle class="nd" cx="' + r2(cx(j)) + '" cy="' + r2(ry(rk)) + '" r="' + (isProd ? 7 : 5) + '"/>';
        if (isProd && !narrow) {
          s += '<text class="vl" x="' + r2(cx(j)) + '" y="' + r2(rk === N ? ry(rk) + 24 : ry(rk) - 13) + '" text-anchor="middle">' + esc(c.f(r[c.key])) + '</text>';
        }
      });
      s += '<text class="nm" x="' + r2(cx(0) - 14) + '" y="' + r2(ry(ranks[i][0]) + 4) + '" text-anchor="end">' + esc(label(r)) + '</text>';
      if (!narrow) s += '<text class="nm" x="' + r2(cx(C - 1) + 14) + '" y="' + r2(ry(ranks[i][C - 1]) + 4) + '">' + esc(r.name) + '</text>';
      s += '</g>';
    });
    host.innerHTML = s + '</svg>';
  }

  function checkScroll() {
    const over = tblwrap.scrollWidth > tblwrap.clientWidth;
    if (over) {
      tblwrap.setAttribute('tabindex', '0');
      tblwrap.setAttribute('role', 'region');
      tblwrap.setAttribute('aria-label', 'Model scores');
    } else {
      tblwrap.removeAttribute('tabindex');
      tblwrap.removeAttribute('role');
      tblwrap.removeAttribute('aria-label');
    }
  }

  drawBump();
  checkScroll();
  observeReveals(body);

  const onSize = () => {
    const w = Math.max(300, Math.round(host.clientWidth));
    if (Math.abs(w - drawnW) > 30) drawBump();
    checkScroll();
  };
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(onSize).observe(host);
  else window.addEventListener('resize', onSize, { passive: true });
  return true;
}
