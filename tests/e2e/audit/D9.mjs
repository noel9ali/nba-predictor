import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

// Test at 320, 400, 768, 1024
const WIDTHS_TESTED = [320, 400, 768, 1024];

for (const w of WIDTHS_TESTED) {
  const p = await open('/?sample=1&scene=live', w);

  // Scroll to toolbar
  await scrollTo(p, '[data-toolbar]', 1200);

  // Get all filter buttons
  const filterButtons = await p.$$('[data-testid=filters] button');
  const filterCount = filterButtons.length;

  // Get toolbar element
  const toolbar = await p.$('[data-toolbar]');
  const toolbarBox = await toolbar.boundingBox();

  if (filterCount > 0) {
    // Get filter button rects
    const filterRects = await Promise.all(filterButtons.map(btn => btn.boundingBox()));

    // All filter buttons should share one top (±2px)
    let allFiltersOneSameTop = true;
    const firstFilterTop = filterRects[0].y;
    for (let i = 1; i < filterRects.length; i++) {
      if (Math.abs(filterRects[i].y - firstFilterTop) > 2) {
        allFiltersOneSameTop = false;
        break;
      }
    }
    check(`${w}px: all filter buttons share one top (±2px)`, allFiltersOneSameTop,
      filterRects.map((r, i) => `btn${i}=${r.y.toFixed(0)}`).join(', '));
  }

  // Get sort buttons
  const sortButtons = await p.$$('[data-testid=sorts] button');
  const sortCount = sortButtons.length;

  // Get sort label
  const sortLabel = await p.$('.tg-lbl');
  const sortLabelBox = sortLabel ? await sortLabel.boundingBox() : null;

  if (sortCount > 0 && sortLabelBox) {
    // Get sort button rects
    const sortRects = await Promise.all(sortButtons.map(btn => btn.boundingBox()));

    // All sort buttons and label should share one top (±4px)
    let allSortsOneSameTop = true;
    const labelVertCenter = sortLabelBox.y + sortLabelBox.height / 2;
    const firstSortTop = sortRects[0].y;

    // Check if label is vertically centered with sort buttons (label center vs button top)
    // Allow ±4px tolerance
    const firstSortVertCenter = sortRects[0].y + sortRects[0].height / 2;
    if (Math.abs(labelVertCenter - firstSortVertCenter) > 4) {
      allSortsOneSameTop = false;
    }

    for (let i = 1; i < sortRects.length; i++) {
      if (Math.abs(sortRects[i].y - firstSortTop) > 4) {
        allSortsOneSameTop = false;
        break;
      }
    }

    check(`${w}px: sort label and buttons share one row (±4px, label centred)`, allSortsOneSameTop,
      `label center=${labelVertCenter.toFixed(0)}, btn0 center=${firstSortVertCenter.toFixed(0)}`);
  }

  // Filters row should be above sorts row
  if (filterCount > 0 && sortCount > 0) {
    const filterRects = await Promise.all(filterButtons.map(btn => btn.boundingBox()));
    const sortRects = await Promise.all(sortButtons.map(btn => btn.boundingBox()));

    const maxFilterBottom = Math.max(...filterRects.map(r => r.y + r.height));
    const minSortTop = Math.min(...sortRects.map(r => r.y));

    check(`${w}px: sorts row is below filters row`, maxFilterBottom <= minSortTop,
      `maxFilterBottom=${maxFilterBottom.toFixed(0)}, minSortTop=${minSortTop.toFixed(0)}`);
  }

  // No button should be alone on a line
  // This is inherent from the above checks

  // No horizontal scroll at this width
  const scrollWidth = await p.evaluate(() => document.documentElement.scrollWidth);
  const innerWidth = await p.evaluate(() => window.innerWidth);
  check(`${w}px: no horizontal scroll`, scrollWidth <= innerWidth,
    `scrollWidth=${scrollWidth}, innerWidth=${innerWidth}`);

  // Test clicking a filter button (scroll into view if needed)
  const finalBtn = await p.$('[data-testid=filters] [data-f=final]');
  if (finalBtn) {
    // Scroll into view if needed
    await p.evaluate(() => {
      const btn = document.querySelector('[data-testid=filters] [data-f=final]');
      if (btn) btn.scrollIntoViewIfNeeded();
    });

    // Click it
    await finalBtn.click();

    // Check aria-pressed
    const ariaPressed = await finalBtn.getAttribute('aria-pressed');
    check(`${w}px: clicking filter sets aria-pressed="true"`, ariaPressed === 'true',
      `aria-pressed="${ariaPressed}"`);
  }

  // Check label is fully inside toolbar rect at this width
  if (sortLabel) {
    const toolbar = await p.$('[data-toolbar]');
    const toolbarBox = await toolbar.boundingBox();
    const labelBox = await sortLabel.boundingBox();

    check(`${w}px: label fully visible in toolbar (left ≥ toolbar left)`,
      labelBox.x >= toolbarBox.x - 0.5,
      `label.x=${labelBox.x.toFixed(1)}, toolbar.x=${toolbarBox.x.toFixed(1)}`);

    check(`${w}px: label fully visible in toolbar (right ≤ toolbar right)`,
      labelBox.x + labelBox.width <= toolbarBox.x + toolbarBox.width + 0.5,
      `label.right=${(labelBox.x + labelBox.width).toFixed(1)}, toolbar.right=${(toolbarBox.x + toolbarBox.width).toFixed(1)}`);
  }

  // Check no console errors
  check(`${w}px: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Take screenshot
  await shot(p, `D9-${w}`, '[data-toolbar]');
  await done(p);
}

// Test at 1440 - everything on one row
{
  const w = 1440;
  const p = await open('/?sample=1&scene=live', w);

  await scrollTo(p, '[data-toolbar]', 1200);

  const filterButtons = await p.$$('[data-testid=filters] button');
  const sortButtons = await p.$$('[data-testid=sorts] button');
  const sortLabel = await p.$('.tg-lbl');

  if (filterButtons.length > 0 && sortButtons.length > 0 && sortLabel) {
    const filterRects = await Promise.all(filterButtons.map(btn => btn.boundingBox()));
    const sortRects = await Promise.all(sortButtons.map(btn => btn.boundingBox()));
    const sortLabelBox = await sortLabel.boundingBox();

    // All buttons should share one row (tops within ±2px)
    let allButtonsOnOneRow = true;
    const firstButtonTop = filterRects[0].y;
    for (let i = 1; i < filterRects.length; i++) {
      if (Math.abs(filterRects[i].y - firstButtonTop) > 2) {
        allButtonsOnOneRow = false;
        break;
      }
    }
    for (let i = 0; i < sortRects.length; i++) {
      if (Math.abs(sortRects[i].y - firstButtonTop) > 2) {
        allButtonsOnOneRow = false;
        break;
      }
    }

    check(`1440px: all buttons share one row (within ±2px)`, allButtonsOnOneRow,
      `filter tops: ${filterRects.map(r => r.y.toFixed(0)).join(', ')}, sort tops: ${sortRects.map(r => r.y.toFixed(0)).join(', ')}`);

    // Check label vertical alignment: label centre-y should match sort button centre-y within ±3px
    const firstSortBox = sortRects[0];
    const labelCentreY = sortLabelBox.y + sortLabelBox.height / 2;
    const sortCentreY = firstSortBox.y + firstSortBox.height / 2;
    check(`1440px: label vertically aligned with sort buttons (±3px)`,
      Math.abs(labelCentreY - sortCentreY) <= 3,
      `label centre=${labelCentreY.toFixed(1)}, sort centre=${sortCentreY.toFixed(1)}`);
  }

  // Toolbar height ≤ 48px at 1440
  const toolbar = await p.$('[data-toolbar]');
  const toolbarBox = await toolbar.boundingBox();
  check(`1440px: toolbar height ≤ 48px`, toolbarBox.height <= 48,
    `height=${toolbarBox.height.toFixed(0)}`);

  check(`1440px: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  await shot(p, `D9-1440`, '[data-toolbar]');
  await done(p);
}

await close();
report();
