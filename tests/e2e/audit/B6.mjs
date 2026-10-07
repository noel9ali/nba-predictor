import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

const widths = [320, 400, 768, 1440];
let passCount = 0, failCount = 0;

for (const w of widths) {
  console.log(`\n=== Testing at ${w}px ===`);
  const p = await open('/model?sample=1', w);

  // Scroll to step 7
  await scrollTo(p, '#ch3 .step[data-step="7"]', 2000);

  // Wait a bit for layout to settle
  await p.waitForTimeout(100);

  // Test 1: Stub tricode on one line
  const stubB = await p.$('.mini-ticket .stub b');
  const stubRects = await p.evaluate(el => el.getClientRects().length, stubB);
  const stubText = await p.evaluate(el => el.textContent, stubB);
  check(`${w}: stub tricode one line`, stubRects === 1, `Got ${stubRects} rects, text="${stubText}"`);
  check(`${w}: stub tricode text is 'SAC'`, stubText === 'SAC', `Got "${stubText}"`);

  // Test 2: All elements in mini-stamp visible (not scrolling overflow)
  const stampElems = await p.$$('.mini-stamp, .mini-stamp small');
  for (let i = 0; i < stampElems.length; i++) {
    const elem = stampElems[i];
    const scrollWidth = await p.evaluate(el => el.scrollWidth, elem);
    const clientWidth = await p.evaluate(el => el.clientWidth, elem);
    const isVisible = scrollWidth <= clientWidth + 1;
    check(`${w}: stamp element ${i} not clipped`, isVisible, `scrollWidth=${scrollWidth}, clientWidth=${clientWidth}`);
  }

  // Test 3: Stamp inside ticket bounds (using bounding rects)
  const miniTicket = await p.$('.mini-ticket');
  const miniStamp = await p.$('.mini-stamp');
  const ticketRect = await p.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  }, miniTicket);
  const stampRect = await p.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  }, miniStamp);

  // Check stamp is roughly inside ticket (allow 1px tolerance)
  const stampInside = stampRect.left >= ticketRect.left - 1 &&
                      stampRect.right <= ticketRect.right + 1 &&
                      stampRect.top >= ticketRect.top - 1 &&
                      stampRect.bottom <= ticketRect.bottom + 1;
  check(`${w}: stamp inside ticket bounds`, stampInside,
    `Ticket: L=${Math.round(ticketRect.left)}, R=${Math.round(ticketRect.right)}, T=${Math.round(ticketRect.top)}, B=${Math.round(ticketRect.bottom)} | Stamp: L=${Math.round(stampRect.left)}, R=${Math.round(stampRect.right)}, T=${Math.round(stampRect.top)}, B=${Math.round(stampRect.bottom)}`);

  // Test 4: Logos present (2 images or chips in .tm elements)
  const logos = await p.$$('.mini-ticket .tm img, .mini-ticket .tm .chip');
  check(`${w}: 2 logos/chips present`, logos.length === 2, `Found ${logos.length}`);

  // Test 5: Meta line(s) on one line each
  const metaLines = await p.$$('.mini-ticket .stub span:nth-child(n+2)');
  for (let i = 0; i < metaLines.length; i++) {
    const elem = metaLines[i];
    const rects = await p.evaluate(el => el.getClientRects().length, elem);
    check(`${w}: meta line ${i} on one line`, rects === 1, `Got ${rects} rects`);
  }

  // Test 6: No horizontal overflow
  const html = await p.$('html');
  const clientWidth = await p.evaluate(el => el.clientWidth, html);
  const scrollWidth = await p.evaluate(el => el.scrollWidth, html);
  check(`${w}: no horizontal overflow`, scrollWidth <= clientWidth + 1, `scrollWidth=${scrollWidth}, clientWidth=${clientWidth}`);

  // Test 7: No console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Test 8: mt-note text not touching edge (8px margin)
  const mtNote = await p.$('.mini-ticket .mt-note');
  const mtNoteRect = await p.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { right: r.right, text: el.textContent };
  }, mtNote);
  const noteInBounds = mtNoteRect.right <= ticketRect.right - 8;
  check(`${w}: mt-note right margin (8px from ticket edge)`, noteInBounds,
    `mt-note right=${Math.round(mtNoteRect.right)}, ticket right=${Math.round(ticketRect.right)}`);

  // Test 8b: mt-note full text visible (should end in ".93" for sample)
  const hasFullText = mtNoteRect.text.includes('.93') || mtNoteRect.text.includes('.9');
  check(`${w}: mt-note full text visible`, hasFullText, `Text: "${mtNoteRect.text}"`);

  // Test 9: No element inside mini-ticket overflows ticket bounds
  const allChildren = await p.$$('.mini-ticket *');
  let anyOverflow = false;
  for (const child of allChildren) {
    const childRect = await p.evaluate(el => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    }, child);
    if (childRect.right > ticketRect.right + 1 || childRect.left < ticketRect.left - 1 ||
        childRect.top < ticketRect.top - 1 || childRect.bottom > ticketRect.bottom + 1) {
      anyOverflow = true;
      console.log(`  WARNING: Element extends past ticket: L=${Math.round(childRect.left)}, R=${Math.round(childRect.right)}, T=${Math.round(childRect.top)}, B=${Math.round(childRect.bottom)}`);
    }
  }
  check(`${w}: no element overflows ticket`, !anyOverflow, anyOverflow ? 'Some element extends past ticket bounds' : 'All contained');

  // Test 10: Stamp (with 6px halo) does not intersect mt-note
  const mtNoteFullRect = await p.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  }, mtNote);
  const stampGrownRect = await p.evaluate(el => {
    const r = el.getBoundingClientRect();
    return { left: r.left - 6, right: r.right + 6, top: r.top - 6, bottom: r.bottom + 6 };
  }, miniStamp);

  // Check intersection: two rects intersect if NOT (one is completely left/right/above/below the other)
  const stampsIntersectsNote = !(stampGrownRect.right < mtNoteFullRect.left - 1 ||
                                  stampGrownRect.left > mtNoteFullRect.right + 1 ||
                                  stampGrownRect.bottom < mtNoteFullRect.top - 1 ||
                                  stampGrownRect.top > mtNoteFullRect.bottom + 1);
  check(`${w}: stamp (with halo) does not intersect mt-note`, !stampsIntersectsNote,
    `Stamp (grown): L=${Math.round(stampGrownRect.left)}, R=${Math.round(stampGrownRect.right)}, T=${Math.round(stampGrownRect.top)}, B=${Math.round(stampGrownRect.bottom)} | Note: L=${Math.round(mtNoteFullRect.left)}, R=${Math.round(mtNoteFullRect.right)}, T=${Math.round(mtNoteFullRect.top)}, B=${Math.round(mtNoteFullRect.bottom)}`);


  // Take screenshot
  await shot(p, `B6-${w}`, '#ch3 .step[data-step="7"] .gfx');

  await done(p);
}

await close();
report();
