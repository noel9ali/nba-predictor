// D10: Glance rows ≤ 900px: teams above the court, court full width
import { open, done, close, check, report, shot, scrollTo, WIDTHS, intersects } from './lib.mjs';

async function testWidth(w, scenes = ['live', 'final', 'edges']) {
  for (const scene of scenes) {
    const page = await open(`/?sample=1&scene=${scene}`, w);

    // Scroll to courts
    await scrollTo(page, '[data-testid=chart]', 500);

    // Get all glance rows
    const rows = await page.$$('[data-testid=chart] .gl');
    if (rows.length === 0) {
      check(`${w} ${scene}: found glance rows`, false, 'no .gl elements');
      await done(page);
      continue;
    }

    // Test each row
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];

      // Get bounding rects for key elements
      const rowRect = await row.evaluate(el => el.getBoundingClientRect());
      const lab = await row.$('.gl__lab');
      const st = await row.$('.gl__st');
      const courtStrip = await row.$('.court-strip');

      if (!courtStrip) {
        check(`${w} ${scene} row${i}: has court-strip`, false, 'no .court-strip');
        continue;
      }

      const labRect = lab ? await lab.evaluate(el => el.getBoundingClientRect()) : null;
      const stRect = st ? await st.evaluate(el => el.getBoundingClientRect()) : null;
      const courtStripRect = await courtStrip.evaluate(el => el.getBoundingClientRect());

      // ===== Width checks: at 768/820/900, court-strip should be ≥90% of row width =====
      if ([768, 820, 900].includes(w)) {
        const courtWidthPct = (courtStripRect.width / rowRect.width) * 100;
        check(
          `${w} ${scene} row${i}: court ≥90% of row width`,
          courtWidthPct >= 90,
          `${courtWidthPct.toFixed(1)}%`
        );
      }

      // ===== Position checks: at 768/820/900, court-strip should be below labels =====
      if ([768, 820, 900].includes(w)) {
        if (labRect && stRect) {
          const labBottom = labRect.bottom;
          const stBottom = stRect.bottom;
          const labStBottom = Math.max(labBottom, stBottom);
          const courtTop = courtStripRect.top;

          check(
            `${w} ${scene} row${i}: court below labels`,
            courtTop >= labStBottom - 1, // -1 for rounding tolerance
            `court@${courtTop.toFixed(0)}, labels@${labStBottom.toFixed(0)}`
          );

          // Check that lab and st don't intersect
          check(
            `${w} ${scene} row${i}: label and status don't overlap`,
            !intersects(labRect, stRect, -1),
            `lab rect [${labRect.left.toFixed(0)}, ${labRect.top.toFixed(0)}, ${labRect.width.toFixed(0)}w x ${labRect.height.toFixed(0)}h] vs st [${stRect.left.toFixed(0)}, ${stRect.top.toFixed(0)}, ${stRect.width.toFixed(0)}w x ${stRect.height.toFixed(0)}h]`
          );
        }
      }

      // ===== Layout check: at >900px (901+), should be 3-column (court left of status) =====
      if (w >= 901) {
        if (labRect && courtStripRect && stRect) {
          // In 3-column: label on left, court in middle, status on right
          // Check that label-right < court-right < status-left (roughly)
          const isThreeColumn = labRect.right <= courtStripRect.right && courtStripRect.right <= stRect.left;
          check(
            `${w} ${scene} row${i}: 3-column layout (label < court < status horizontally)`,
            isThreeColumn,
            `label.right=${labRect.right.toFixed(0)}, court.right=${courtStripRect.right.toFixed(0)}, status.left=${stRect.left.toFixed(0)}`
          );
        }
      }

      // ===== Tag containment: all .tag rects inside court-strip =====
      const tags = await courtStrip.$$('.tag');
      for (let ti = 0; ti < tags.length; ti++) {
        const tagRect = await tags[ti].evaluate(el => el.getBoundingClientRect());

        const tagInside = (
          tagRect.left >= courtStripRect.left - 1 &&
          tagRect.right <= courtStripRect.right + 1 &&
          tagRect.top >= courtStripRect.top - 1 &&
          tagRect.bottom <= courtStripRect.bottom + 1
        );
        check(
          `${w} ${scene} row${i} tag${ti}: inside court-strip`,
          tagInside,
          `tag [${tagRect.left.toFixed(0)}, ${tagRect.top.toFixed(0)}, ${tagRect.width.toFixed(0)}w x ${tagRect.height.toFixed(0)}h] vs court [${courtStripRect.left.toFixed(0)}, ${courtStripRect.top.toFixed(0)}, ${courtStripRect.width.toFixed(0)}w x ${courtStripRect.height.toFixed(0)}h]`
        );
      }
    }

    // Check console errors (ignore 404s from sample data resources)
    const relevantErrors = page.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
    check(`${w} ${scene}: no console errors`, relevantErrors.length === 0, relevantErrors.join(' | '));

    // Take screenshot
    await shot(page, `D10-${w}-${scene}`, '[data-testid=chart]');

    await done(page);
  }
}

// Test at key widths
for (const w of [768, 820, 900, 901, 1440]) {
  await testWidth(w);
}

await close();
report();
