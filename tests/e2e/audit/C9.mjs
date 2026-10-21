import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

// Test: in #ch1 .board, dd containing a small should have small on its own line, no clipping, matching pattern
async function testModelBoard(page, width) {
  // Scroll to the board
  await scrollTo(page, '#ch1 .board', 1200);

  // Get all dd elements that contain a small using evaluate
  const results = await page.evaluate(() => {
    const dds = document.querySelectorAll('#ch1 .board dd:has(> small)');
    return Array.from(dds).map(dd => {
      const small = dd.querySelector('small');
      if (!small) return null;

      // Get the bottom of the first text node
      let textNode = null;
      for (const n of dd.childNodes) {
        if (n.nodeType === 3) {
          textNode = n;
          break;
        }
      }

      let firstTextBottom = null;
      if (textNode) {
        const range = document.createRange();
        range.setStart(textNode, 0);
        range.setEnd(textNode, textNode.length);
        const rect = range.getBoundingClientRect();
        firstTextBottom = rect.bottom;
      }

      const smallRect = small.getBoundingClientRect();
      const smallText = small.textContent;

      return {
        smallText,
        smallTop: smallRect.top,
        smallHeight: smallRect.height,
        firstTextBottom,
        scrollWidth: dd.scrollWidth,
        clientWidth: dd.clientWidth
      };
    }).filter(r => r !== null);
  });

  check(`${width}: found dd with small in #ch1 .board`, results.length > 0, `found ${results.length}`);

  for (let i = 0; i < results.length; i++) {
    const r = results[i];

    // Check small's text matches pattern
    const matches = /^[+−±]\d+\.\d%$/.test(r.smallText);
    check(`${width} dd[${i}]: small text matches pattern`, matches, r.smallText);

    // Check small is on its own line (small's top >= first text node's bottom)
    if (r.firstTextBottom !== null) {
      const onOwnLine = r.smallTop >= r.firstTextBottom - 2;
      check(`${width} dd[${i}]: small on own line`, onOwnLine, `small.top=${r.smallTop.toFixed(1)}, text.bottom=${r.firstTextBottom.toFixed(1)}`);
    }

    // Check no clipping
    const noClipping = r.scrollWidth <= r.clientWidth + 1;
    check(`${width} dd[${i}]: no overflow`, noClipping, `scrollWidth=${r.scrollWidth}, clientWidth=${r.clientWidth}`);
  }

  // Click each season button and re-check
  const seasonButtons = await page.locator('#ch1 .seasonbar button').all();
  for (let s = 0; s < seasonButtons.length; s++) {
    await seasonButtons[s].click();
    await page.waitForTimeout(500); // Wait for board update

    // Re-check small positions
    const newResults = await page.evaluate(() => {
      const dds = document.querySelectorAll('#ch1 .board dd:has(> small)');
      return Array.from(dds).map(dd => {
        const small = dd.querySelector('small');
        if (!small) return null;

        let textNode = null;
        for (const n of dd.childNodes) {
          if (n.nodeType === 3) {
            textNode = n;
            break;
          }
        }

        let firstTextBottom = null;
        if (textNode) {
          const range = document.createRange();
          range.setStart(textNode, 0);
          range.setEnd(textNode, textNode.length);
          const rect = range.getBoundingClientRect();
          firstTextBottom = rect.bottom;
        }

        const smallRect = small.getBoundingClientRect();
        return {
          smallTop: smallRect.top,
          firstTextBottom
        };
      }).filter(r => r !== null);
    });

    for (let i = 0; i < newResults.length; i++) {
      const r = newResults[i];
      if (r.firstTextBottom !== null) {
        const onOwnLine = r.smallTop >= r.firstTextBottom - 2;
        check(`${width} season[${s}] dd[${i}]: small on own line`, onOwnLine, `small.top=${r.smallTop.toFixed(1)}, text.bottom=${r.firstTextBottom.toFixed(1)}`);
      }
    }
  }
}

async function testTonightBoard(page) {
  // Check [data-testid=tape] and [data-testid=season-board] have no small elements
  const tapeSmalls = await page.locator('[data-testid=tape] small').count();
  check('1440 Tonight: tape has no small', tapeSmalls === 0);

  const seasonSmalls = await page.locator('[data-testid=season-board] small').count();
  check('1440 Tonight: season-board has no small', seasonSmalls === 0);
}

// Main test
async function runTests() {
  for (const w of WIDTHS) {
    const p = await open('/model?sample=1', w);

    // Take a before screenshot
    await shot(p, `C9-before-${w}`, '#ch1 .board');

    // Test model board
    await testModelBoard(p, w);

    check(`${w}: page errors`, p.errors.length === 0, p.errors.join(' | '));

    await done(p);
  }

  // Test Tonight board at 1440
  const pTonight = await open('/?sample=1&scene=live', 1440);
  await scrollTo(pTonight, '[data-testid=season-board]', 1200);
  await testTonightBoard(pTonight);
  check('1440 Tonight: page errors', pTonight.errors.length === 0, pTonight.errors.join(' | '));
  await done(pTonight);

  await close();
  report();
}

runTests().catch(e => {
  console.error('Test error:', e);
  process.exitCode = 1;
});
