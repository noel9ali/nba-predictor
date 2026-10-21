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
  // Drawn at the host's real width (rendered 1:1, so text stays at its CSS size): the card caps at 420,
  // the chapter at 560.
  const W = Math.round(Math.min(card ? 420 : 560, Math.max(240, host.clientWidth || (card ? 340 : 560))));
  const H = card ? Math.round(W * 0.72) : Math.max(240, Math.round(W * 380 / 560));
  const pad = { l: 58, r: card ? 14 : 16, t: card ? 14 : 16, b: 56 };
  const xMax = card ? 0.85 : 0.8;
  const clampX = v => Math.min(xMax, Math.max(0.5, v)), clampY = v => Math.min(1, Math.max(0.4, v));
  const cx = v => pad.l + (clampX(v) - 0.5) * (W - pad.l - pad.r) / (xMax - 0.5);
  const cy = v => pad.t + (1 - clampY(v)) * (H - pad.t - pad.b) / 0.6;
  const bottom = H - pad.b;
  let s = '';
  [0.4, 0.6, 0.8, 1].forEach(v => {
    s += '<line class="gridl" x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + r2(cy(v)) + '" y2="' + r2(cy(v)) + '"/>' +
      '<text class="ax" x="' + (pad.l - 8) + '" y="' + r2(cy(v) + 4) + '" text-anchor="end">' + Math.round(v * 100) + '%</text>';
  });
  // x ticks sit 20px below the plot, so the "50%" tick clears the "40%" y tick at the origin.
  [0.5, 0.6, 0.7, 0.8].forEach(v => {
    s += '<text class="ax" x="' + r2(cx(v)) + '" y="' + (bottom + 20) + '" text-anchor="middle">' + Math.round(v * 100) + '%</text>';
  });
  s += '<line class="diag" stroke-dasharray="' + (card ? '4 4' : '5 5') + '" x1="' + r2(cx(0.5)) + '" y1="' + r2(cy(0.5)) + '" x2="' + r2(cx(xMax)) + '" y2="' + r2(cy(xMax)) + '"/>';
  const midY = r2((cy(0.4) + cy(1)) / 2);
  s += '<text class="ax" text-anchor="middle" transform="rotate(-90 14 ' + midY + ')" x="14" y="' + midY + '">Actually won</text>';
  const caption = card ? 'Model said · dot size = picks'
    : W < 300 ? 'Dot size and label = picks' : W < 420 ? 'Model said · dot size and label = picks' : 'What the model said · dot size and label = number of picks';
  s += '<text class="ax" x="' + r2((pad.l + W - pad.r) / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' + caption + '</text>';
  list.forEach(b => {
    const rr = card ? Math.min(16, 4 + Math.sqrt(b.n) * 0.9) : Math.min(22, 5 + Math.sqrt(b.n) * 1.1);
    const title = bucketLabel(b.bucket) + '%: ' + (card ? 'predicted ' : 'said ') + fmt.pct(b.predicted) + ', won ' + fmt.pct(b.actual) + ' of ' + b.n;
    s += '<circle class="dot" cx="' + r2(cx(b.predicted)) + '" cy="' + r2(cy(b.actual)) + '" r="' + rr.toFixed(1) + '"><title>' + esc(title) + '</title></circle>';
    if (!card) {
      const x = cx(b.predicted), right = x + 12 + rr + 10 > W - pad.r;
      s += '<text class="lb" x="' + r2(right ? x - 12 - rr : x + 12 + Math.sqrt(b.n) * 1.1) + '" y="' + r2(cy(b.actual) + 4) + '"' + (right ? ' text-anchor="end"' : '') + '>' + b.n + '</text>';
    }
  });
  s += '<text class="ax" data-perfect text-anchor="end">perfect</text>';
  host.innerHTML = '<svg class="' + (card ? 'calib-svg' : 'cal-svg') + '" viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(calibrationAriaLabel(list, variant)) + '">' + s + '</svg>';
  if (card) host.querySelectorAll('.dot').forEach((d, i) => d.style.setProperty('--k', String(i)));
  placePerfect(host.querySelector('svg'), [cx(0.5), cy(0.5)], [cx(xMax), cy(xMax)]);
  return { W };
}

// "perfect" rides the dashed diagonal: rotated to it, 6px above it, ending 10px short of its top end.
// It slides towards the origin in 10px steps while it would cover a dot or another label.
function placePerfect(svg, [x1, y1], [x2, y2]) {
  const t = svg && svg.querySelector('[data-perfect]');
  if (!t) return;
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, nx = uy, ny = -ux;          // n: unit normal pointing above the line
  const angle = r2(Math.atan2(dy, dx) * 180 / Math.PI);
  const others = [...svg.querySelectorAll('.dot, text:not([data-perfect])')];
  const hit = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  for (let back = 10; back < len * 0.7; back += 10) {
    const x = r2(x2 - ux * back + nx * 6), y = r2(y2 - uy * back + ny * 6);
    t.setAttribute('x', x); t.setAttribute('y', y);
    t.setAttribute('transform', 'rotate(' + angle + ' ' + x + ' ' + y + ')');
    const r = t.getBoundingClientRect();
    if (!others.some(o => hit(r, o.getBoundingClientRect()))) return;
  }
}
