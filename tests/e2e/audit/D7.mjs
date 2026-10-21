// D7: Team names ellipsize, records stay visible
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

// Test at multiple widths and scenes
for (const w of WIDTHS) {
  for (const scene of ['live', 'final']) {
    const p = await open(`/?sample=1&scene=${scene}`, w);

    // Check for no console errors
    check(`${w} ${scene}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // Get all tickets first
    const tickets = await p.$$('.ticket');
    check(`${w} ${scene}: tickets found`, tickets.length > 0, `found ${tickets.length}`);

    if (tickets.length === 0) {
      await done(p);
      continue;
    }

    // Scroll to first ticket to trigger reveal
    await scrollTo(p, '.ticket:first-child', 1500);

    // Check first ticket's match section using locators
    const tnameLocators = await p.locator('.ticket:first-child .tname').all();
    check(`${w} ${scene}: first ticket has team names`, tnameLocators.length > 0, `found ${tnameLocators.length}`);

    for (let i = 0; i < tnameLocators.length; i++) {
      const tnameLocator = tnameLocators[i];
      const tnameRect = await tnameLocator.boundingBox();

      const scoreLocators = await p.locator('.ticket:first-child .match > .score').all();
      const scoreLocator = scoreLocators[i] || null;
      const scoreRect = scoreLocator ? await scoreLocator.boundingBox() : null;

      // Check for .tn-n (name span)
      const tnnCount = await tnameLocator.locator('.tn-n').count();
      check(`${w} ${scene} tname${i}: has .tn-n`, tnnCount > 0);

      // Check for .tn-r (record span)
      const tnrCount = await tnameLocator.locator('.tn-r').count();
      check(`${w} ${scene} tname${i}: has .tn-r`, tnrCount > 0);

      if (tnrCount > 0) {
        const tnrLocator = tnameLocator.locator('.tn-r');
        const tnrRect = await tnrLocator.boundingBox();
        const tnrText = await tnrLocator.textContent();

        // .tn-r text should match /^ · \d+[–-]\d+$/
        check(`${w} ${scene} tname${i}: .tn-r text matches record pattern`,
          /^ · \d+[–-]\d+$/.test(tnrText),
          `got: "${tnrText}"`);

        // .tn-r should be fully visible: rect inside .tname
        if (tnrRect && tnameRect) {
          check(`${w} ${scene} tname${i}: .tn-r rect inside .tname`,
            tnrRect.x >= tnameRect.x && tnrRect.x + tnrRect.width <= tnameRect.x + tnameRect.width,
            `tnr: [${tnrRect.x},${tnrRect.x + tnrRect.width}] tname: [${tnameRect.x},${tnameRect.x + tnameRect.width}]`);
        }

        // .tn-r.scrollWidth <= .tn-r.clientWidth + 1 (not truncated)
        const tnrScrollWidth = await tnrLocator.evaluate(el => el.scrollWidth);
        const tnrClientWidth = await tnrLocator.evaluate(el => el.clientWidth);
        check(`${w} ${scene} tname${i}: .tn-r not truncated`,
          tnrScrollWidth <= tnrClientWidth + 1,
          `scrollWidth=${tnrScrollWidth} clientWidth=${tnrClientWidth}`);

        // .tname rect right should not overlap with score
        if (scoreRect && tnameRect) {
          const noOverlap = tnameRect.x + tnameRect.width <= scoreRect.x;
          check(`${w} ${scene} tname${i}: no overlap with score`,
            noOverlap,
            `tname: [${tnameRect.x},${tnameRect.x + tnameRect.width}] score: [${scoreRect.x},${scoreRect.x + scoreRect.width}]`);
        }
      }
    }

    // Check no horizontal overflow at viewport
    const htmlEl = await p.$('html');
    const htmlWidth = await htmlEl.evaluate(el => el.scrollWidth);
    const vpWidth = w;
    check(`${w} ${scene}: no horizontal overflow`,
      htmlWidth <= vpWidth + 1,
      `html scrollWidth=${htmlWidth} viewport=${vpWidth}`);

    // Take screenshots (only for live scenes)
    if (scene === 'live') {
      await shot(p, `D7-before-${w}`, '.ticket:first-child .match');
    }

    await done(p);
  }
}

await close();
report();
