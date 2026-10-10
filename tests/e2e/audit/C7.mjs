// C7: Season strip flag and label layout, no overlap or truncation
import { open, done, close, check, report, shot, scrollTo, intersects, WIDTHS } from './lib.mjs';

const widths = [320, 400, 560, 600, 700, 768, 1440];

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
  const p = await open('/model?sample=1', w, { reducedMotion: true });

  console.log(`\n=== ${w}px ===`);

  // Get the card element
  const card = await p.$('.s2card');
  if (!card) {
    check(`${w}: card found`, false, 'no .s2card element');
    await done(p);
    continue;
  }

  // Get bounding rectangles
  const flagPill = await p.$('.splitflag i');
  const slabelsContainer = await p.$('.slabels');
  const scountsContainer = await p.$('.scounts');
  const seasonsStrip = await p.$('.seasons');

  const flagRect = toRect(flagPill ? await flagPill.boundingBox() : null);
  const slabelsRect = toRect(slabelsContainer ? await slabelsContainer.boundingBox() : null);
  const scountsRect = toRect(scountsContainer ? await scountsContainer.boundingBox() : null);
  const seasonsRect = toRect(seasonsStrip ? await seasonsStrip.boundingBox() : null);

  // Test 1: No console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  if (!slabelsRect || !scountsRect || !seasonsRect) {
    check(`${w}: all elements found`, false, 'missing labels/counts/seasons');
    await done(p);
    continue;
  }

  // Test 2: Flag doesn't overlap labels/counts text (skip if flag is hidden or has invalid rect)
  const hasValidFlagRect = flagRect && Number.isFinite(flagRect.bottom) && Number.isFinite(flagRect.top);
  if (hasValidFlagRect) {
    const flagIntersectsLabels = intersects(flagRect, slabelsRect, 1);
    check(`${w}: flag doesn't intersect labels`, !flagIntersectsLabels);

    const flagIntersectsCounts = intersects(flagRect, scountsRect, 1);
    check(`${w}: flag doesn't intersect counts`, !flagIntersectsCounts);

    const flagBelowLimit = flagRect.bottom <= seasonsRect.top + 1;
    check(`${w}: flag bottom <= strip top + 1`, flagBelowLimit);
  } else {
    check(`${w}: flag position test skipped`, true, 'flag not visible');
  }

  const labelsAboveLimit = slabelsRect.top >= seasonsRect.bottom - 1;
  check(`${w}: labels top >= strip bottom - 1`, labelsAboveLimit);

  // Test 3: Labels have 6px space below strip
  const labelSpans = await p.$$('.slabels span');
  const countSpans = await p.$$('.scounts span');

  let labelSpacingOk = true;
  for (const span of labelSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const rect = toRect(await span.boundingBox());
    if (rect && rect.top < seasonsRect.bottom + 6) {
      labelSpacingOk = false;
    }
  }
  check(`${w}: labels have 6px space below strip`, labelSpacingOk);

  // Test 4: No truncation (scrollWidth <= clientWidth of visible content only)
  // Only measure the displayed label element (l-full or l-short), not the entire span with both
  let truncationFound = false;
  for (const span of labelSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const truncated = await span.evaluate(el => {
      const full = el.querySelector('.l-full');
      const short = el.querySelector('.l-short');
      if (!full || !short) return false;
      const fullStyle = window.getComputedStyle(full);
      const visibleEl = fullStyle.display !== 'none' ? full : short;
      return visibleEl.scrollWidth > el.clientWidth + 1;
    });
    if (truncated) truncationFound = true;
  }

  for (const span of countSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const sw = await span.evaluate(el => el.scrollWidth);
    const cw = await span.evaluate(el => el.clientWidth);
    if (sw > cw + 1) {
      truncationFound = true;
    }
  }
  check(`${w}: no truncation`, !truncationFound);

  // Test 5: Labels must not wrap to multiple lines
  let labelWrapFound = false;
  for (const span of labelSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const rects = await span.evaluate(el => el.getClientRects().length);
    if (rects !== 1) {
      labelWrapFound = true;
      console.log(`  Label span wraps: ${rects} rects instead of 1`);
    }
  }
  check(`${w}: no label wrapping`, !labelWrapFound);

  // Test 6: Label format matches width expectations
  let labelFormatOk = true;
  const maxWidth560 = w <= 560;
  const expectedFormat = maxWidth560 ? /^\d{2}–\d{2}$/ : /^\d{4}–\d{2}$/;

  for (const span of labelSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const text = await span.evaluate((el) => {
      const full = el.querySelector('.l-full');
      const short = el.querySelector('.l-short');
      if (full && short) {
        const fullStyle = window.getComputedStyle(full);
        return fullStyle.display !== 'none' ? full.textContent : short.textContent;
      }
      return '';
    });
    if (text && text.trim() && !expectedFormat.test(text.trim())) {
      labelFormatOk = false;
      console.log(`  Label "${text.trim()}" doesn't match ${expectedFormat}`);
    }
  }
  check(`${w}: label format correct`, labelFormatOk);

  // Test 7: Font sizes >= 11px
  let fontSizeOk = true;
  for (const span of labelSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const fs = await span.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    if (fs < 11) {
      fontSizeOk = false;
    }
  }
  for (const span of countSpans) {
    const hidden = await span.evaluate(el => window.getComputedStyle(el).visibility === 'hidden');
    if (hidden) continue;
    const fs = await span.evaluate(el => parseFloat(window.getComputedStyle(el).fontSize));
    if (fs < 11) {
      fontSizeOk = false;
    }
  }
  check(`${w}: font sizes >= 11px`, fontSizeOk);

  // Test 8: No horizontal page overflow
  const pageWidth = await p.evaluate(() => document.documentElement.clientWidth);
  const bodyWidth = await p.evaluate(() => document.body.scrollWidth);
  const noOverflow = bodyWidth <= pageWidth + 1;
  check(`${w}: no horizontal overflow`, noOverflow);

  // Take screenshot
  await shot(p, `C7-${w}`, '.s2card');

  await done(p);
}

await close();
report();
