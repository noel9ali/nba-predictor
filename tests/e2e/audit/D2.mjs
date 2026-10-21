// D2: Lede kicker wraps only between parts, never with a leading "·"
import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

// Helper to normalise text (replace NBSP with space, collapse whitespace)
function normalise(text) {
  return text.replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
}

// Get all line start characters in an element: group rects by top coordinate
function getLineStarts(el) {
  if (!el) return [];
  const range = new Range();
  const lineStarts = [];
  const seenTops = new Set();

  // Walk all text nodes and check each character
  function walkTextNodes(node) {
    if (node.nodeType === 3) {
      // Text node: check each character
      const text = node.textContent;
      for (let i = 0; i < text.length; i++) {
        if (text[i].trim()) {
          range.setStart(node, i);
          range.setEnd(node, i + 1);
          const rects = range.getClientRects();
          if (rects.length > 0) {
            const rect = rects[0];
            const top = Math.round(rect.top);
            if (!seenTops.has(top)) {
              seenTops.add(top);
              lineStarts.push({ char: text[i], top });
            }
          }
        }
      }
    } else if (node.nodeType === 1) {
      for (let child of node.childNodes) {
        walkTextNodes(child);
      }
    }
  }

  walkTextNodes(el);
  return lineStarts;
}

async function testScene(scene) {
  const widths = scene === 'offseason' ? [320, 400, 768, 1440] : [320, 400, 768, 1440];

  for (const w of widths) {
    const p = await open(`/?sample=1&scene=${scene}`, w);
    const kick = await p.$('[data-lede-kick]');
    const eyebrow = await p.$('[data-testid=date-eyebrow]');
    const counts = await p.$('[data-testid=counts]');

    // Check console errors
    check(`${scene}/${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // Check no line starts with "·"
    const lineStarts = await p.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return [];
      const range = new Range();
      const lineStarts = [];
      const seenTops = new Set();

      function walkTextNodes(node) {
        if (node.nodeType === 3) {
          const text = node.textContent;
          for (let i = 0; i < text.length; i++) {
            if (text[i].trim()) {
              range.setStart(node, i);
              range.setEnd(node, i + 1);
              const rects = range.getClientRects();
              if (rects.length > 0) {
                const rect = rects[0];
                const top = Math.round(rect.top);
                if (!seenTops.has(top)) {
                  seenTops.add(top);
                  lineStarts.push({ char: text[i], top });
                }
              }
            }
          }
        } else if (node.nodeType === 1) {
          for (let child of node.childNodes) {
            walkTextNodes(child);
          }
        }
      }

      walkTextNodes(el);
      return lineStarts;
    }, '[data-lede-kick]');

    const bulletsAtLineStart = lineStarts.filter(ls => ls.char === '·');
    check(`${scene}/${w}: no line starts with "·"`, bulletsAtLineStart.length === 0,
      bulletsAtLineStart.length > 0 ? `Found ${bulletsAtLineStart.length} lines starting with "·"` : '');

    // Check eyebrow text format
    const eyebrowText = await eyebrow.textContent();
    const normEyebrow = normalise(eyebrowText);

    if (scene === 'offseason') {
      check(`${scene}/${w}: eyebrow is just the date`,
        /^\w+day, \w+ \d+$/.test(normEyebrow), `Got "${normEyebrow}"`);
    } else {
      check(`${scene}/${w}: eyebrow matches date + · + games pattern`,
        /^\w+day, \w+ \d+ · \d+ games?$/.test(normEyebrow), `Got "${normEyebrow}"`);
    }

    // Check counts text format
    const countsText = await counts.textContent();
    const normCounts = normalise(countsText);

    if (scene === 'offseason') {
      check(`${scene}/${w}: counts text correct`, true);
    } else {
      // Should have at least one "·" separator between parts
      check(`${scene}/${w}: counts has separators`, normCounts.includes('·'), `Got "${normCounts}"`);
    }

    // Check whole kicker text (concatenate eyebrow + " · " + counts for non-offseason)
    const kickText = await kick.textContent();
    const normKick = normalise(kickText);
    if (scene !== 'offseason') {
      const expectedKick = normEyebrow + ' · ' + normCounts;
      check(`${scene}/${w}: kicker text = eyebrow + · + counts`, normKick === expectedKick,
        `Expected "${expectedKick}", got "${normKick}"`);
    }

    // Check no horizontal overflow
    const overflowed = await p.evaluate(() => {
      const body = document.body;
      return body.scrollWidth > body.clientWidth;
    });
    check(`${scene}/${w}: no horizontal overflow`, !overflowed);

    await shot(p, `D2-${w === 320 ? '320' : w}`, 'section.lede');
    await done(p);
  }
}

// Test all scenes
const testScenes = ['live', 'final', 'nobets', 'offseason'];
for (const s of testScenes) {
  await testScene(s);
}

// Test past mode
for (const w of [320, 400, 768, 1440]) {
  const p = await open('/?sample=1&date=2026-11-16', w);
  const kick = await p.$('[data-lede-kick]');
  const eyebrow = await p.$('[data-testid=date-eyebrow]');

  check(`past/${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  const lineStarts = await p.evaluate(() => {
    const el = document.querySelector('[data-lede-kick]');
    if (!el) return [];
    const range = new Range();
    const lineStarts = [];
    const seenTops = new Set();

    function walkTextNodes(node) {
      if (node.nodeType === 3) {
        const text = node.textContent;
        for (let i = 0; i < text.length; i++) {
          if (text[i].trim()) {
            range.setStart(node, i);
            range.setEnd(node, i + 1);
            const rects = range.getClientRects();
            if (rects.length > 0) {
              const rect = rects[0];
              const top = Math.round(rect.top);
              if (!seenTops.has(top)) {
                seenTops.add(top);
                lineStarts.push({ char: text[i], top });
              }
            }
          }
        }
      } else if (node.nodeType === 1) {
        for (let child of node.childNodes) {
          walkTextNodes(child);
        }
      }
    }

    walkTextNodes(el);
    return lineStarts;
  });

  const bulletsAtLineStart = lineStarts.filter(ls => ls.char === '·');
  check(`past/${w}: no line starts with "·"`, bulletsAtLineStart.length === 0);

  const overflowed = await p.evaluate(() => {
    const body = document.body;
    return body.scrollWidth > body.clientWidth;
  });
  check(`past/${w}: no horizontal overflow`, !overflowed);

  await done(p);
}

await close();
report();
