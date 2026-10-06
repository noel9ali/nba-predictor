// Calibration dot plot shared by the Tonight card (T17) and Model chapter 6 (no animation, M9).
// SVG geometry is written as attributes; --k per dot through the CSSOM.
import { fmt, esc } from './format.js';

export const bucketLabel = b => String(b).split('-').map(x => String(Math.round(parseFloat(x) * 100))).join('–');

export function calibrationAriaLabel(buckets, variant) {
  const lead = variant === 'chapter'
    ? "Calibration of this season's picks: predicted vs actual win rate by bucket."
    : 'Calibration: predicted vs actual win rate by probability bucket.';
  return lead + buckets.map(b => ' ' + bucketLabel(b.bucket) + '%: predicted ' + fmt.pct(b.predicted) + ', won ' + fmt.pct(b.actual) + ' of ' + b.n + ' picks;').join('');
}

const r2 = v => Math.round(v * 10) / 10;

export function renderCalibration(host, buckets, { variant }) {
  const list = (buckets || []).filter(b => b && b.predicted != null && b.actual != null)
    .sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)));
  if (!list.length) {
    host.innerHTML = '<p class="chart-empty">Not enough picks to chart yet.</p>';
    return { W: 0 };
  }
  const card = variant === 'card';
  const W = card ? Math.max(260, host.clientWidth || 340) : 560;
  const H = card ? Math.round(W * 0.72) : 380;
  const pad = card ? { l: 44, r: 12, t: 12, b: 34 } : { l: 48, r: 16, t: 16, b: 44 };
  const xMax = card ? 0.85 : 0.8;
  const clampX = v => Math.min(xMax, Math.max(0.5, v)), clampY = v => Math.min(1, Math.max(0.4, v));
  const cx = v => pad.l + (clampX(v) - 0.5) * (W - pad.l - pad.r) / (xMax - 0.5);
  const cy = v => pad.t + (1 - clampY(v)) * (H - pad.t - pad.b) / 0.6;
  let s = '';
  [0.4, 0.6, 0.8, 1].forEach(v => {
    s += '<line class="gridl" x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + r2(cy(v)) + '" y2="' + r2(cy(v)) + '"/>' +
      '<text class="ax" x="' + (card ? pad.l - 6 : 40) + '" y="' + r2(cy(v) + 4) + '" text-anchor="end">' + Math.round(v * 100) + '%</text>';
  });
  [0.5, 0.6, 0.7, 0.8].forEach(v => {
    s += '<text class="ax" x="' + r2(cx(v)) + '" y="' + (card ? H - 16 : H - pad.b + 18) + '" text-anchor="middle">' + Math.round(v * 100) + '%</text>';
  });
  s += '<line class="diag" stroke-dasharray="' + (card ? '4 4' : '5 5') + '" x1="' + r2(cx(0.5)) + '" y1="' + r2(cy(0.5)) + '" x2="' + r2(cx(xMax)) + '" y2="' + r2(cy(xMax)) + '"/>';
  if (!card) s += '<text class="ax" x="' + r2(cx(0.79)) + '" y="' + r2(cy(0.8) - 8) + '" text-anchor="end">perfect</text>';
  list.forEach(b => {
    const rr = card ? Math.min(16, 4 + Math.sqrt(b.n) * 0.9) : Math.min(22, 5 + Math.sqrt(b.n) * 1.1);
    const title = bucketLabel(b.bucket) + '%: ' + (card ? 'predicted ' : 'said ') + fmt.pct(b.predicted) + ', won ' + fmt.pct(b.actual) + ' of ' + b.n;
    s += '<circle class="dot" cx="' + r2(cx(b.predicted)) + '" cy="' + r2(cy(b.actual)) + '" r="' + rr.toFixed(1) + '"><title>' + esc(title) + '</title></circle>';
    if (!card) {
      const x = cx(b.predicted), right = x + 12 + rr + 10 > 556;
      s += '<text class="lb" x="' + r2(right ? x - 12 - rr : x + 12 + Math.sqrt(b.n) * 1.1) + '" y="' + r2(cy(b.actual) + 4) + '"' + (right ? ' text-anchor="end"' : '') + '>' + b.n + '</text>';
    }
  });
  s += '<text class="ax" x="' + r2((pad.l + W - pad.r) / 2) + '" y="' + (H - (card ? 2 : 6)) + '" text-anchor="middle">' +
    (card ? 'Model said · dot size = picks' : 'What the model said · dot size and label = number of picks') + '</text>';
  const size = card ? ' width="' + W + '" height="' + H + '"' : '';
  host.innerHTML = '<svg class="' + (card ? 'calib-svg' : 'cal-svg') + '" viewBox="0 0 ' + W + ' ' + H + '"' + size + ' role="img" aria-label="' + esc(calibrationAriaLabel(list, variant)) + '">' + s + '</svg>';
  if (card) host.querySelectorAll('.dot').forEach((d, i) => d.style.setProperty('--k', String(i)));
  return { W };
}
