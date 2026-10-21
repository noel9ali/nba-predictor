// D12: Model hero - no big empty band above the step kicker
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

console.log('Testing D12: No empty band above step kicker\n');

for (const w of WIDTHS) {
  console.log(`\n=== Width ${w} ===`);

  // Open the model page at base state
  const page = await open('/model?sample=1', w);

  // Take base state screenshot before checking
  await shot(page, `D12-before-${w}`, '.claim');

  // Test 1: Base state - check gap between .claim > .k (page kicker) and .pin__k (step kicker)
  const baseGap = await page.evaluate(() => {
    const pageKicker = document.querySelector('.claim > .k');
    const stepKicker = document.querySelector('.pin__k');
    if (!pageKicker || !stepKicker) return null;

    const pageKickerBottom = pageKicker.getBoundingClientRect().bottom;
    const stepKickerTop = stepKicker.getBoundingClientRect().top;

    return Math.max(0, stepKickerTop - pageKickerBottom);
  });

  check(
    `${w}: Base state gap between page kicker and step kicker ≤ 40px`,
    baseGap !== null && baseGap <= 40,
    `Gap: ${baseGap}px`
  );

  // Test 2: Get court top position in base state
  const baseCourtTop = await page.evaluate(() => {
    const pin = document.querySelector('.pin');
    const courtSlot = document.querySelector('[data-court-slot]');
    if (!pin || !courtSlot) return null;

    const pinRect = pin.getBoundingClientRect();
    const courtRect = courtSlot.getBoundingClientRect();

    // Return court top relative to pin top
    return courtRect.top - pinRect.top;
  });

  // Test 3: Scroll to model state (~40% through [data-scrolly])
  await scrollTo(page, '[data-scrolly]', 600);

  // Wait for the model state to be set (the animation is 450ms for swap)
  await page.waitForTimeout(600);

  // Test 4: Verify we're in model state
  const modelState = await page.evaluate(() => {
    const pin = document.querySelector('.pin');
    return pin?.dataset.state || null;
  });

  check(
    `${w}: After scroll, pin state is "model"`,
    modelState === 'model',
    `Got state: ${modelState}`
  );

  // Test 5: Get court top position in model state
  const modelCourtTop = await page.evaluate(() => {
    const pin = document.querySelector('.pin');
    const courtSlot = document.querySelector('[data-court-slot]');
    if (!pin || !courtSlot) return null;

    const pinRect = pin.getBoundingClientRect();
    const courtRect = courtSlot.getBoundingClientRect();

    // Return court top relative to pin top
    return courtRect.top - pinRect.top;
  });

  // Test 6: Court top should be equal in both states (±1px)
  const courtTopDiff = Math.abs(baseCourtTop - modelCourtTop);
  check(
    `${w}: Court top is equal in base and model states (±1px)`,
    courtTopDiff <= 1,
    `Base: ${baseCourtTop}px, Model: ${modelCourtTop}px, Diff: ${courtTopDiff}px`
  );

  // Test 7: No console errors
  check(
    `${w}: No console errors`,
    page.errors.length === 0,
    page.errors.join(' | ')
  );

  // Take model state screenshot
  await shot(page, `D12-model-${w}`, '.claim');

  await done(page);
}

await close();
report();
