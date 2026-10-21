// D3: No line breaks inside records, scores or money
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

async function testLede() {
  const scenes = ['final', 'live', 'nextup', 'nobets'];

  for (const scene of scenes) {
    for (const w of [320, 400, 768, 1440]) {
      const p = await open(`/?sample=1&scene=${scene}`, w);

      // Check console errors
      check(`lede ${scene}/${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

      // Check no horizontal overflow
      const overflowed = await p.evaluate(() => document.body.scrollWidth > document.body.clientWidth);
      check(`lede ${scene}/${w}: no horizontal overflow`, !overflowed);

      // For each .n span in the lede h1, check that getClientRects().length === 1
      const ledeSplits = await p.evaluate(() => {
        const hero = document.querySelector('[data-testid=hero]');
        if (!hero) return [];
        const spans = hero.querySelectorAll('.n');
        const results = [];
        for (const span of spans) {
          const rects = span.getClientRects();
          results.push({
            text: span.textContent,
            rectsLength: rects.length,
            rects: Array.from(rects).map(r => ({ top: r.top, left: r.left, width: r.width }))
          });
        }
        return results;
      });

      for (const item of ledeSplits) {
        check(`lede ${scene}/${w}: "${item.text}" no wrap`, item.rectsLength === 1,
          `Got ${item.rectsLength} rects: ${JSON.stringify(item.rects)}`);
      }

      // Take screenshot
      await shot(p, `D3-lede-${w}`, 'section.lede');
      await done(p);
    }
  }

  // Test past mode
  for (const w of [320, 400, 768, 1440]) {
    const p = await open('/?sample=1&date=2026-11-16', w);

    check(`lede past/${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    const overflowed = await p.evaluate(() => document.body.scrollWidth > document.body.clientWidth);
    check(`lede past/${w}: no horizontal overflow`, !overflowed);

    const ledeSplits = await p.evaluate(() => {
      const hero = document.querySelector('[data-testid=hero]');
      if (!hero) return [];
      const spans = hero.querySelectorAll('.n');
      const results = [];
      for (const span of spans) {
        const rects = span.getClientRects();
        results.push({
          text: span.textContent,
          rectsLength: rects.length
        });
      }
      return results;
    });

    for (const item of ledeSplits) {
      check(`lede past/${w}: "${item.text}" no wrap`, item.rectsLength === 1);
    }

    await done(p);
  }
}

async function testDrawer() {
  // Test drawer meta at different widths
  for (const w of [320, 400, 768, 1440]) {
    const p = await open(`/?sample=1&scene=final`, w);

    check(`drawer ${w}: no console errors at start`, p.errors.length === 0, p.errors.join(' | '));

    // Scroll to first ticket to make sure it's visible
    await scrollTo(p, '.ticket__hit', 1200);

    // Click the first ticket hit
    try {
      await p.click('.ticket__hit:first-of-type', { timeout: 5000 });
      await p.waitForTimeout(600);
    } catch (e) {
      check(`drawer ${w}: can open first ticket`, false, e.message);
      await done(p);
      continue;
    }

    // Get the meta element
    const metaEl = await p.$('[data-meta]');
    if (!metaEl) {
      check(`drawer ${w}: has [data-meta]`, false, 'Meta element not found');
      await done(p);
      continue;
    }

    // Get meta text content (for reference)
    const metaText = await metaEl.textContent();
    check(`drawer ${w}: meta text not empty`, metaText && metaText.trim().length > 0, metaText);

    // Check each .nw span has only 1 rect (no wrapping)
    const nwSplits = await p.evaluate(() => {
      const meta = document.querySelector('[data-meta]');
      if (!meta) return [];
      const spans = meta.querySelectorAll('.nw');
      const results = [];
      for (const span of spans) {
        const rects = span.getClientRects();
        results.push({
          text: span.textContent,
          rectsLength: rects.length,
          rects: Array.from(rects).map(r => ({ top: r.top, left: r.left, width: r.width }))
        });
      }
      return results;
    });

    for (const item of nwSplits) {
      check(`drawer ${w}: ".nw" "${item.text}" no wrap`, item.rectsLength === 1,
        `Got ${item.rectsLength} rects: ${JSON.stringify(item.rects)}`);
    }

    // Check no console errors during drawer interaction
    check(`drawer ${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // Check no horizontal overflow
    const overflowed = await p.evaluate(() => document.body.scrollWidth > document.body.clientWidth);
    check(`drawer ${w}: no horizontal overflow`, !overflowed);

    // Take screenshot of drawer panel
    await shot(p, `D3-drawer-${w}`, '.drawer .panel');

    // Close drawer with Escape
    await p.keyboard.press('Escape');
    await p.waitForTimeout(400);

    await done(p);
  }
}

await testLede();
await testDrawer();
await close();
report();
