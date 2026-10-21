import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

async function testA6() {
  // Test nobets scene
  for (const w of WIDTHS) {
    const nobets = await open('/?sample=1&scene=nobets', w);
    const noCells = await nobets.evaluate(() => {
      const cells = document.querySelectorAll('[data-testid=tape] > div');
      return cells.length;
    });
    check(`${w} nobets: exactly 1 cell`, noCells === 1, `Got ${noCells}`);

    const noDt = await nobets.evaluate(() => {
      const dt = document.querySelector('[data-testid=tape] dt');
      return dt ? dt.textContent : null;
    });
    check(`${w} nobets: dt is "Tonight"`, noDt === 'Tonight', `Got "${noDt}"`);

    const noDd = await nobets.evaluate(() => {
      const dd = document.querySelector('[data-testid=tape] dd');
      return dd ? dd.textContent : null;
    });
    check(`${w} nobets: dd is "No bets tonight"`, noDd === 'No bets tonight', `Got "${noDd}"`);

    check(`${w} nobets: no console errors`, nobets.errors.length === 0, nobets.errors.join(' | '));
    await shot(nobets, `A6-nobets-${w}`, '[data-testid=tape]');
    await done(nobets);
  }

  // Test final scene
  for (const w of WIDTHS) {
    const final = await open('/?sample=1&scene=final', w);
    const finalCells = await final.evaluate(() => {
      const cells = document.querySelectorAll('[data-testid=tape] > div');
      return cells.length;
    });
    check(`${w} final: exactly 5 cells`, finalCells === 5, `Got ${finalCells}`);

    const hasLivePicksAhead = await final.evaluate(() => {
      const dts = document.querySelectorAll('[data-testid=tape] dt');
      return Array.from(dts).some(dt => dt.textContent === 'Live picks ahead');
    });
    check(`${w} final: no "Live picks ahead" label`, !hasLivePicksAhead, 'Found "Live picks ahead"');

    const hasZeroOfZero = await final.evaluate(() => {
      const dds = document.querySelectorAll('[data-testid=tape] dd');
      return Array.from(dds).some(dd => /\b0 of 0\b/.test(dd.textContent));
    });
    check(`${w} final: no "0 of 0"`, !hasZeroOfZero, 'Found "0 of 0"');

    // At 400px: check borders and last cell width
    if (w === 400) {
      const borders = await final.evaluate(() => {
        const cells = document.querySelectorAll('[data-testid=tape] > div');
        return Array.from(cells).map((cell, i) => ({
          index: i,
          borderBottom: getComputedStyle(cell).borderBottomWidth
        }));
      });
      for (const b of borders.slice(0, -1)) {
        const width = parseFloat(b.borderBottom);
        check(`${w} final: cell ${b.index} has bottom border`, width >= 2, `Got ${b.borderBottom}`);
      }
      const lastBorder = borders[borders.length - 1];
      check(`${w} final: last cell has no bottom border`, parseFloat(lastBorder.borderBottom) === 0, `Got ${lastBorder.borderBottom}`);

      const lastCellWidth = await final.evaluate(() => {
        const cells = document.querySelectorAll('[data-testid=tape] > div');
        const lastCell = cells[cells.length - 1];
        const board = document.querySelector('[data-testid=tape]');
        const lastRect = lastCell.getBoundingClientRect();
        const boardRect = board.getBoundingClientRect();
        const boardInnerWidth = boardRect.width - (parseFloat(getComputedStyle(board).paddingLeft) || 0) - (parseFloat(getComputedStyle(board).paddingRight) || 0);
        return { lastWidth: lastRect.width, boardInner: boardInnerWidth };
      });
      const diff = Math.abs(lastCellWidth.lastWidth - lastCellWidth.boardInner);
      check(`${w} final: last cell spans board width`, diff <= 8, `Last: ${lastCellWidth.lastWidth}, Board inner: ${lastCellWidth.boardInner}, diff: ${diff}`);
    }

    check(`${w} final: no console errors`, final.errors.length === 0, final.errors.join(' | '));
    await shot(final, `A6-final-${w}`, '[data-testid=tape]');
    await done(final);
  }

  // Test live scene
  for (const w of WIDTHS) {
    const live = await open('/?sample=1&scene=live', w);
    const liveCells = await live.evaluate(() => {
      const cells = document.querySelectorAll('[data-testid=tape] > div');
      return cells.length;
    });
    check(`${w} live: exactly 6 cells`, liveCells === 6, `Got ${liveCells}`);

    const livePicksValue = await live.evaluate(() => {
      const dts = document.querySelectorAll('[data-testid=tape] dt');
      const livePicksDt = Array.from(dts).find(dt => dt.textContent === 'Live picks ahead');
      if (!livePicksDt) return null;
      const dd = livePicksDt.nextElementSibling;
      return dd ? dd.textContent : null;
    });
    check(`${w} live: "Live picks ahead" value matches /^\\d+ of [1-9]\\d*$/`,
      /^\d+ of [1-9]\d*$/.test(livePicksValue || ''), `Got "${livePicksValue}"`);

    check(`${w} live: no console errors`, live.errors.length === 0, live.errors.join(' | '));
    await done(live);
  }

  // Test nextup scene (5 cells: no live bets yet)
  for (const w of WIDTHS) {
    const nextup = await open('/?sample=1&scene=nextup', w);
    const nextupCells = await nextup.evaluate(() => {
      const cells = document.querySelectorAll('[data-testid=tape] > div');
      return cells.length;
    });
    check(`${w} nextup: exactly 5 cells`, nextupCells === 5, `Got ${nextupCells}`);

    const hasZeroOfZero = await nextup.evaluate(() => {
      const dds = document.querySelectorAll('[data-testid=tape] dd');
      return Array.from(dds).some(dd => /\b0 of 0\b/.test(dd.textContent));
    });
    check(`${w} nextup: no "0 of 0"`, !hasZeroOfZero, 'Found "0 of 0"');

    check(`${w} nextup: no console errors`, nextup.errors.length === 0, nextup.errors.join(' | '));
    await done(nextup);
  }

  // Test replay scene (only at one width)
  const replay = await open('/?sample=1&scene=replay', 400);
  const replayInitial = await replay.evaluate(() => {
    const dd = document.querySelector('[data-testid=tape] [data-testid=settled]');
    return dd ? dd.textContent : null;
  });
  // Step through several replay updates to find a value change
  let replayAfter = replayInitial;
  for (let i = 0; i < 3; i++) {
    await replay.evaluate(() => window.__sampleFeed.step());
    await replay.waitForTimeout(300);
    replayAfter = await replay.evaluate(() => {
      const dd = document.querySelector('[data-testid=tape] [data-testid=settled]');
      return dd ? dd.textContent : null;
    });
    if (replayAfter !== replayInitial) break;
  }
  check('replay: settled value changed after steps', replayInitial !== replayAfter,
    `Initial: "${replayInitial}", After: "${replayAfter}"`);
  check('replay: no console errors', replay.errors.length === 0, replay.errors.join(' | '));
  await done(replay);

  // Test past mode
  for (const w of WIDTHS) {
    const past = await open('/?sample=1&date=2026-11-16', w);
    const pastCells = await past.evaluate(() => {
      const cells = document.querySelectorAll('[data-testid=tape] > div');
      return cells.length;
    });
    check(`${w} past: exactly 5 cells`, pastCells === 5, `Got ${pastCells}`);
    check(`${w} past: no console errors`, past.errors.length === 0, past.errors.join(' | '));
    await done(past);
  }
}

await testA6();
await close();
report();
