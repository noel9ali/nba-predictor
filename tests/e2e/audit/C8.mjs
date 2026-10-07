// C8: Weights chapter - visible grid lines, values at bar end
import { open, done, close, check, report, shot, scrollTo, intersects, WIDTHS } from './lib.mjs';

const widths = [320, 400, 768, 1440];

// Helper to convert Playwright bounding box to DOMRect-like object
const toRect = (box) => {
  if (!box) return null;
  return {
    left: box.x,
    right: box.x + box.width,
    top: box.y,
    bottom: box.y + box.height,
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height
  };
};

for (const w of widths) {
  const p = await open('/model?sample=1', w);

  console.log(`\n=== ${w}px ===`);

  // Scroll to the weights section and wait for reveal animation
  await scrollTo(p, '#ch4 .wts', 1500);

  // Test: no console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Get all weight rows
  const rows = await p.$$('ol.wts > li.w');
  if (!rows.length) {
    check(`${w}: rows found`, false, 'no weight rows');
    await done(p);
    continue;
  }

  // Test each row for value positioning
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];

    // Get the feature label
    const label = await row.evaluate(el => el.querySelector('.nm')?.textContent?.trim() || 'unknown');

    // Get the track (tr), bar (i), and value (val) elements
    const tr = await row.$('.tr');
    const bar = await row.$('.tr i');
    const val = await row.$('.val');

    if (!tr || !bar || !val) {
      check(`${w}: row ${i} has required elements`, false, label);
      continue;
    }

    // Get rectangles
    const trRect = toRect(await tr.boundingBox());
    const barRect = toRect(await bar.boundingBox());
    const valRect = toRect(await val.boundingBox());
    const nmRect = toRect(await row.$('.nm').then(e => e?.boundingBox()));

    if (!trRect || !barRect || !valRect) {
      check(`${w}: row ${i} rects valid`, false, label);
      continue;
    }

    // Get the share value from the row
    const share = await row.evaluate(el => {
      const bar = el.querySelector('.tr i');
      if (!bar) return null;
      const width = window.getComputedStyle(bar).width;
      const trackWidth = el.querySelector('.tr')?.offsetWidth;
      if (!width || !trackWidth) return null;
      return parseFloat(width) / trackWidth;
    });

    // Test value positioning: outside case (share <= 0.82) or inside case (share > 0.82)
    if (share !== null && share <= 0.82) {
      // Outside case: value should be just after the bar
      const gap = valRect.left - barRect.right;
      check(`${w}: row ${i} value gap is 6-10px`, gap >= 6 && gap <= 10, `${label}: ${gap.toFixed(1)}px`);

      // Value should be inside the track horizontally
      const valueInsideTrack = valRect.right <= trRect.right + 1;
      check(`${w}: row ${i} value inside track right`, valueInsideTrack, label);
    } else if (share !== null && share > 0.82) {
      // Inside case: value should be inside the bar
      const valueInsideBar = valRect.left >= barRect.left - 1 && valRect.right <= barRect.right + 1;
      check(`${w}: row ${i} value inside bar`, valueInsideBar, `${label} (share ${share.toFixed(2)})`);
    }

    // Test: value doesn't intersect with the label
    if (nmRect) {
      const overlap = intersects(valRect, nmRect, 2);
      check(`${w}: row ${i} value doesn't overlap label`, !overlap, label);
    }
  }

  // Test: no value rects intersect other value rects
  const valElements = await p.$$('ol.wts > li.w .val');
  for (let i = 0; i < valElements.length; i++) {
    const valRect = toRect(await valElements[i].boundingBox());
    if (!valRect) continue;

    for (let j = i + 1; j < valElements.length; j++) {
      const otherRect = toRect(await valElements[j].boundingBox());
      if (!otherRect) continue;

      const overlap = intersects(valRect, otherRect, 2);
      check(`${w}: values don't intersect (${i} & ${j})`, !overlap);
    }
  }

  // Test: grid color is visible (color-mix renders as color(srgb ...) or rgba with alpha 0.15–0.25)
  const tr = await p.$('.wts .tr');
  if (tr) {
    const bgImage = await tr.evaluate(el => window.getComputedStyle(el).backgroundImage);
    const hasVisibleGrid = bgImage && (
      bgImage.includes('color-mix') ||
      bgImage.includes('color(srgb') ||
      /rgba\([^)]+,\s*0\.(?:1[5-9]|2[0-5])\)/.test(bgImage) ||
      /rgba\([^)]+,\s*0\.[1-2]\d\)/.test(bgImage)
    );
    check(`${w}: grid has visible color`, hasVisibleGrid, bgImage?.substring(0, 50));
  }

  // Test: each value has sr-only text ending with '%'
  const nmElements = await p.$$('ol.wts > li.w .nm');
  let srTextOk = true;
  for (const nm of nmElements) {
    const srText = await nm.evaluate(el => {
      const sr = el.querySelector('.sr');
      return sr?.textContent || '';
    });
    if (!srText.endsWith('%')) {
      srTextOk = false;
      console.log(`  SR text missing or doesn't end with %: "${srText}"`);
    }
  }
  check(`${w}: sr-only text ends with %`, srTextOk);

  // Test: values fade in with opacity transition (skip for reduced motion)
  const valOpacity = await p.evaluate(() => {
    const val = document.querySelector('.wts .val');
    return val ? window.getComputedStyle(val).opacity : null;
  });
  // At the time of screenshot, values should be visible (opacity 1) since animation has finished
  check(`${w}: values visible (opacity 1)`, valOpacity === '1', `opacity: ${valOpacity}`);

  // Test: no horizontal page overflow
  const pageWidth = await p.evaluate(() => document.documentElement.clientWidth);
  const bodyWidth = await p.evaluate(() => document.body.scrollWidth);
  const noOverflow = bodyWidth <= pageWidth + 1;
  check(`${w}: no horizontal overflow`, noOverflow);

  // Take screenshot of the card
  await shot(p, `C8-${w}`, '#ch4 .card');

  await done(p);
}

// Reduced motion test at 400px
{
  const p = await open('/model?sample=1', 400, { reducedMotion: true });
  console.log(`\n=== 400px (reduced motion) ===`);

  // Scroll to weights
  await scrollTo(p, '#ch4 .wts', 500);

  // Values should be immediately visible (no transition delay)
  const valOpacity = await p.evaluate(() => {
    const val = document.querySelector('.wts .val');
    return val ? window.getComputedStyle(val).opacity : null;
  });
  check(`400 reduced-motion: values visible (opacity 1)`, valOpacity === '1', `opacity: ${valOpacity}`);

  check(`400 reduced-motion: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  await done(p);
}

await close();
report();
