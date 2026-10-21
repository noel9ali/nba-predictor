// B1 · Keyboard focus must never land under the fixed ribbon (WCAG 2.4.11)
import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

async function testWidth(width, reducedMotion = false) {
  const opts = { reducedMotion, settle: 500 };
  const p = await open('/?sample=1&scene=live', width, opts);

  // Scroll so the board is just above the viewport and ribbon.on appears
  const tape = await p.$('[data-testid=tape]');
  const tapeRect = await tape.evaluate(el => {
    const r = el.getBoundingClientRect();
    const scrollY = window.scrollY;
    return { bottom: r.bottom + scrollY, top: r.top + scrollY };
  });

  await p.evaluate((tapeBottom) => {
    window.scrollTo(0, tapeBottom + 10);
  }, tapeRect.bottom);

  // Wait for ribbon transition to finish
  await p.waitForTimeout(reducedMotion ? 100 : 600);

  // Verify ribbon is on
  const ribbonVisible = await p.evaluate(() => {
    const ribbon = document.querySelector('[data-ribbon]');
    return ribbon && ribbon.classList.contains('on');
  });
  check(`${width}${reducedMotion ? ' (reduced motion)' : ''}: ribbon is on`, ribbonVisible);

  // Helper to get ribbon bottom, active element rect, check if inside ribbon/drawer
  const getRibbonBottom = () => p.evaluate(() => {
    const ribbon = document.querySelector('[data-ribbon]');
    if (!ribbon || !ribbon.classList.contains('on')) return null;
    const rect = ribbon.getBoundingClientRect();
    return rect.bottom;
  });

  const getActiveElementInfo = () => p.evaluate(() => {
    const active = document.activeElement;
    const rect = active.getBoundingClientRect();
    const inRibbon = document.querySelector('[data-ribbon]')?.contains(active);
    const inDrawer = document.querySelector('.drawer')?.contains(active);
    return {
      top: rect.top,
      insideRibbon: inRibbon,
      insideDrawer: inDrawer,
      tag: active.tagName,
      id: active.id,
      cls: active.className
    };
  });

  // Set focus on first .gl__hit
  const firstHit = await p.$('.gl__hit');
  if (firstHit) {
    await firstHit.focus();
  }

  let failCount = 0;

  // Tab 25 times
  console.log(`\nTesting Tab at width ${width}...`);
  for (let i = 0; i < 25; i++) {
    await p.keyboard.press('Tab');
    await p.waitForTimeout(50);

    const ribbonBottom = await getRibbonBottom();
    if (ribbonBottom !== null) {
      const info = await getActiveElementInfo();
      if (!info.insideRibbon && !info.insideDrawer) {
        const pass = info.top >= ribbonBottom - 0.5;
        if (!pass) {
          failCount++;
          check(
            `Tab ${i + 1}: focus not under ribbon (top >= ${ribbonBottom - 0.5})`,
            pass,
            `actual top: ${info.top}, element: ${info.tag}.${info.cls}`
          );
        } else {
          check(
            `Tab ${i + 1}: focus not under ribbon`,
            true
          );
        }
      }
    }
  }

  // Take a screenshot after the last Tab lands
  await shot(p, `B1${reducedMotion ? '-rm' : ''}-before-${width}`, '#tonight');

  // Shift+Tab 10 times
  console.log(`\nTesting Shift+Tab at width ${width}...`);
  for (let i = 0; i < 10; i++) {
    await p.keyboard.press('Shift+Tab');
    await p.waitForTimeout(50);

    const ribbonBottom = await getRibbonBottom();
    if (ribbonBottom !== null) {
      const info = await getActiveElementInfo();
      if (!info.insideRibbon && !info.insideDrawer) {
        const pass = info.top >= ribbonBottom - 0.5;
        if (!pass) {
          failCount++;
          check(
            `Shift+Tab ${i + 1}: focus not under ribbon (top >= ${ribbonBottom - 0.5})`,
            pass,
            `actual top: ${info.top}, element: ${info.tag}.${info.cls}`
          );
        } else {
          check(
            `Shift+Tab ${i + 1}: focus not under ribbon`,
            true
          );
        }
      }
    }
  }

  // Check no console errors
  check(`${width}${reducedMotion ? ' (reduced motion)' : ''}: no console errors`, p.errors.length === 0, p.errors.slice(0, 3).join(' | '));

  // Check no horizontal overflow
  const hasHOverflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  check(`${width}${reducedMotion ? ' (reduced motion)' : ''}: no horizontal overflow`, !hasHOverflow);

  await done(p);
}

async function run() {
  // Test all standard widths
  for (const w of WIDTHS) {
    await testWidth(w);
  }

  // Test reduced motion at 400
  await testWidth(400, true);

  await close();
  report();
}

run().catch(e => {
  console.error('Test error:', e);
  process.exitCode = 1;
});
