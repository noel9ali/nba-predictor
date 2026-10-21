import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

// Get all visible text labels in the chart
async function getVisibleLabels(page) {
  return await page.locator('[data-testid=bankroll]').evaluate((h) => {
    const svg = h.querySelector('svg');
    if (!svg) return [];

    const labels = [];
    const computedOpacity = (el) => {
      let opacity = 1;
      let current = el;
      while (current && current !== svg) {
        const computed = window.getComputedStyle(current);
        opacity *= parseFloat(computed.opacity || '1');
        if (computed.display === 'none' || computed.visibility === 'hidden') return 0;
        current = current.parentElement;
      }
      return opacity;
    };

    // Get all text elements
    svg.querySelectorAll('text').forEach((t) => {
      const op = computedOpacity(t);
      if (op > 0.05) {
        const rect = t.getBoundingClientRect();
        const svgRect = svg.getBoundingClientRect();
        labels.push({
          text: t.textContent,
          class: t.getAttribute('class') || '',
          rect: {
            left: rect.left - svgRect.left,
            top: rect.top - svgRect.top,
            right: rect.right - svgRect.left,
            bottom: rect.bottom - svgRect.top,
            width: rect.width,
            height: rect.height
          },
          opacity: op,
          visibility: window.getComputedStyle(t).visibility,
          display: window.getComputedStyle(t).display
        });
      }
    });

    return labels;
  });
}

async function debugStep(page) {
  return await page.locator('[data-testid=bankroll]').evaluate((h) => {
    const step = h.dataset.step;
    const svg = h.querySelector('svg');
    const labels = [];
    svg.querySelectorAll('text.lbl').forEach((t) => {
      let op = 1, current = t;
      while (current && current !== svg) {
        op *= parseFloat(window.getComputedStyle(current).opacity || '1');
        current = current.parentElement;
      }
      labels.push({ text: t.textContent, op });
    });
    return { step, labels };
  });
}

// Get all line segments and points from SVG paths
async function getLineSegments(page) {
  return await page.locator('[data-testid=bankroll]').evaluate((h) => {
    const svg = h.querySelector('svg');
    if (!svg) return { base: null, tnr: null, ln: [], ddl: null, tnl: null };

    const svgRect = svg.getBoundingClientRect();

    // Base line (horizontal dashed line)
    const baseEl = svg.querySelector('line.base');
    const base = baseEl
      ? {
          x1: parseFloat(baseEl.getAttribute('x1')),
          y: parseFloat(baseEl.getAttribute('y1')),
          x2: parseFloat(baseEl.getAttribute('x2')),
          tolerance: 1
        }
      : null;

    // Tonight range bar (vertical line)
    const tnrEl = svg.querySelector('line.tnr');
    const tnr = tnrEl
      ? {
          x: parseFloat(tnrEl.getAttribute('x1')),
          y1: parseFloat(tnrEl.getAttribute('y1')),
          y2: parseFloat(tnrEl.getAttribute('y2')),
          tolerance: 3
        }
      : null;

    // Series lines
    const lineSegments = [];
    ['.ln', '.ddl', '.tnl'].forEach((sel) => {
      const el = svg.querySelector(sel);
      if (!el) return;

      const pathData = el.getAttribute('d');
      if (!pathData) return;

      // Parse path: M x,y L x,y ... format
      const matches = pathData.match(/[ML][\d.,\-\.]+/g) || [];
      const points = [];
      matches.forEach((m) => {
        const coords = m.slice(1).split(',').map(parseFloat);
        if (coords.length === 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {
          points.push({ x: coords[0], y: coords[1] });
        }
      });

      if (points.length >= 2) {
        lineSegments.push({ type: sel.slice(1), points });
      }
    });

    return { base, tnr, lineSegments };
  });
}

// Check if a point is inside a rect (shrink by px)
function pointInRect(pt, rect, shrink = 0) {
  return (
    pt.x >= rect.left + shrink &&
    pt.x <= rect.right - shrink &&
    pt.y >= rect.top + shrink &&
    pt.y <= rect.bottom - shrink
  );
}

// Check if a line segment intersects a rectangle
function segmentIntersectsRect(p1, p2, rect, tolerance = 0) {
  const grow = (r, t) => ({
    left: r.left - t,
    top: r.top - t,
    right: r.right + t,
    bottom: r.bottom + t
  });

  const r = grow(rect, tolerance);

  // If either endpoint is in the rect, it intersects
  if (pointInRect(p1, r) || pointInRect(p2, r)) return true;

  // Check if segment crosses any edge
  const edges = [
    { x1: r.left, y1: r.top, x2: r.right, y2: r.top }, // top
    { x1: r.left, y1: r.bottom, x2: r.right, y2: r.bottom }, // bottom
    { x1: r.left, y1: r.top, x2: r.left, y2: r.bottom }, // left
    { x1: r.right, y1: r.top, x2: r.right, y2: r.bottom } // right
  ];

  for (const edge of edges) {
    if (segmentIntersectsSegment(p1, p2, { x: edge.x1, y: edge.y1 }, { x: edge.x2, y: edge.y2 })) {
      return true;
    }
  }

  return false;
}

// Standard line segment intersection
function segmentIntersectsSegment(p1, p2, p3, p4) {
  const ccw = (a, b, c) => (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x);
  return ccw(p1, p3, p4) !== ccw(p2, p3, p4) && ccw(p1, p2, p3) !== ccw(p1, p2, p4);
}

async function testC4Labels(p, w, step) {
  const labels = await getVisibleLabels(p);
  const lines = await getLineSegments(p);

  // Debug: log visible labels for step 2
  if (step === 2 && w.includes('400') && w.includes('live')) {
    console.log(`DEBUG ${w} step ${step}: visible labels =`, labels.filter(l => l.class.match(/lbl|ddt|tnt|tns/)).map(l => l.text.slice(0, 15)));
  }

  // Check 1: No two visible text rects intersect
  let labelOverlaps = [];
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      if (intersects(labels[i].rect, labels[j].rect, 0)) {
        labelOverlaps.push(`"${labels[i].text}" ↔ "${labels[j].text}"`);
      }
    }
  }
  check(`${w} step ${step}: no label overlaps`, labelOverlaps.length === 0, labelOverlaps.slice(0, 3).join('; '));

  // Check 2: No .lbl/.ddt/.tnt/.tns rect intersects base line
  if (lines.base) {
    let baseCollisions = [];
    labels.forEach((lbl) => {
      if (lbl.class.match(/lbl|ddt|tnt|tns/)) {
        // Horizontal overlap with base line?
        if (lbl.rect.left <= lines.base.x2 && lbl.rect.right >= lines.base.x1) {
          // Y overlap with base line (with tolerance)?
          if (lbl.rect.top <= lines.base.y + 1 && lbl.rect.bottom >= lines.base.y - 1) {
            baseCollisions.push(lbl.text);
          }
        }
      }
    });
    check(`${w} step ${step}: no labels cross base line`, baseCollisions.length === 0, baseCollisions.slice(0, 2).join(', '));
  }

  // Check 3: No .lbl/.ddt/.tnt/.tns rect intersects tonight range bar
  if (lines.tnr && step === 3) {   // the range bar only shows at step 3
    let tnrCollisions = [];
    labels.forEach((lbl) => {
      if (lbl.class.match(/lbl|ddt|tnt|tns/)) {
        // X overlap with tnr?
        if (lbl.rect.left <= lines.tnr.x + 3 && lbl.rect.right >= lines.tnr.x - 3) {
          // Y overlap with tnr bar span?
          if (lbl.rect.top <= Math.max(lines.tnr.y1, lines.tnr.y2) && lbl.rect.bottom >= Math.min(lines.tnr.y1, lines.tnr.y2)) {
            tnrCollisions.push(lbl.text);
          }
        }
      }
    });
    check(`${w} step ${step}: no labels cross tonight range bar`, tnrCollisions.length === 0, tnrCollisions.slice(0, 2).join(', '));
  }

  // Check 4: No .lbl/.ddt/.tnt/.tns crosses series lines (step 2 checks .ddl; all check .ln, .tnl)
  let lineCollisions = [];
  const checkedLabels = [];
  labels.forEach((lbl) => {
    if (lbl.class.match(/lbl|ddt|tnt|tns/)) {
      checkedLabels.push(lbl.text);
      lines.lineSegments.forEach((line) => {
        // Skip .ddl unless step 2
        if (line.type === 'ddl' && step !== 2) return;
        if (line.type === 'tnl' && step !== 3) return;   // the tonight line only shows at step 3

        for (let i = 0; i < line.points.length - 1; i++) {
          if (segmentIntersectsRect(line.points[i], line.points[i + 1], lbl.rect, 0)) {
            lineCollisions.push(`${lbl.text} ↔ ${line.type}`);
            return;
          }
        }
      });
    }
  });
  if (step === 2 && `${w}`.includes('400') && lineCollisions.length > 0) {
    console.log(`DEBUG ${w} step ${step}: checked labels = [${checkedLabels.join(', ')}]`);
    console.log(`DEBUG ${w} step ${step}: line collisions = [${lineCollisions.join(', ')}]`);
  }
  check(`${w} step ${step}: no labels cross series lines`, lineCollisions.length === 0, lineCollisions.slice(0, 2).join('; '));

  // Check 5: Step 3 end label (.endg) has display:none
  if (step === 3) {
    const endgDisplay = await p.locator('[data-testid=bankroll]').evaluate((h) => {
      const endg = h.querySelector('.endg');
      return endg ? window.getComputedStyle(endg).display : 'missing';
    });
    check(`${w} step 3: .endg display:none`, endgDisplay === 'none', `got ${endgDisplay}`);
  }

  // Check 6: All visible text rects lie inside the card
  const cardRect = await p.locator('.bcard').first().boundingBox();
  if (cardRect) {
    const chartRect = await p.locator('[data-testid=bankroll]').boundingBox();
    const svgRect = await p.locator('[data-testid=bankroll] svg').boundingBox();

    let outOfBounds = [];
    labels.forEach((lbl) => {
      // Convert label rect (relative to SVG) to absolute coords
      const absRect = {
        left: svgRect.x + lbl.rect.left,
        top: svgRect.y + lbl.rect.top,
        right: svgRect.x + lbl.rect.right,
        bottom: svgRect.y + lbl.rect.bottom
      };

      if (
        absRect.left < chartRect.x ||
        absRect.right > chartRect.x + chartRect.width ||
        absRect.top < chartRect.y ||
        absRect.bottom > chartRect.y + chartRect.height
      ) {
        outOfBounds.push(lbl.text);
      }
    });
    check(`${w} step ${step}: all labels inside chart`, outOfBounds.length === 0, outOfBounds.slice(0, 2).join(', '));
  }

  // Check 7: No console errors
  check(`${w} step ${step}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
}

async function testC4() {
  const scenes = ['live', 'final', 'nextup'];

  for (const scene of scenes) {
    for (const w of WIDTHS) {
      const p = await open(`/?sample=1&scene=${scene}`, w);

      for (const step of [1, 2, 3]) {
        // Scroll to the step
        await scrollTo(p, `.bstep[data-bs="${step}"]`, 2000);

        // Verify we're on the right step
        const currentStep = await p.locator('[data-testid=bankroll]').evaluate((h) => h.dataset.step);
        check(`${scene} ${w} step ${step}: data-step matches`, currentStep === String(step), `got ${currentStep}`);

        // Test label placement
        await testC4Labels(p, `${scene}/${w}`, step);

        // Take screenshot
        await shot(p, `C4-s${step}-${w}`, '.bcard');
      }

      await done(p);
    }
  }

  // Test past mode with a specific date
  const p = await open('/?sample=1&date=2026-11-16', 400);
  for (const step of [1, 2, 3]) {
    await scrollTo(p, `.bstep[data-bs="${step}"]`, 2000);
    const currentStep = await p.locator('[data-testid=bankroll]').evaluate((h) => h.dataset.step);
    check(`past 400 step ${step}: data-step matches`, currentStep === String(step), `got ${currentStep}`);
    await testC4Labels(p, `past/400`, step);
    await shot(p, `C4-s${step}-past`, '.bcard');
  }
  await done(p);

  await close();
  report();
}

await testC4();
