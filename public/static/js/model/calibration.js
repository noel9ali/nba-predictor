// Chapter 6: the calibration dot plot (no animation, M9) plus the two summary stats.
import { renderCalibration, bucketLabel } from '../calibration-chart.js';

function productionRow(model) {
  const rows = (model.leaderboard || []).filter(r => r && r.model);
  const flagged = rows.find(r => r.is_production === true);
  if (flagged) return flagged;
  const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const p = norm(model.production_model);
  const hits = rows.filter(r => norm(r.model) === p || p.endsWith(norm(r.model)) || norm(r.model).endsWith(p));
  return hits.sort((a, b) => norm(b.model).length - norm(a.model).length)[0] || null;
}

function stat(big, small) {
  const d = document.createElement('div'), b = document.createElement('b'), s = document.createElement('span');
  b.textContent = big; s.textContent = small;
  d.append(b, s);
  return d;
}

export function initCalibration(section, model) {
  const body = section.querySelector('[data-body]');
  body.textContent = '';
  const card = document.createElement('div'); card.className = 'card';
  const cal = document.createElement('div'); cal.className = 'cal';
  const plot = document.createElement('div'); plot.dataset.cal = '';
  const sum = document.createElement('div'); sum.className = 'sum';
  cal.append(plot, sum); card.append(cal); body.append(card);
  renderCalibration(plot, model.calibration || [], { variant: 'chapter' });
  const prod = productionRow(model);
  const ece = prod && prod.calibration_ece != null ? prod.calibration_ece : null;
  if (ece != null) {
    const n = Math.round(ece * 100);
    sum.append(stat(ece.toFixed(3), 'average calibration error on the test set: its probabilities are ' +
      (n === 0 ? 'off by less than a point.' : 'off by about ' + n + (n === 1 ? ' point.' : ' points.'))));
  }
  const live = model.season_live || {};
  const sparse = (model.calibration || []).find(b => b.n < 20);
  sum.append(stat(String(live.picks ?? 0), 'live picks this season.' +
    (sparse ? ' Buckets with fewer than 20 picks swing a lot; ' + bucketLabel(sparse.bucket) + '% has only ' + sparse.n + '.' : '')));

  // Add ResizeObserver for chapter variant to re-render on width changes > 8px
  let lastWidth = plot.clientWidth;
  const ro = new ResizeObserver(() => {
    const newWidth = plot.clientWidth;
    if (Math.abs(newWidth - lastWidth) > 8) {
      lastWidth = newWidth;
      renderCalibration(plot, model.calibration || [], { variant: 'chapter' });
    }
  });
  ro.observe(plot);

  return true;
}
