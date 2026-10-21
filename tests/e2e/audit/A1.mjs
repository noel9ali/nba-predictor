import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

for (const w of WIDTHS) {
  const p = await open('/model?sample=1', w, {
    route: [
      ['**/sample/game-*.json', r => r.fulfill({ status: 404, contentType: 'application/json', body: '{}' })]
    ]
  });

  // Check chapter visibility and numbering
  const ch3 = await p.$('#ch3');
  const ch3Hidden = await p.evaluate(() => document.querySelector('#ch3').hidden);
  check(`${w}: ch3 not hidden when game detail fails`, !ch3Hidden);

  const ch3K = await p.evaluate(() => document.querySelector('#ch3 .ch .k')?.textContent);
  check(`${w}: ch3 has correct number`, ch3K === 'Chapter 3', `got "${ch3K}"`);

  // Check fallback card in ch3
  const walkFallback = await p.evaluate(() => document.querySelector('#ch3 .walk-fallback') !== null);
  check(`${w}: ch3 has walk-fallback card`, walkFallback);

  const walkFallbackText = await p.evaluate(() => document.querySelector('#ch3 .walk-fallback p')?.textContent);
  check(`${w}: ch3 fallback text correct`,
    walkFallbackText?.includes("Walkthrough unavailable: the featured game couldn't load."),
    walkFallbackText || 'not found');

  const stepCount = await p.evaluate(() => document.querySelectorAll('#ch3 .step').length);
  check(`${w}: ch3 has no steps in fallback`, stepCount === 0, `got ${stepCount}`);

  // Check ch2 row card fallback
  const rowcardFallback = await p.evaluate(() => document.querySelector('#ch2 .rowcard-fallback') !== null);
  check(`${w}: ch2 has rowcard-fallback card`, rowcardFallback);

  // Check chapter numbering is fixed
  const ch4K = await p.evaluate(() => document.querySelector('#ch4 .ch .k')?.textContent);
  check(`${w}: ch4 has correct number`, ch4K === 'Chapter 4', `got "${ch4K}"`);

  const ch5K = await p.evaluate(() => document.querySelector('#ch5 .ch .k')?.textContent);
  check(`${w}: ch5 has correct number`, ch5K === 'Chapter 5', `got "${ch5K}"`);

  const ch6K = await p.evaluate(() => document.querySelector('#ch6 .ch .k')?.textContent);
  check(`${w}: ch6 has correct number`, ch6K === 'Chapter 6', `got "${ch6K}"`);

  // Check no console errors (ignoring 404s)
  const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
  check(`${w}: no console errors`, errors.length === 0, errors.join(' | '));

  // Take screenshot
  await scrollTo(p, '#ch3', 1500);
  await shot(p, `A1-${w}`, '#ch3');

  await done(p);
}

// Test with featured pick failing instead
for (const w of WIDTHS) {
  const p = await open('/model?sample=1', w, {
    route: [
      ['**/sample/featured-pick.json', r => r.fulfill({ status: 404, contentType: 'application/json', body: '{}' })]
    ]
  });

  const ch3Hidden = await p.evaluate(() => document.querySelector('#ch3').hidden);
  check(`${w}: ch3 not hidden when featured pick fails`, !ch3Hidden);

  const walkFallback = await p.evaluate(() => document.querySelector('#ch3 .walk-fallback') !== null);
  check(`${w}: ch3 has fallback when featured-pick fails`, walkFallback);

  // Check no console errors
  const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
  check(`${w}: no console errors (featured-pick fail)`, errors.length === 0, errors.join(' | '));

  await done(p);
}

// Test normal case (no failures)
for (const w of WIDTHS) {
  const p = await open('/model?sample=1', w);

  // Check ch3 still has steps
  const stepCount = await p.evaluate(() => document.querySelectorAll('#ch3 .step').length);
  check(`${w}: ch3 has 7 steps normally`, stepCount === 7, `got ${stepCount}`);

  // Check no fallback cards
  const walkFallback = await p.evaluate(() => document.querySelector('#ch3 .walk-fallback') !== null);
  check(`${w}: no walk-fallback in normal case`, !walkFallback);

  const rowcardFallback = await p.evaluate(() => document.querySelector('#ch2 .rowcard-fallback') !== null);
  check(`${w}: no rowcard-fallback in normal case`, !rowcardFallback);

  // Check chapter numbering
  const numbers = await p.evaluate(() =>
    [1,2,3,4,5,6].map(n => document.querySelector(`#ch${n} .ch .k`)?.textContent)
  );
  for (let i = 0; i < 6; i++) {
    check(`${w}: normal case ch${i+1} number`, numbers[i] === `Chapter ${i+1}`, `got "${numbers[i]}"`);
  }

  // Check no console errors
  const errors = p.errors.filter(e => !e.includes('404') && !e.includes('Failed to load resource'));
  check(`${w}: no errors in normal case`, errors.length === 0, errors.join(' | '));

  await done(p);
}

await close();
report();
