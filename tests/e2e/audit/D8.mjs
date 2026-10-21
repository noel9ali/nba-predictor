// D8: "Last 33 bets" card layout fix — no stretch, even rows (11 × 3)
// Test that the card doesn't stretch and squares arrange in 11-column grid.
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

async function testWLCard(scene, widths) {
  console.log(`\n=== SCENE: ${scene} ===`);

  for (const w of widths) {
    const p = await open(`/?sample=1&scene=${scene}`, w);

    // Scroll to the wl card
    await scrollTo(p, '[data-wl-card]', 1500);

    // Get the card and wl div
    const card = await p.$('[data-wl-card]');
    const wlDiv = await p.$('[data-testid="wl"]');
    const squares = await p.$$('[data-testid="wl"] i');

    const squareCount = squares.length;

    // Get card dimensions
    const cardBox = await card.boundingBox();
    const cardHeight = cardBox.height;
    const cardWidth = cardBox.width;
    const cardScrollHeight = await card.evaluate(el => el.scrollHeight);
    const cardClientHeight = await card.evaluate(el => el.clientHeight);

    // Get all square positions
    const squarePositions = await p.evaluate(() => {
      const squares = [...document.querySelectorAll('[data-testid="wl"] i')];
      return squares.map(el => {
        const rect = el.getBoundingClientRect();
        return { top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom };
      });
    });

    // Get all distinct row tops
    const rowTops = new Set(squarePositions.map(pos => Math.round(pos.top)));
    const distinctRows = [...rowTops].sort((a, b) => a - b);

    // Get squares per row
    const squaresPerRow = {};
    squarePositions.forEach(pos => {
      const rowTop = Math.round(pos.top);
      if (!squaresPerRow[rowTop]) squaresPerRow[rowTop] = 0;
      squaresPerRow[rowTop]++;
    });

    // Check: all squares visible inside card (no horizontal overflow)
    const allInside = await p.evaluate(() => {
      const card = document.querySelector('[data-wl-card]');
      const cardRect = card.getBoundingClientRect();
      const squares = [...document.querySelectorAll('[data-testid="wl"] i')];
      return squares.every(sq => {
        const rect = sq.getBoundingClientRect();
        return rect.left >= cardRect.left - 1 && rect.right <= cardRect.right + 1;
      });
    });

    // Check no horizontal overflow
    const hasHorizontalScroll = await p.evaluate(() => {
      const card = document.querySelector('[data-wl-card]');
      return card.scrollWidth > card.clientWidth;
    });

    // Take screenshot of the card
    await shot(p, `D8-${w}`, '[data-wl-card]');

    // Run checks
    check(
      `${w}/${scene}: exactly 33 squares`,
      squareCount === 33,
      `found ${squareCount}`
    );

    check(
      `${w}/${scene}: exactly 3 rows`,
      distinctRows.length === 3,
      `found ${distinctRows.length} rows`
    );

    // Check 11 squares per row
    let allRows11 = true;
    let rowDetails = '';
    for (const rowTop of distinctRows) {
      const count = squaresPerRow[rowTop];
      if (count !== 11) allRows11 = false;
      rowDetails += `${count} `;
    }
    check(
      `${w}/${scene}: each row has 11 squares`,
      allRows11,
      `counts: ${rowDetails}`
    );

    check(
      `${w}/${scene}: no horizontal overflow`,
      !hasHorizontalScroll,
      'horizontal scroll detected'
    );

    check(
      `${w}/${scene}: all squares inside card bounds`,
      allInside,
      'squares overflow card'
    );

    check(
      `${w}/${scene}: card height not stretched`,
      cardScrollHeight === cardClientHeight,
      `scrollHeight ${cardScrollHeight} vs clientHeight ${cardClientHeight}`
    );

    // At 1440, card should be < 260px high (3 rows of 26px + some padding)
    if (w === 1440) {
      check(
        `${w}/${scene}: card height reasonable at 1440`,
        cardHeight < 260,
        `card height: ${cardHeight}px`
      );
    }

    check(
      `${w}/${scene}: no console errors`,
      p.errors.length === 0,
      p.errors.join(' | ')
    );

    await done(p);
  }
}

// Test at 320px separately since WIDTHS doesn't include it
async function test320px(scene) {
  console.log(`\n=== 320px / ${scene} ===`);
  const p = await open(`/?sample=1&scene=${scene}`, 320);
  await scrollTo(p, '[data-wl-card]', 1500);

  const card = await p.$('[data-wl-card]');
  const squares = await p.$$('[data-testid="wl"] i');
  const squareCount = squares.length;

  const cardBox = await card.boundingBox();
  const cardHeight = cardBox.height;

  const hasHorizontalScroll = await p.evaluate(() => {
    const card = document.querySelector('[data-wl-card]');
    return card.scrollWidth > card.clientWidth;
  });

  const allInside = await p.evaluate(() => {
    const card = document.querySelector('[data-wl-card]');
    const cardRect = card.getBoundingClientRect();
    const squares = [...document.querySelectorAll('[data-testid="wl"] i')];
    return squares.every(sq => {
      const rect = sq.getBoundingClientRect();
      return rect.left >= cardRect.left - 1 && rect.right <= cardRect.right + 1;
    });
  });

  const cardScrollHeight = await card.evaluate(el => el.scrollHeight);
  const cardClientHeight = await card.evaluate(el => el.clientHeight);

  await shot(p, 'D8-320', '[data-wl-card]');

  check(`320/${scene}: exactly 33 squares`, squareCount === 33, `found ${squareCount}`);
  check(`320/${scene}: no horizontal overflow`, !hasHorizontalScroll, 'horizontal scroll detected');
  check(`320/${scene}: all squares inside card bounds`, allInside, 'squares overflow card');
  check(`320/${scene}: card height not stretched`, cardScrollHeight === cardClientHeight, '');
  check(`320/${scene}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  await done(p);
}

async function run() {
  try {
    // Test scene=live and scene=final with standard widths (400, 768, 1440)
    await testWLCard('live', WIDTHS);
    await testWLCard('final', WIDTHS);
    // Also test at 320px
    await test320px('live');
  } finally {
    await close();
    report();
  }
}

run().catch(e => {
  console.error('Test failed:', e);
  process.exit(1);
});
