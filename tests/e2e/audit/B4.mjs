// B4: Tale-of-the-tape bars use fixed scale per stat, not max of pair.
import { open, done, close, check, report, WIDTHS } from './lib.mjs';

async function testTapeRows(width) {
  const p = await open('/?sample=1&scene=live', width);

  // Test 3 different game drawers
  for (let gameIdx = 0; gameIdx < 3; gameIdx++) {
    // Click the first/next ticket to open drawer
    const ticketSelector = `.ticket[data-id]:nth-of-type(${gameIdx + 1}) .ticket__hit`;
    const ticket = await p.$(ticketSelector);
    if (!ticket) {
      check(`${width}px game ${gameIdx}: ticket exists`, false, 'no such ticket');
      continue;
    }

    await ticket.click();

    // Wait for tape rows to load
    const tapeRows = await p.waitForSelector('.drawer [data-tape] .tt', { timeout: 5000 }).catch(() => null);
    if (!tapeRows) {
      check(`${width}px game ${gameIdx}: tape rows load`, false, 'timeout waiting for .tt');
      continue;
    }

    // Get all tape rows in the drawer
    const rows = await p.$$('.drawer [data-tape] .tt');
    check(`${width}px game ${gameIdx}: has tape rows`, rows.length > 0, `${rows.length} rows`);

    // For each row, verify bar scaling
    let rowsChecked = 0;
    for (const row of rows) {
      // Get the two values (left and right)
      const values = await row.$$eval('.v', els => els.map(el => parseFloat(el.textContent)));
      if (values.length < 2) continue;
      const [aVal, hVal] = values;

      // Get the two bar widths (left and right inner bars)
      const barEls = await row.$$('.b i');
      if (barEls.length < 2) continue;

      const aBox = await barEls[0].boundingBox();
      const hBox = await barEls[1].boundingBox();

      if (!aBox || !hBox) continue;
      const aWidth = aBox.width;
      const hWidth = hBox.width;

      // Check 1: If values are equal, bar widths should be equal (±0.5px)
      if (Math.abs(aVal - hVal) < 0.01) {
        const widthDiff = Math.abs(aWidth - hWidth);
        check(`${width}px game ${gameIdx} row ${rowsChecked}: equal values => equal widths`,
          widthDiff <= 0.5,
          `vals ${aVal.toFixed(2)} vs ${hVal.toFixed(2)}, widths ${aWidth.toFixed(2)} vs ${hWidth.toFixed(2)}`);
      }

      rowsChecked++;
    }

    if (rowsChecked > 0) {
      check(`${width}px game ${gameIdx}: checked ${rowsChecked} tape rows`, true, '');
    }

    // Close drawer with Escape
    await p.keyboard.press('Escape');
    await p.waitForTimeout(300);
  }

  // Test the pure tapeWidth helper function
  const tapeWidthTest = await p.evaluate(async () => {
    const m = await import('/static/js/tonight/drawer.js');
    if (typeof m.tapeWidth !== 'function') {
      return { error: 'tapeWidth not exported' };
    }

    const w0 = m.tapeWidth('rest_days', 0);
    const w1 = m.tapeWidth('roll_pts', 110);
    const w2 = m.tapeWidth('roll_pts', 104);

    return {
      restDaysZero: w0,
      pts110: w1,
      pts104: w2,
      diff: w1 - w2
    };
  });

  check(`${width}px: tapeWidth exported`, !tapeWidthTest.error, tapeWidthTest.error || '');
  if (!tapeWidthTest.error) {
    check(`${width}px: tapeWidth('rest_days', 0) === 0`, tapeWidthTest.restDaysZero === 0, `got ${tapeWidthTest.restDaysZero}`);
    check(`${width}px: tapeWidth('roll_pts', 110) - tapeWidth('roll_pts', 104) >= 20`,
      tapeWidthTest.diff >= 20,
      `diff = ${tapeWidthTest.diff.toFixed(2)}% (110=${tapeWidthTest.pts110.toFixed(1)}%, 104=${tapeWidthTest.pts104.toFixed(1)}%)`);
  }

  // Check no console errors
  check(`${width}px: no console errors`, p.errors.length === 0, p.errors.slice(0, 3).join(' | '));

  await done(p);
}

// Run tests at all widths
for (const w of WIDTHS) {
  await testTapeRows(w);
}

await close();
report();
