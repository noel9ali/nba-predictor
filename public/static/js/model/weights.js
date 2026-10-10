// Chapter 4, "What it leans on": ranked share-of-weight bars plus one dashed "other" bar.
// initWeights(section, model) -> true if rendered, false if feature_importance is unusable.
import { observeReveals } from '../reveal.js';
import { pct1, FEATURE_COUNT } from '../format.js';

const isNum = v => typeof v === 'number' && Number.isFinite(v);

const ELO_LABELS = { ELO_DIFF: 'Rating gap', HOME_ELO: "Home team's rating", AWAY_ELO: "Away team's rating", REST_DIFF: 'Rest gap' };
const STAT_WORDS = { PTS: 'points', FG_PCT: 'FG%', REB: 'rebounds', AST: 'assists', TOV: 'turnovers', STOCKS: 'steals + blocks' };

function fallbackLabel(feature, win) {
  if (Object.prototype.hasOwnProperty.call(ELO_LABELS, feature)) return ELO_LABELS[feature];
  const m = /^(HOME|AWAY)_roll_(PTS|FG_PCT|REB|AST|TOV|STOCKS)$/.exec(feature);
  if (m) return (m[1] === 'HOME' ? 'Home' : 'Away') + ' ' + STAT_WORDS[m[2]] + ', last ' + win;
  return feature;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function row(label, small, share, extra) {
  const li = el('li', 'w' + (extra ? ' ' + extra : ''));
  const nm = el('span', 'nm');
  nm.append(document.createTextNode(label), el('small', '', small));
  // Add sr-only value for screen readers
  const sr = el('span', 'sr', pct1(share) + '%');
  nm.append(sr);
  const tr = el('span', 'tr');
  tr.setAttribute('aria-hidden', 'true');
  const bar = document.createElement('i');
  bar.style.setProperty('width', Math.min(100, Math.max(0, share * 100)) + '%');
  const val = el('span', 'val', pct1(share) + '%');
  // Position value at bar end (inside track), or deeper inside bar if share > 0.82
  // When share <= 0.82, position at bar end but align right edge of value with track right edge
  // minus 8px to ensure it fits
  const shareNum = Math.min(1, Math.max(0, share));
  const pct = shareNum * 100;
  val.style.setProperty('position', 'absolute');
  if (shareNum > 0.82) {
    // Inside bar case: position right edge 8px from bar end
    val.style.setProperty('right', 'calc(100% - ' + pct + '% + 8px)');
    val.style.setProperty('left', 'auto');
  } else {
    // Outside bar case: position left edge 8px from bar end, but keep within track
    // Use max() to ensure it doesn't overflow: max(left_pos, track_right - value_width_estimate)
    val.style.setProperty('left', 'calc(' + pct + '% + 8px)');
    val.style.setProperty('right', 'auto');
  }
  tr.append(bar, val);
  li.append(nm, tr);
  return li;
}

export function initWeights(section, model) {
  const body = section && section.querySelector('[data-body]');
  const fi = model && Array.isArray(model.feature_importance) ? model.feature_importance : null;
  if (!body || !fi) return false;

  const win = (model.training && isNum(model.training.rolling_window)) ? model.training.rolling_window : 10;
  let warned = false;
  const abs = r => {
    if (r.share < 0 && !warned) { warned = true; console.warn('feature_importance: negative share, using abs'); }
    return Math.abs(r.share);
  };
  const ranked = fi
    .filter(r => r && r.feature !== 'other' && isNum(r.share))
    .map(r => ({ feature: String(r.feature), label: r.label ? String(r.label) : fallbackLabel(String(r.feature), win), share: abs(r) }))
    .sort((a, b) => b.share - a.share);
  if (!ranked.length || ranked.every(r => r.share === 0)) return false;

  const otherRow = fi.find(r => r && r.feature === 'other' && isNum(r.share));
  const otherShare = otherRow ? Math.max(0, otherRow.share) : null;
  const sum = ranked.reduce((s, r) => s + r.share, 0) + (otherShare || 0);
  if (otherRow && Math.abs(sum - 1) > 0.01) console.warn('feature_importance: shares sum to ' + sum.toFixed(3));

  // Lede
  const ratingShare = ranked.filter(r => /ELO/i.test(r.feature)).reduce((s, r) => s + r.share, 0);
  const lede = section.querySelector('[data-lede]');
  if (lede) {
    lede.textContent = "How much each input moves the model's answer, as a share of the total. " +
      (ratingShare >= 0.5
        ? 'Ratings do most of the work; recent form fine-tunes.'
        : ranked[0].label + ' leads at ' + pct1(ranked[0].share) + '%; the rest of the weight is spread across the other inputs.');
  }

  // Card
  const card = el('div', 'card');
  const list = el('ol', 'wts rv');
  list.setAttribute('data-reveal', '');
  list.setAttribute('aria-label', "How much each input moves the model's answer, largest first");
  ranked.forEach(r => list.append(row(r.label, r.feature, r.share)));
  if (otherRow) {
    const n = FEATURE_COUNT - ranked.length;
    list.append(row(n >= 1 ? 'The other ' + n + ' inputs' : 'The other inputs', 'form, shooting, rest', otherShare, 'other'));
  }
  card.append(list, el('p', 'cap', "Grid lines every 10%. From the training run's feature-importance output (model_leaderboard.csv)."));
  body.textContent = '';
  body.append(card);
  observeReveals(body);
  return true;
}
