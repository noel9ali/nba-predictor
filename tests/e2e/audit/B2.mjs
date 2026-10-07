import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

const PAD = 0.5; // tolerance in px

async function testTooltipContainment(p, w) {
  // Get the chart host and its card container
  const host = await p.locator('[data-testid=bankroll]').elementHandle();
  const card = await host.evaluate(h => h.closest('.card'));

  if (!host || !card) {
    check(`${w}: chart found`, false, 'host or card not found');
    return;
  }

  // Helper to check if tooltip is inside card
  const checkTipInside = async (nightNum, source) => {
    const tip = await host.evaluate(h => {
      const t = h.querySelector('.tip');
      if (!t || t.hidden) return null;
      const r = t.getBoundingClientRect();
      return {
        left: r.left, right: r.right, top: r.top, bottom: r.bottom,
        text: t.textContent
      };
    });

    const cardRect = await host.evaluate(h => {
      const c = h.closest('.card');
      const r = c.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    });

    if (!tip) {
      check(`${w}: night ${nightNum} (${source}): tip visible`, false, 'tip hidden or not found');
      return null;
    }

    const insideLeft = tip.left >= cardRect.left - PAD;
    const insideRight = tip.right <= cardRect.right + PAD;
    const insideTop = tip.top >= cardRect.top - PAD;
    const insideBottom = tip.bottom <= cardRect.bottom + PAD;
    const inside = insideLeft && insideRight && insideTop && insideBottom;

    check(
      `${w}: night ${nightNum} (${source}): tip inside card`,
      inside,
      inside ? 'OK' : `tip: L=${tip.left.toFixed(1)},R=${tip.right.toFixed(1)},T=${tip.top.toFixed(1)},B=${tip.bottom.toFixed(1)} vs card: L=${cardRect.left.toFixed(1)},R=${cardRect.right.toFixed(1)},T=${cardRect.top.toFixed(1)},B=${cardRect.bottom.toFixed(1)}`
    );

    return tip;
  };

  // Scroll chart into view
  await scrollTo(p, '[data-testid=bankroll]');

  // Focus the chart
  await host.evaluate(h => h.focus());

  // Press ArrowLeft 40 times to reach night 1 (safe for ~27 nights)
  for (let i = 0; i < 40; i++) {
    await p.keyboard.press('ArrowLeft');
    await p.waitForTimeout(50);
  }

  // Check we're at the first night
  let tip = await checkTipInside(1, 'keyboard');
  if (tip && tip.text) {
    check(`${w}: first night text`, tip.text.includes('Oct'), tip.text);
  }

  // Take a screenshot of the first night
  const hostRect = await host.evaluate(h => {
    const r = h.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  });

  // Now navigate through all nights with ArrowRight
  let lastText = tip?.text || '';
  let nightNum = 1;

  while (true) {
    await p.keyboard.press('ArrowRight');
    await p.waitForTimeout(50);

    const currentTip = await checkTipInside(nightNum + 1, 'keyboard');
    if (!currentTip || currentTip.text === lastText) {
      // Reached the end
      break;
    }

    lastText = currentTip.text;
    nightNum++;

    // Check every few nights to avoid too many checks
    if (nightNum % 5 === 0) {
      check(`${w}: every 5 nights: inside`, true, `night ${nightNum}`);
    }
  }

  // Go back to the first night for screenshot
  for (let i = 0; i < nightNum; i++) {
    await p.keyboard.press('ArrowLeft');
    await p.waitForTimeout(20);
  }
  await p.waitForTimeout(100);
  await shot(p, `B2-first-${w}`, '[data-testid=bankroll]');

  // Now go to the last night and check there too
  for (let i = 0; i < nightNum; i++) {
    await p.keyboard.press('ArrowRight');
    await p.waitForTimeout(20);
  }
  await p.waitForTimeout(100);
  await checkTipInside(nightNum, 'keyboard end');
  await shot(p, `B2-last-${w}`, '[data-testid=bankroll]');

  // Test mouse hover on left edge
  const hostBounds = await host.evaluate(h => {
    const r = h.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  });

  // Hover at left edge
  await p.mouse.move(hostBounds.left + 2, (hostBounds.top + hostBounds.bottom) / 2);
  await p.waitForTimeout(100);
  const tipLeft = await checkTipInside('L', 'hover left');

  // Hover at right edge
  await p.mouse.move(hostBounds.right - 2, (hostBounds.top + hostBounds.bottom) / 2);
  await p.waitForTimeout(100);
  const tipRight = await checkTipInside('R', 'hover right');

  // Check for console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
}

// Main test loop
for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=live', w);
  await testTooltipContainment(p, w);
  await done(p);
}

await close();
report();
