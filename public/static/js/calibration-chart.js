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
  const W = card ? Math.min(420, Math.max(260, host.clientWidth || 340)) : 560;
  const H = card ? Math.round(W * 0.72) : 380;
  const pad = card ? { l: 58, r: 14, t: 14, b: 54 } : { l: 48, r: 16, t: 16, b: 44 };
  const xMax = card ? 0.85 : 0.8;
  const clampX = v => Math.min(xMax, Math.max(0.5, v)), clampY = v => Math.min(1, Math.max(0.4, v));
  const cx = v => pad.l + (clampX(v) - 0.5) * (W - pad.l - pad.r) / (xMax - 0.5);
  const cy = v => pad.t + (1 - clampY(v)) * (H - pad.t - pad.b) / 0.6;
  let s = '';
  [0.4, 0.6, 0.8, 1].forEach(v => {
    s += '<line class="gridl" x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + r2(cy(v)) + '" y2="' + r2(cy(v)) + '"/>' +
      '<text class="ax" x="' + (card ? pad.l - 8 : 40) + '" y="' + r2(cy(v) + 4) + '" text-anchor="end">' + Math.round(v * 100) + '%</text>';
  });
  [0.5, 0.6, 0.7, 0.8].forEach(v => {
    s += '<text class="ax" x="' + r2(cx(v)) + '" y="' + (card ? H - pad.b + 18 : H - pad.b + 18) + '" text-anchor="middle">' + Math.round(v * 100) + '%</text>';
  });
  s += '<line class="diag" stroke-dasharray="' + (card ? '4 4' : '5 5') + '" x1="' + r2(cx(0.5)) + '" y1="' + r2(cy(0.5)) + '" x2="' + r2(cx(xMax)) + '" y2="' + r2(cy(xMax)) + '"/>';
  if (card) {
    // Add y-axis title for card variant
    const plotMidY = (cy(0.4) + cy(1)) / 2;
    s += '<text class="ax" text-anchor="middle" transform="rotate(-90, 14, ' + r2(plotMidY) + ')" x="14" y="' + r2(plotMidY) + '">Actually won</text>';
  }
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
  s += '<text class="ax" x="' + r2((pad.l + W - pad.r) / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' +
    (card ? 'Model said · dot size = picks' : 'What the model said · dot size and label = number of picks') + '</text>';

  // Add "perfect" label for card variant with collision detection
  if (card) {
    // Diagonal endpoints
    const x1 = cx(0.5), y1 = cy(0.5), x2 = cx(xMax), y2 = cy(xMax);
    const dx = x2 - x1, dy = y2 - y1;
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;

    // Start position: ~0.85 along the diagonal, 6px above the line
    let tPos = 0.85;
    let perfectX = x1 + tPos * dx;
    let perfectY = y1 + tPos * dy - 6;

    // Add the perfect label to SVG to measure its bbox
    s += '<text class="ax" data-perfect="1" text-anchor="end" transform="rotate(' + r2(angle) + ' ' + r2(perfectX) + ' ' + r2(perfectY) + ')" x="' + r2(perfectX) + '" y="' + r2(perfectY) + '">perfect</text>';
  }

  const size = card ? ' width="' + W + '" height="' + H + '"' : '';
  host.innerHTML = '<svg class="' + (card ? 'calib-svg' : 'cal-svg') + '" viewBox="0 0 ' + W + ' ' + H + '"' + size + ' role="img" aria-label="' + esc(calibrationAriaLabel(list, variant)) + '">' + s + '</svg>';
  if (card) {
    host.querySelectorAll('.dot').forEach((d, i) => d.style.setProperty('--k', String(i)));

    // Collision detection for perfect label
    const svg = host.querySelector('svg');
    const perfectText = svg.querySelector('[data-perfect="1"]');
    const dots = svg.querySelectorAll('.dot');
    const texts = svg.querySelectorAll('text');

    if (perfectText && dots.length > 0) {
      let perfectBox = perfectText.getBBox();
      let slideSteps = 0;
      let maxSteps = 8;

      // Slide down the diagonal until clear of collisions
      while (slideSteps < maxSteps) {
        let hasCollision = false;
        perfectBox = perfectText.getBBox();

        // Check collision with dots
        dots.forEach(dot => {
          const dotCx = parseFloat(dot.getAttribute('cx'));
          const dotCy = parseFloat(dot.getAttribute('cy'));
          const r = parseFloat(dot.getAttribute('r'));
          const dotBox = { left: dotCx - r, top: dotCy - r, right: dotCx + r, bottom: dotCy + r };
          if (intersects(perfectBox, dotBox, 0)) hasCollision = true;
        });

        // Check collision with other labels (excluding itself)
        texts.forEach(t => {
          if (t !== perfectText && t.textContent.trim()) {
            const tBox = t.getBBox();
            const box = { left: tBox.x, top: tBox.y, right: tBox.x + tBox.width, bottom: tBox.y + tBox.height };
            if (intersects(perfectBox, box, 0)) hasCollision = true;
          }
        });

        if (!hasCollision) break;

        // Slide 10px down the diagonal
        tPos -= 0.1;
        const x1 = cx(0.5), y1 = cy(0.5), x2 = cx(xMax), y2 = cy(xMax);
        const dx = x2 - x1, dy = y2 - y1;
        perfectX = x1 + tPos * dx;
        perfectY = y1 + tPos * dy - 6;
        perfectText.setAttribute('x', r2(perfectX));
        perfectText.setAttribute('y', r2(perfectY));
        slideSteps++;
      }
    }
  }
  return { W };
}

// Helper for bounding box intersection
function intersects(a, b, tol = 0) {
  return a.left < b.right - tol && b.left < a.right - tol && a.top < b.bottom - tol && b.top < a.bottom - tol;
}
