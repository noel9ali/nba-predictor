// C2 · Model calibration chapter: origin labels apart, "perfect" on the diagonal, real-size text on phones
import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

// Helper: perpendicular distance from a point to a line
function perpDistance(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  const nx = x1 + t * dx, ny = y1 + t * dy;
  return Math.sqrt((px - nx) ** 2 + (py - ny) ** 2);
}

// Test the model page chapter variant
for (const w of [320, ...WIDTHS]) {
  const p = await open('/model?sample=1', w);

  // Scroll to chapter 6 and wait
  await scrollTo(p, '#ch6 [data-cal]', 1000);

  // Check for console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Get the SVG and card elements
  const svg = await p.$('#ch6 svg');
  const card = await p.$('#ch6 .card');

  if (!svg || !card) {
    check(`${w}: chapter calibration chart found`, !!svg && !!card, 'SVG or card not found');
    await done(p);
    continue;
  }

  // Get SVG bounds and viewBox
  const svgBox = await svg.boundingBox();
  const cardBox = await card.boundingBox();
  const viewBox = await svg.evaluate(el => {
    const vb = el.getAttribute('viewBox');
    if (!vb) return null;
    const [x, y, vbw, vbh] = vb.split(' ').map(Number);
    return { x, y, w: vbw, h: vbh };
  });

  // Collect all text elements with their bboxes
  const texts = await svg.$$eval('text', ts => ts.map(t => {
    const bbox = t.getBoundingClientRect();  // screen px: correct for rotated text
    const style = window.getComputedStyle(t);
    const fontSize = parseFloat(style.fontSize);
    const transform = t.getAttribute('transform') || '';
    return {
      text: t.textContent,
      x: bbox.left,
      y: bbox.top,
      width: bbox.width,
      height: bbox.height,
      fontSize: fontSize,
      transform: transform,
      cx: bbox.x + bbox.width / 2,  // center x
      cy: bbox.y + bbox.height / 2  // center y
    };
  }));

  // Get diagonal line endpoints (from viewBox coordinates)
  const diag = await svg.evaluate(el => {
    const line = el.querySelector('.diag');
    if (!line) return null;
    const m = line.getScreenCTM(), P = (x, y) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f];
    const a = P(+line.getAttribute('x1'), +line.getAttribute('y1')), b = P(+line.getAttribute('x2'), +line.getAttribute('y2'));
    return { x1: a[0], y1: a[1], x2: b[0], y2: b[1] };
  });

  // Check: SVG has width/height attributes (1:1 rendering)
  const svgAttrs = await svg.evaluate(el => ({
    width: el.getAttribute('width'),
    height: el.getAttribute('height')
  }));
  check(`${w}: SVG has width attribute`, svgAttrs.width !== null);
  check(`${w}: SVG has height attribute`, svgAttrs.height !== null);

  // Check: rendered font sizes ≥ 11px
  if (viewBox && svgBox) {
    const scale = svgBox.width / viewBox.w;
    const minSize = 10.95;
    texts.forEach((t, i) => {
      const rendered = t.fontSize * scale;
      if (t.text.trim() && rendered < minSize) {
        check(`${w}: text "${t.text}" ≥ 11px`, false,
          `rendered=${rendered.toFixed(2)}px (css=${t.fontSize}px × scale=${scale.toFixed(3)})`);
      }
    });
  }

  // Check: "Actually won" exists (y-axis title added in this fix)
  const hasYTitle = texts.some(t => t.text === 'Actually won');
  check(`${w}: "Actually won" y-axis title exists`, hasYTitle);

  // Check: "perfect" exists and is rotated
  const perfect = texts.find(t => t.text === 'perfect');
  check(`${w}: "perfect" label exists`, !!perfect);
  if (perfect) {
    check(`${w}: "perfect" is rotated`, perfect.transform.includes('rotate('),
      `transform=${perfect.transform}`);

    // Check: "perfect" center is near the diagonal (within 14px perp distance, in viewBox coords)
    if (diag && viewBox && svgBox) {
      // perfect.cx and perfect.cy are in viewBox coordinates from getBBox()
      // diag coordinates are also in viewBox coordinates
      // perpDistance expects both in the same coordinate system
      const dist = perpDistance(perfect.cx, perfect.cy, diag.x1, diag.y1, diag.x2, diag.y2);
      check(`${w}: "perfect" within 14px of diagonal`, dist <= 14,
        `distance=${dist.toFixed(1)}px`);
    }
  }

  // Check: no text overlaps
  const bboxes = texts.map((t, i) => ({
    i, text: t.text,
    left: t.x, top: t.y, right: t.x + t.width, bottom: t.y + t.height
  }));

  let hasOverlap = false;
  let overlapDetails = [];
  for (let i = 0; i < bboxes.length; i++) {
    for (let j = i + 1; j < bboxes.length; j++) {
      if (intersects(bboxes[i], bboxes[j], 0)) {
        hasOverlap = true;
        overlapDetails.push(`"${bboxes[i].text}" x "${bboxes[j].text}"`);
      }
    }
  }
  check(`${w}: no text overlaps`, !hasOverlap, overlapDetails.slice(0, 3).join('; '));

  // Check: all text inside the card
  if (cardBox && svgBox) {
    texts.forEach((t, i) => {
      const textLeft = t.x;
      const textTop = t.y;
      const textRight = textLeft + t.width;
      const textBottom = textTop + t.height;

      const inside = textLeft >= cardBox.x && textRight <= cardBox.x + cardBox.width &&
                     textTop >= cardBox.y && textBottom <= cardBox.y + cardBox.height;
      if (!inside && t.text.trim()) {
        check(`${w}: text "${t.text}" inside card`, false,
          `text=[${textLeft.toFixed(0)},${textTop.toFixed(0)},${textRight.toFixed(0)},${textBottom.toFixed(0)}], ` +
          `card=[${cardBox.x.toFixed(0)},${cardBox.y.toFixed(0)},${(cardBox.x + cardBox.width).toFixed(0)},${(cardBox.y + cardBox.height).toFixed(0)}]`);
      }
    });
  }

  // Take before-screenshot if this is the first pass (we'll rename later)
  await shot(p, `C2-before-${w}`, '#ch6 .card');

  await done(p);
}

// Test resize handling: open at 1440, resize to 400, check assertions still hold
const p1440 = await open('/model?sample=1', 1440);
await scrollTo(p1440, '#ch6 [data-cal]', 1000);

// Resize to 400
await p1440.setViewportSize({ width: 400, height: 900 });
await p1440.waitForTimeout(400); // Wait for resize handling

// Re-check text sizes and overlaps after resize
const svg400 = await p1440.$('#ch6 svg');
if (svg400) {
  const texts400 = await svg400.$$eval('text', ts => ts.map(t => {
    const bbox = t.getBBox();
    const style = window.getComputedStyle(t);
    const fontSize = parseFloat(style.fontSize);
    return {
      text: t.textContent,
      x: bbox.x,
      y: bbox.y,
      width: bbox.width,
      height: bbox.height,
      fontSize: fontSize
    };
  }));

  const viewBox400 = await svg400.evaluate(el => {
    const vb = el.getAttribute('viewBox');
    if (!vb) return null;
    const [x, y, vbw, vbh] = vb.split(' ').map(Number);
    return { x, y, w: vbw, h: vbh };
  });

  const svgBox400 = await svg400.boundingBox();

  if (viewBox400 && svgBox400) {
    const scale = svgBox400.width / viewBox400.w;
    const minSize = 10.95;
    texts400.forEach((t) => {
      const rendered = t.fontSize * scale;
      if (t.text.trim() && rendered < minSize) {
        check(`resize to 400: text "${t.text}" ≥ 11px`, false,
          `rendered=${rendered.toFixed(2)}px`);
      }
    });
  }

  const bboxes400 = texts400.map((t, i) => ({
    i, text: t.text,
    left: t.x, top: t.y, right: t.x + t.width, bottom: t.y + t.height
  }));

  let hasOverlap = false;
  for (let i = 0; i < bboxes400.length; i++) {
    for (let j = i + 1; j < bboxes400.length; j++) {
      if (intersects(bboxes400[i], bboxes400[j], 0)) {
        hasOverlap = true;
        break;
      }
    }
    if (hasOverlap) break;
  }
  check(`resize to 400: no text overlaps`, !hasOverlap);
}

check(`resize: no console errors`, p1440.errors.length === 0, p1440.errors.join(' | '));
await done(p1440);

// Verify C1 (Tonight card) is still working
console.log('\n--- Checking C1 (Tonight card) unchanged ---');
const pc1 = await open('/?sample=1&scene=live', 768);
await scrollTo(pc1, '[data-testid=calib]', 1500);

const svgc1 = await pc1.$('[data-testid=calib] svg');
if (svgc1) {
  const outerHtml = await svgc1.evaluate(el => el.outerHTML);
  // Verify card has its expected elements
  check(`C1: card SVG exists`, outerHtml.length > 100);
  check(`C1: card has dots`, outerHtml.includes('dot'));
  check(`C1: card has "Actually won"`, outerHtml.includes('Actually won'));
} else {
  check(`C1: card SVG exists`, false, 'SVG not found');
}

check(`C1: no console errors`, pc1.errors.length === 0, pc1.errors.join(' | '));
await done(pc1);

await close();
report();
