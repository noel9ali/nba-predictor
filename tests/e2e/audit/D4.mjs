import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

// Helper to find visible hyphens that should be en dashes.
// Returns array of { element, text, matches } where matches are the hyphenated numbers found.
async function hyphens(page) {
  return await page.evaluate(() => {
    const HYPHEN_RE = /\d-\d/;
    const DATE_RE = /\d{4}-\d{2}-\d{2}/;
    const found = [];

    // Check text nodes
    const walker = document.createTreeWalker(
      document.documentElement,
      NodeFilter.SHOW_TEXT,
      null,
      false
    );
    let node;
    while (node = walker.nextNode()) {
      const text = node.textContent;
      if (HYPHEN_RE.test(text) && !DATE_RE.test(text)) {
        const parent = node.parentElement;
        if (parent && parent.offsetParent !== null) {
          found.push({ type: 'text', text: text.trim(), selector: parent.className });
        }
      }
    }

    // Check aria-label attributes
    document.querySelectorAll('[aria-label]').forEach(el => {
      const label = el.getAttribute('aria-label');
      if (label && HYPHEN_RE.test(label) && !DATE_RE.test(label)) {
        found.push({ type: 'aria-label', text: label, element: el.tagName });
      }
    });

    // Check title attributes
    document.querySelectorAll('[title]').forEach(el => {
      const title = el.getAttribute('title');
      if (title && HYPHEN_RE.test(title) && !DATE_RE.test(title)) {
        found.push({ type: 'title', text: title, element: el.tagName });
      }
    });

    // Check SVG titles
    document.querySelectorAll('svg title').forEach(el => {
      const text = el.textContent;
      if (text && HYPHEN_RE.test(text) && !DATE_RE.test(text)) {
        found.push({ type: 'svg-title', text: text, parent: el.parentElement.tagName });
      }
    });

    return found;
  });
}

// Test tonight page scenes
for (const scene of ['live', 'final', 'nobets', 'nextup', 'replay']) {
  for (const w of WIDTHS) {
    const p = await open(`/?sample=1&scene=${scene}`, w);

    // For first 3 tickets, open the drawer
    const ticketCount = Math.min(3, await p.evaluate(() => document.querySelectorAll('.ticket').length));
    for (let i = 0; i < ticketCount; i++) {
      const ticket = await p.evaluate((idx) => {
        const tickets = document.querySelectorAll('.ticket');
        if (idx < tickets.length) {
          const btn = tickets[idx].querySelector('.ticket__hit');
          if (btn) {
            btn.click();
            return tickets[idx].getAttribute('data-id');
          }
        }
        return null;
      }, i);

      if (ticket) {
        await p.waitForTimeout(300);
        const hyphenMatches = await hyphens(p);
        check(
          `${scene}-${w}: drawer #${i + 1} no hyphens`,
          hyphenMatches.length === 0,
          hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
        );

        if (i === 0) {
          await shot(p, `D4-drawer-${w}`, '.drawer [data-meta]');
        }

        // Close drawer
        await p.keyboard.press('Escape');
        await p.waitForTimeout(300);
      }
    }

    // Check bankroll tooltip for replay mode
    if (scene === 'replay' || scene === 'live' || scene === 'final') {
      const hasBankroll = await p.$('[data-testid=bankroll]');
      if (hasBankroll) {
        // Show tooltip for night 1
        await p.focus('[data-testid=bankroll]');
        await p.keyboard.press('ArrowLeft');
        await p.waitForTimeout(200);
        let hyphenMatches = await hyphens(p);
        check(
          `${scene}-${w}: bankroll tooltip night 1 no hyphens`,
          hyphenMatches.length === 0,
          hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
        );
        if (w === 1440 && scene === 'live') {
          await shot(p, `D4-tooltip-${w}`, '[data-testid=bankroll]');
        }

        // Navigate to middle night if possible
        const N = await p.evaluate(() => document.querySelectorAll('[data-testid=bankroll] svg circle.pk').length);
        if (N > 2) {
          for (let j = 0; j < Math.floor(N / 2); j++) {
            await p.keyboard.press('ArrowRight');
            await p.waitForTimeout(50);
          }
          await p.waitForTimeout(200);
          hyphenMatches = await hyphens(p);
          check(
            `${scene}-${w}: bankroll tooltip middle no hyphens`,
            hyphenMatches.length === 0,
            hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
          );
        }

        // Navigate to last night
        for (let j = 0; j < N; j++) {
          await p.keyboard.press('ArrowRight');
          await p.waitForTimeout(50);
        }
        await p.waitForTimeout(200);
        hyphenMatches = await hyphens(p);
        check(
          `${scene}-${w}: bankroll tooltip last no hyphens`,
          hyphenMatches.length === 0,
          hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
        );
      }
    }

    // For replay, advance through steps
    if (scene === 'replay') {
      for (let step = 0; step < 6; step++) {
        await p.evaluate(() => window.__sampleFeed.step());
        await p.waitForTimeout(200);
      }
    }

    const hyphenMatches = await hyphens(p);
    check(
      `${scene}-${w}: no hyphens in visible content`,
      hyphenMatches.length === 0,
      hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
    );

    const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
    check(
      `${scene}-${w}: no console errors`,
      errors.length === 0,
      errors.join(' | ')
    );

    await done(p);
  }
}

// Test past mode
for (const w of WIDTHS) {
  const p = await open('/?sample=1&date=2026-11-16', w);

  // Open drawers for first 3 tickets
  const ticketCount = Math.min(3, await p.evaluate(() => document.querySelectorAll('.ticket').length));
  for (let i = 0; i < ticketCount; i++) {
    const ticket = await p.evaluate((idx) => {
      const tickets = document.querySelectorAll('.ticket');
      if (idx < tickets.length) {
        const btn = tickets[idx].querySelector('.ticket__hit');
        if (btn) {
          btn.click();
          return tickets[idx].getAttribute('data-id');
        }
      }
      return null;
    }, i);

    if (ticket) {
      await p.waitForTimeout(300);
      const hyphenMatches = await hyphens(p);
      check(
        `past-${w}: drawer #${i + 1} no hyphens`,
        hyphenMatches.length === 0,
        hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
      );
      await p.keyboard.press('Escape');
      await p.waitForTimeout(300);
    }
  }

  // Check bankroll tooltip
  const hasBankroll = await p.$('[data-testid=bankroll]');
  if (hasBankroll) {
    await p.focus('[data-testid=bankroll]');
    await p.keyboard.press('ArrowLeft');
    await p.waitForTimeout(200);
    let hyphenMatches = await hyphens(p);
    check(
      `past-${w}: bankroll tooltip night 1 no hyphens`,
      hyphenMatches.length === 0,
      hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
    );
  }

  // Check step 3 text for hyphens
  const step3Text = await p.evaluate(() => {
    const el = document.querySelector('.bstep[data-bs="3"] .bstep__in p');
    return el ? el.textContent : '';
  });
  const hasHyphens = /\d-\d/.test(step3Text) && !/\d{4}-\d{2}-\d{2}/.test(step3Text);
  check(
    `past-${w}: step 3 copy no hyphens`,
    !hasHyphens,
    step3Text.slice(0, 100)
  );

  const hyphenMatches = await hyphens(p);
  check(
    `past-${w}: no hyphens in visible content`,
    hyphenMatches.length === 0,
    hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
  );

  const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
  check(
    `past-${w}: no console errors`,
    errors.length === 0,
    errors.join(' | ')
  );

  await done(p);
}

// Test model page
for (const w of WIDTHS) {
  const p = await open('/model?sample=1', w);

  // Get all season buttons
  const seasons = await p.evaluate(() => {
    const btns = document.querySelectorAll('#ch1 .seasonbar button');
    return Array.from(btns).map(b => b.textContent);
  });

  for (const season of seasons) {
    await p.click(`#ch1 .seasonbar button:has-text("${season}")`);
    await p.waitForTimeout(400);

    const hyphenMatches = await hyphens(p);
    check(
      `model-${w}: season "${season}" no hyphens`,
      hyphenMatches.length === 0,
      hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
    );
  }

  const hyphenMatches = await hyphens(p);
  check(
    `model-${w}: no hyphens in visible content`,
    hyphenMatches.length === 0,
    hyphenMatches.length > 0 ? hyphenMatches.map(m => m.text).join(', ') : 'pass'
  );

  const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
  check(
    `model-${w}: no console errors`,
    errors.length === 0,
    errors.join(' | ')
  );

  await done(p);
}

await close();
report();
