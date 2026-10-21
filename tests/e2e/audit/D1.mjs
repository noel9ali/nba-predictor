import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

const PHONE_WIDTHS = [320, 360, 400, 480];
const DESKTOP_WIDTHS = [768, 1440];

function rectsIntersect(r1, r2, tolerance = 0) {
  return !(r1.right + tolerance < r2.left || r2.right + tolerance < r1.left ||
           r1.bottom + tolerance < r2.top || r2.bottom + tolerance < r1.top);
}

// Test phone widths (≤ 480px)
for (const w of PHONE_WIDTHS) {
  // Test Tonight page
  const p = await open('/?sample=1&scene=live', w);

  // Get header measurements
  const headerMetrics = await p.evaluate(() => {
    const header = document.querySelector('header.top');
    const brand = document.querySelector('.brand');
    const brandB = brand.querySelector('b');
    const tabs = document.querySelectorAll('.tabs a');
    const topR = document.querySelector('.top__r');
    const sampleTag = document.querySelector('.sample-tag');
    const status = document.querySelector('.status');

    const headerRect = header.getBoundingClientRect();
    const brandRect = { top: brand.getBoundingClientRect().top, left: brand.getBoundingClientRect().left, right: brand.getBoundingClientRect().right, bottom: brand.getBoundingClientRect().bottom };
    const brandBRects = Array.from(brandB.getClientRects());
    const tabRects = Array.from(tabs).map(t => t.getBoundingClientRect());
    const sampleTagRect = sampleTag && !sampleTag.hidden ? { top: sampleTag.getBoundingClientRect().top, left: sampleTag.getBoundingClientRect().left, right: sampleTag.getBoundingClientRect().right, bottom: sampleTag.getBoundingClientRect().bottom } : null;
    const statusRect = status && !status.hidden ? { top: status.getBoundingClientRect().top, left: status.getBoundingClientRect().left, right: status.getBoundingClientRect().right, bottom: status.getBoundingClientRect().bottom } : null;

    const topRVisible = Array.from(topR.children).filter(c => !c.hidden);
    const topRRects = topRVisible.map(t => ({ top: t.getBoundingClientRect().top, left: t.getBoundingClientRect().left, right: t.getBoundingClientRect().right, bottom: t.getBoundingClientRect().bottom }));

    return {
      headerHeight: headerRect.height,
      headerTop: headerRect.top,
      headerBottom: headerRect.bottom,
      headerLeft: headerRect.left,
      headerRight: headerRect.right,
      brandRect,
      brandBHeight: Math.max(...brandBRects.map(r => r.height)),
      tabTops: tabRects.map(r => r.top),
      tabHeights: tabRects.map(r => r.height),
      sampleTagRect,
      statusRect,
      topRRects,
      pageScrollWidth: document.documentElement.scrollWidth,
      pageInnerWidth: window.innerWidth,
    };
  });

  const allTabsOneSameTop = headerMetrics.tabTops.length > 0 &&
    headerMetrics.tabTops.every(t => Math.abs(t - headerMetrics.tabTops[0]) < 2);
  const allTabsAbove44px = headerMetrics.tabHeights.every(h => h >= 44);
  const topROneSameRow = headerMetrics.topRRects.length > 0 &&
    headerMetrics.topRRects.every(t => Math.abs(t.top - headerMetrics.topRRects[0].top) < 2);
  const topRInsideHeader = headerMetrics.topRRects.every(t => t.bottom <= headerMetrics.headerBottom + 2 && t.top >= headerMetrics.headerTop);
  const noPageScroll = headerMetrics.pageScrollWidth <= headerMetrics.pageInnerWidth;
  const brandOneLine = headerMetrics.brandBHeight < 30;

  // Check for overlaps between brand, sample-tag, and status
  const visibleElements = [];
  if (headerMetrics.brandRect) visibleElements.push({ name: 'brand', rect: headerMetrics.brandRect });
  if (headerMetrics.sampleTagRect) visibleElements.push({ name: 'sample-tag', rect: headerMetrics.sampleTagRect });
  if (headerMetrics.statusRect) visibleElements.push({ name: 'status', rect: headerMetrics.statusRect });

  let overlaps = [];
  for (let i = 0; i < visibleElements.length; i++) {
    for (let j = i + 1; j < visibleElements.length; j++) {
      if (rectsIntersect(visibleElements[i].rect, visibleElements[j].rect, 0)) {
        overlaps.push(`${visibleElements[i].name} overlaps ${visibleElements[j].name}`);
      }
    }
  }

  // Check all elements inside header
  const allInsideHeader = visibleElements.every(e =>
    e.rect.top >= headerMetrics.headerTop &&
    e.rect.bottom <= headerMetrics.headerBottom &&
    e.rect.left >= headerMetrics.headerLeft &&
    e.rect.right <= headerMetrics.headerRight
  );

  check(`${w}px Tonight: header height ≤ 120`, headerMetrics.headerHeight <= 120, `${headerMetrics.headerHeight}px`);
  check(`${w}px Tonight: all 4 tabs on one row`, allTabsOneSameTop, `Tab tops: ${headerMetrics.tabTops}`);
  check(`${w}px Tonight: all tabs min-height ≥ 44`, allTabsAbove44px, `Tab heights: ${headerMetrics.tabHeights}`);
  check(`${w}px Tonight: .top__r on one row`, topROneSameRow, `Top-r tops: ${headerMetrics.topRRects.map(t => t.top)}`);
  check(`${w}px Tonight: no overlaps (brand/sample/status)`, overlaps.length === 0, overlaps.join('; '));
  check(`${w}px Tonight: all elements inside header`, allInsideHeader, 'element outside bounds');
  check(`${w}px Tonight: brand on one line`, brandOneLine, `brand b height: ${headerMetrics.brandBHeight}`);
  check(`${w}px Tonight: no page horizontal scroll`, noPageScroll, `scrollWidth ${headerMetrics.pageScrollWidth} vs ${headerMetrics.pageInnerWidth}`);
  check(`${w}px Tonight: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  await shot(p, `D1-${w}`, 'header.top');
  await done(p);
}

// Test Model page at 400px
const pModel = await open('/model?sample=1', 400);
const modelMetrics = await pModel.evaluate(() => {
  const header = document.querySelector('header.top');
  const brand = document.querySelector('.brand');
  const brandB = brand.querySelector('b');
  const tabs = document.querySelectorAll('.tabs a');
  const topR = document.querySelector('.top__r');
  const sampleTag = document.querySelector('.sample-tag');
  const status = document.querySelector('.status');

  const headerRect = header.getBoundingClientRect();
  const brandRect = { top: brand.getBoundingClientRect().top, left: brand.getBoundingClientRect().left, right: brand.getBoundingClientRect().right, bottom: brand.getBoundingClientRect().bottom };
  const brandBRects = Array.from(brandB.getClientRects());
  const tabRects = Array.from(tabs).map(t => t.getBoundingClientRect());
  const sampleTagRect = sampleTag && !sampleTag.hidden ? { top: sampleTag.getBoundingClientRect().top, left: sampleTag.getBoundingClientRect().left, right: sampleTag.getBoundingClientRect().right, bottom: sampleTag.getBoundingClientRect().bottom } : null;
  const statusRect = status && !status.hidden ? { top: status.getBoundingClientRect().top, left: status.getBoundingClientRect().left, right: status.getBoundingClientRect().right, bottom: status.getBoundingClientRect().bottom } : null;

  const topRVisible = Array.from(topR.children).filter(c => !c.hidden);
  const topRRects = topRVisible.map(t => ({ top: t.getBoundingClientRect().top, left: t.getBoundingClientRect().left, right: t.getBoundingClientRect().right, bottom: t.getBoundingClientRect().bottom }));

  return {
    headerHeight: headerRect.height,
    headerTop: headerRect.top,
    headerBottom: headerRect.bottom,
    headerLeft: headerRect.left,
    headerRight: headerRect.right,
    brandRect,
    brandBHeight: Math.max(...brandBRects.map(r => r.height)),
    tabTops: tabRects.map(r => r.top),
    tabHeights: tabRects.map(r => r.height),
    sampleTagRect,
    statusRect,
    topRRects,
    pageScrollWidth: document.documentElement.scrollWidth,
    pageInnerWidth: window.innerWidth,
  };
});

const modelAllTabsOneSameTop = modelMetrics.tabTops.length > 0 &&
  modelMetrics.tabTops.every(t => Math.abs(t - modelMetrics.tabTops[0]) < 2);
const modelAllTabsAbove44px = modelMetrics.tabHeights.every(h => h >= 44);
const modelTopROneSameRow = modelMetrics.topRRects.length > 0 &&
  modelMetrics.topRRects.every(t => Math.abs(t.top - modelMetrics.topRRects[0].top) < 2);
const modelTopRInsideHeader = modelMetrics.topRRects.every(t => t.bottom <= modelMetrics.headerBottom + 2 && t.top >= modelMetrics.headerTop);
const modelNoPageScroll = modelMetrics.pageScrollWidth <= modelMetrics.pageInnerWidth;
const modelBrandOneLine = modelMetrics.brandBHeight < 30;

// Check for overlaps
const modelVisibleElements = [];
if (modelMetrics.brandRect) modelVisibleElements.push({ name: 'brand', rect: modelMetrics.brandRect });
if (modelMetrics.sampleTagRect) modelVisibleElements.push({ name: 'sample-tag', rect: modelMetrics.sampleTagRect });
if (modelMetrics.statusRect) modelVisibleElements.push({ name: 'status', rect: modelMetrics.statusRect });

let modelOverlaps = [];
for (let i = 0; i < modelVisibleElements.length; i++) {
  for (let j = i + 1; j < modelVisibleElements.length; j++) {
    if (rectsIntersect(modelVisibleElements[i].rect, modelVisibleElements[j].rect, 0)) {
      modelOverlaps.push(`${modelVisibleElements[i].name} overlaps ${modelVisibleElements[j].name}`);
    }
  }
}

const modelAllInsideHeader = modelVisibleElements.every(e =>
  e.rect.top >= modelMetrics.headerTop &&
  e.rect.bottom <= modelMetrics.headerBottom &&
  e.rect.left >= modelMetrics.headerLeft &&
  e.rect.right <= modelMetrics.headerRight
);

check(`400px Model: header height ≤ 120`, modelMetrics.headerHeight <= 120, `${modelMetrics.headerHeight}px`);
check(`400px Model: all 4 tabs on one row`, modelAllTabsOneSameTop, `Tab tops: ${modelMetrics.tabTops}`);
check(`400px Model: all tabs min-height ≥ 44`, modelAllTabsAbove44px, `Tab heights: ${modelMetrics.tabHeights}`);
check(`400px Model: .top__r on one row`, modelTopROneSameRow, `Top-r tops: ${modelMetrics.topRRects.map(t => t.top)}`);
check(`400px Model: no overlaps`, modelOverlaps.length === 0, modelOverlaps.join('; '));
check(`400px Model: all elements inside header`, modelAllInsideHeader, 'element outside bounds');
check(`400px Model: brand on one line`, modelBrandOneLine, `brand b height: ${modelMetrics.brandBHeight}`);
check(`400px Model: no page horizontal scroll`, modelNoPageScroll, `scrollWidth vs innerWidth`);
check(`400px Model: no console errors`, pModel.errors.length === 0, pModel.errors.join(' | '));

await shot(pModel, `D1-model-400`, 'header.top');
await done(pModel);

// Test desktop widths (768, 1440) - header should maintain original heights
for (const w of DESKTOP_WIDTHS) {
  const pDesktop = await open('/?sample=1&scene=live', w);
  const desktopMetrics = await pDesktop.evaluate(() => {
    const header = document.querySelector('header.top');
    return {
      headerHeight: header.getBoundingClientRect().height,
    };
  });

  // Note: these are the expected "before" values from the task description
  // Tonight: 182 at 768, 95 at 1440
  const expectedHeights = { 768: 182, 1440: 95 };
  const expectedHeight = expectedHeights[w];
  const tolerance = 2;

  check(`${w}px Tonight: header height ~${expectedHeight}px (unchanged)`,
    Math.abs(desktopMetrics.headerHeight - expectedHeight) <= tolerance,
    `${desktopMetrics.headerHeight}px (expected ~${expectedHeight})`);
  check(`${w}px Tonight: no console errors`, pDesktop.errors.length === 0, pDesktop.errors.join(' | '));

  await done(pDesktop);
}

await close();
report();
