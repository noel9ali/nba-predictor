// C1 · Tonight calibration card: no label collisions, y-axis title, real-size text
import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=live', w);

  // Scroll to the calibration card and wait for dots to animate
  await scrollTo(p, '[data-testid=calib]', 1500);

  // Check for console errors (CSP violations, etc.)
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Get the SVG and card elements
  const svg = await p.$('[data-testid=calib] svg');
  const card = await p.$('[data-testid=calib]');

  if (!svg || !card) {
    check(`${w}: calibration chart found`, !!svg && !!card, 'SVG or card not found');
    await done(p);
    continue;
  }

  // Get SVG bounds and viewBox
  const svgBox = await svg.boundingBox();
  const viewBox = await svg.evaluate(el => {
    const vb = el.getAttribute('viewBox');
    if (!vb) return null;
    const [x, y, vbw, vbh] = vb.split(' ').map(Number);
    return { x, y, w: vbw, h: vbh };
  });

  // Get card bounds
  const cardBox = await card.boundingBox();

  // Check SVG width vs viewBox width
  if (viewBox && svgBox) {
    const renderedWidth = svgBox.width;
    const viewBoxWidth = viewBox.w;
    check(`${w}: rendered SVG width matches viewBox ±1px`,
      Math.abs(renderedWidth - viewBoxWidth) <= 1,
      `rendered=${renderedWidth.toFixed(1)}, viewBox=${viewBoxWidth}`);
    check(`${w}: SVG width ≤ 420px`, renderedWidth <= 420, `width=${renderedWidth.toFixed(1)}`);

    // At 768px check centering
    if (w === 768 && cardBox) {
      const leftGap = svgBox.x - cardBox.x;
      const rightGap = (cardBox.x + cardBox.width) - (svgBox.x + svgBox.width);
      check(`${w}: SVG centered in card (gaps ≤2px apart)`,
        Math.abs(leftGap - rightGap) <= 2,
        `leftGap=${leftGap.toFixed(1)}, rightGap=${rightGap.toFixed(1)}`);
    }
  }

  // Collect all text elements
  const texts = await svg.$$eval('text', ts => ts.map(t => {
    const bbox = t.getBBox();
    const style = window.getComputedStyle(t);
    const fontSize = parseFloat(style.fontSize);
    const transform = t.getAttribute('transform') || '';
    return {
      text: t.textContent,
      x: bbox.x,
      y: bbox.y,
      width: bbox.width,
      height: bbox.height,
      fontSize: fontSize,
      transform: transform
    };
  }));

  // Check for y-axis title
  const hasYTitle = texts.some(t => t.text === 'Actually won' && t.transform.includes('rotate'));
  check(`${w}: y-axis title "Actually won" exists with rotate`, hasYTitle);

  // Check for perfect label
  const hasPerfect = texts.some(t => t.text === 'perfect');
  check(`${w}: "perfect" label exists`, hasPerfect);

  // Calculate rendered font size (accounting for SVG scaling)
  if (viewBox && svgBox) {
    const scale = svgBox.width / viewBox.w;
    const minRenderedSize = 10.95; // ~11px

    texts.forEach((t, i) => {
      const renderedSize = t.fontSize * scale;
      if (renderedSize < minRenderedSize && t.text.trim() && t.text !== 'Actually won') {
        check(`${w}: text "${t.text}" rendered size ≥ 11px`, false,
          `rendered=${renderedSize.toFixed(1)}px, css=${t.fontSize.toFixed(1)}px`);
      }
    });
  }

  // Check for text overlaps
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
  check(`${w}: no text overlaps`, !hasOverlap, overlapDetails.join('; '));

  // Check caption spacing - find x tick labels more robustly
  const caption = texts.find(t => t.text.includes('Model said'));
  const xTickLabels = texts.filter(t => t.text && /^\d+%$/.test(t.text) && (t.text === '50%' || t.text === '60%' || t.text === '70%' || t.text === '80%'));

  if (caption && xTickLabels.length > 0) {
    const maxXTickBottom = Math.max(...xTickLabels.map(t => t.y + t.height));
    const captionTop = caption.y;
    const gap = captionTop - maxXTickBottom;
    check(`${w}: caption ≥ 12px above x ticks`, gap >= 12, `gap=${gap.toFixed(1)}px`);
  } else {
    check(`${w}: caption and x ticks found`, false, `caption=${!!caption}, xTicks=${xTickLabels.length}`);
  }

  // Take after-screenshot
  await shot(p, `C1-${w}`, '[data-testid=calib]');

  await done(p);
}

// Model page check: verify the chapter chart (if it exists) is unchanged
const p = await open('/model?sample=1', 1440);
await p.waitForTimeout(1500); // Wait for animations

const chapterSvg = await p.$('#ch6 svg');
if (chapterSvg) {
  const outerHtml = await chapterSvg.evaluate(el => el.outerHTML);
  // Just verify it exists and has dots - we're not changing the chapter variant
  check('1440: chapter SVG unchanged (still has dots)', outerHtml.includes('dot'));
}

check(`1440: model page no console errors`, p.errors.length === 0, p.errors.join(' | '));
await done(p);

await close();
report();
