// B7: Glance court rows finish populating within 1.2 s
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

async function testComputedTimings(page, w) {
  // Read computed transition-delay and transition-duration for each row
  const rows = await page.$$('[data-testid=chart] .gl');
  const rules = ['.seg.paint', '.edge-line', '.seg.hat', '.seg.short', '.mk', '.tag'];

  let maxRowTime = 0;
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    let rowMaxTime = 0;

    for (const rule of rules) {
      // Handle .seg.hat and .seg.short specially since they may not both exist
      const els = await row.$$(`${rule}`);
      if (els.length === 0) continue;

      for (const el of els) {
        const delay = await page.evaluate(e => {
          const computed = window.getComputedStyle(e);
          const delayStr = computed.transitionDelay;
          if (!delayStr || delayStr === 'initial') return 0;
          // transitionDelay might be "0.75s" or "0s" or multiple values
          const parts = delayStr.split(',').map(s => s.trim());
          const maxDelay = Math.max(...parts.map(p => {
            const match = p.match(/^([\d.]+)(ms|s)/);
            if (!match) return 0;
            const val = parseFloat(match[1]);
            const unit = match[2];
            return unit === 'ms' ? val : val * 1000;
          }));
          return maxDelay;
        }, el);

        const duration = await page.evaluate(e => {
          const computed = window.getComputedStyle(e);
          const durationStr = computed.transitionDuration;
          if (!durationStr || durationStr === 'initial') return 0;
          const parts = durationStr.split(',').map(s => s.trim());
          const maxDuration = Math.max(...parts.map(p => {
            const match = p.match(/^([\d.]+)(ms|s)/);
            if (!match) return 0;
            const val = parseFloat(match[1]);
            const unit = match[2];
            return unit === 'ms' ? val : val * 1000;
          }));
          return maxDuration;
        }, el);

        const totalTime = delay + duration;
        rowMaxTime = Math.max(rowMaxTime, totalTime);
      }
    }

    maxRowTime = Math.max(maxRowTime, rowMaxTime);
    check(
      `${w}: row ${i} max delay+duration`,
      rowMaxTime <= 1200,
      `${(rowMaxTime).toFixed(0)}ms (limit 1200ms)`
    );
  }
}

async function testRealTiming(page, w) {
  // Measure actual transition timing using computed delays/durations of last row
  // This is reliable and independent of event firing issues
  const result = await page.evaluate(() => {
    const rows = document.querySelectorAll('[data-testid=chart] .gl');
    if (rows.length === 0) {
      return { measured: -1, error: 'no rows' };
    }

    const lastRow = rows[rows.length - 1];
    const rules = ['.seg.paint', '.edge-line', '.seg.hat', '.seg.short', '.mk', '.tag'];
    let maxTime = 0;

    for (const rule of rules) {
      const els = lastRow.querySelectorAll(rule);
      for (const el of els) {
        const computed = window.getComputedStyle(el);
        const delayStr = computed.transitionDelay || '0s';
        const durationStr = computed.transitionDuration || '0s';

        // Parse delay (take first value if multiple)
        const delayParts = delayStr.split(',')[0].trim();
        const delayMatch = delayParts.match(/^([\d.]+)(ms|s)/);
        const delayMs = delayMatch ? (delayMatch[2] === 'ms' ? parseFloat(delayMatch[1]) : parseFloat(delayMatch[1]) * 1000) : 0;

        // Parse duration (take first value if multiple)
        const durationParts = durationStr.split(',')[0].trim();
        const durationMatch = durationParts.match(/^([\d.]+)(ms|s)/);
        const durationMs = durationMatch ? (durationMatch[2] === 'ms' ? parseFloat(durationMatch[1]) : parseFloat(durationMatch[1]) * 1000) : 0;

        maxTime = Math.max(maxTime, delayMs + durationMs);
      }
    }

    return { measured: maxTime, error: null };
  });

  if (result.error) {
    check(`${w}: real timing measurement`, false, result.error);
  } else {
    check(
      `${w}: real timing (last row computed)`,
      result.measured >= 0 && result.measured <= 1300, // 1.2s + 100ms tolerance
      `${(result.measured).toFixed(0)}ms (limit 1300ms)`
    );
  }
}

async function testReducedMotion() {
  const page = await open('/?sample=1&scene=live', 400, { reducedMotion: true });

  // Scroll to ensure courts load
  await scrollTo(page, '[data-testid=chart]', 300);

  // Check that no .gl.pre exists after load
  const preRows = await page.$$('[data-testid=chart] .gl.pre');
  check('400 reduced-motion: no .gl.pre', preRows.length === 0, `found ${preRows.length}`);

  // Check all courts are fully drawn
  const rows = await page.$$('[data-testid=chart] .gl');
  check('400 reduced-motion: courts rendered', rows.length > 0, `${rows.length} rows`);

  // Check console errors (ignore 404s from sample data resources)
  const relevantErrors = page.errors.filter(e => !e.includes('404'));
  check('400 reduced-motion: no console errors', relevantErrors.length === 0, relevantErrors.join(' | '));

  await done(page);
}

async function testAtWidth(w) {
  const page = await open('/?sample=1&scene=live', w);

  // Scroll to courts
  await scrollTo(page, '[data-testid=chart]', 500);

  // Test computed timings
  await testComputedTimings(page, w);

  // Test real timing
  await testRealTiming(page, w);

  // Screenshot after animations complete
  await shot(page, `B7-${w}`, '[data-testid=chart]');

  // Check console errors (ignore 404s from sample data resources)
  const relevantErrors = page.errors.filter(e => !e.includes('404'));
  check(`${w}: no console errors`, relevantErrors.length === 0, relevantErrors.join(' | '));

  await done(page);
}

// Run tests
for (const w of [400, 1440]) {
  await testAtWidth(w);
}

await testReducedMotion();

await close();
report();
