import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

// D6: Pass stub label "PICK · NO BET" on two lines for desktop (>560px), one line for mobile (≤560px)
// Test with nobets scene (all passes)
for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=nobets', w);

  // Find pass tickets
  const results = await p.evaluate(() => {
    const out = { passCount: 0, passLinesCounts: [] };

    document.querySelectorAll('[data-testid="ticket"]').forEach((ticket, idx) => {
      const whoEl = ticket.querySelector('.stub .who');
      if (!whoEl) return;

      const fullText = whoEl.textContent;
      const isBet = fullText.includes('Bet on');
      const isPass = fullText.includes('Pick') && !isBet;

      if (isPass) {
        out.passCount++;
        // Count line boxes for pass tickets
        const childNodes = Array.from(whoEl.childNodes).filter(n =>
          n.nodeType === 3 || (n.nodeType === 1 && !n.classList.contains('stub-pick'))
        );

        const rects = [];
        childNodes.forEach(node => {
          if (node.nodeType === 3) {
            const range = document.createRange();
            range.selectNodeContents(node);
            const rs = Array.from(range.getClientRects());
            rects.push(...rs);
          } else if (node.nodeType === 1) {
            const rs = Array.from(node.getClientRects());
            rects.push(...rs);
          }
        });

        const lines = new Set();
        rects.forEach(r => lines.add(Math.round(r.top)));
        out.passLinesCounts.push({ idx, lines: lines.size });
      }
    });

    return out;
  });

  check(`${w} nobets: found pass tickets`, results.passCount > 0, `found ${results.passCount}`);

  const isDesktop = w > 560;
  const expectedPassLines = isDesktop ? 2 : 1;

  results.passLinesCounts.forEach(r => {
    check(
      `${w} nobets: pass ticket ${r.idx} has ${expectedPassLines} line(s)`,
      r.lines === expectedPassLines,
      `got ${r.lines} lines`
    );
  });

  // Check for console errors
  const errors = p.errors.filter(e => !e.includes('404'));
  check(`${w} nobets: no console errors`, errors.length === 0, errors.slice(0, 3).join(' | '));

  // Take screenshot
  try {
    await shot(p, `D6-before-${w}`, '[data-testid="ticket"]:first-of-type .stub');
  } catch (e) {
    // Ignore screenshot errors
  }

  await done(p);
}

// Test with live scene (has both passes and bets)
for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=live', w);

  const results = await p.evaluate(() => {
    const out = { passCount: 0, betCount: 0, passLinesCounts: [], betLinesCounts: [] };

    document.querySelectorAll('[data-testid="ticket"]').forEach((ticket, idx) => {
      const whoEl = ticket.querySelector('.stub .who');
      if (!whoEl) return;

      const fullText = whoEl.textContent;
      const isBet = fullText.includes('Bet on');
      const isPass = fullText.includes('Pick') && !isBet;

      if (isPass) {
        out.passCount++;
        const childNodes = Array.from(whoEl.childNodes).filter(n =>
          n.nodeType === 3 || (n.nodeType === 1 && !n.classList.contains('stub-pick'))
        );

        const rects = [];
        childNodes.forEach(node => {
          if (node.nodeType === 3) {
            const range = document.createRange();
            range.selectNodeContents(node);
            const rs = Array.from(range.getClientRects());
            rects.push(...rs);
          } else if (node.nodeType === 1) {
            const rs = Array.from(node.getClientRects());
            rects.push(...rs);
          }
        });

        const lines = new Set();
        rects.forEach(r => lines.add(Math.round(r.top)));
        out.passLinesCounts.push({ idx, lines: lines.size });
      } else if (isBet) {
        out.betCount++;
        // For bet tickets, count rects from all text and non-stub-pick elements
        const allRects = [];
        Array.from(whoEl.childNodes).forEach(node => {
          if (node.nodeType === 3) {
            const range = document.createRange();
            range.selectNodeContents(node);
            const rs = Array.from(range.getClientRects());
            allRects.push(...rs);
          } else if (node.nodeType === 1 && !node.classList.contains('stub-pick')) {
            const rs = Array.from(node.getClientRects());
            allRects.push(...rs);
          }
        });

        const lines = new Set();
        allRects.forEach(r => lines.add(Math.round(r.top)));
        out.betLinesCounts.push({ idx, lines: lines.size });
      }
    });

    return out;
  });

  if (results.passCount > 0) {
    const isDesktop = w > 560;
    const expectedPassLines = isDesktop ? 2 : 1;

    results.passLinesCounts.forEach(r => {
      check(
        `${w} live: pass ticket ${r.idx} has ${expectedPassLines} line(s)`,
        r.lines === expectedPassLines,
        `got ${r.lines} lines`
      );
    });
  }

  if (results.betCount > 0) {
    results.betLinesCounts.forEach(r => {
      check(
        `${w} live: bet ticket ${r.idx} has 1 line`,
        r.lines === 1,
        `got ${r.lines} lines`
      );
    });
  }

  // Check for console errors
  const errors = p.errors.filter(e => !e.includes('404'));
  check(`${w} live: no console errors`, errors.length === 0, errors.slice(0, 3).join(' | '));

  await done(p);
}

report();
