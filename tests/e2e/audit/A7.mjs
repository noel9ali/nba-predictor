// A7: "Needs backend" note only with ?sample=1
// Test that the walkthrough's "Needs backend" note appears only in sample mode.
import { open, done, close, check, report, shot, scrollTo, WIDTHS, BASE } from './lib.mjs';

async function testWithSample() {
  console.log('\n=== TEST WITH ?sample=1 ===');
  for (const w of WIDTHS) {
    const p = await open('/model?sample=1', w);
    const ch3 = await p.$('#ch3');
    const needEls = await p.$$('#ch3 .need');
    const needCount = needEls.length;

    check(`${w}: sample=1 has exactly one .need`, needCount === 1, `found ${needCount}`);
    check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // Screenshot the step 4
    if (needCount > 0) {
      await scrollTo(p, '#ch3 .step[data-step="4"]', 1500);
      await shot(p, `A7-${w}-with-sample`, '#ch3 .step[data-step="4"]');
    }

    await done(p);
  }
}

async function testWithoutSample() {
  console.log('\n=== TEST WITHOUT ?sample=1 (with API routes) ===');

  // Create route handlers that serve sample files
  const routes = [
    [
      '**/api/model',
      async (route) => {
        const json = await (await fetch(BASE + '/sample/model.json')).json();
        await route.fulfill({ json });
      }
    ],
    [
      '**/api/performance*',
      async (route) => {
        const json = await (await fetch(BASE + '/sample/performance-all.json')).json();
        await route.fulfill({ json });
      }
    ],
    [
      '**/api/featured-pick',
      async (route) => {
        const json = await (await fetch(BASE + '/sample/featured-pick.json')).json();
        await route.fulfill({ json });
      }
    ],
    [
      '**/api/game/**',
      async (route) => {
        const url = route.request().url();
        const match = url.match(/\/game\/(\d+)/);
        if (match) {
          const gameId = match[1];
          const json = await (await fetch(BASE + `/sample/game-${gameId}.json`)).json();
          await route.fulfill({ json });
        } else {
          await route.abort();
        }
      }
    ]
  ];

  for (const w of WIDTHS) {
    const p = await open('/model', w, { route: routes });
    const needEls = await p.$$('#ch3 .need');
    const needCount = needEls.length;
    const steps = await p.$$('#ch3 .step');
    const stepCount = steps.length;

    // Check for "Needs backend" text anywhere in the page
    const bodyText = await p.evaluate(() => document.body.innerText);
    const hasNeedsBackendText = bodyText.includes('Needs backend');

    check(`${w}: no sample - .step count is 7`, stepCount === 7, `found ${stepCount}`);
    check(`${w}: no sample - zero .need elements`, needCount === 0, `found ${needCount}`);
    check(`${w}: no sample - no "Needs backend" text`, !hasNeedsBackendText, 'text found');
    check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

    // Screenshot the step 4 for visual confirmation
    await scrollTo(p, '#ch3 .step[data-step="4"]', 1500);
    await shot(p, `A7-${w}-no-sample`, '#ch3 .step[data-step="4"]');

    await done(p);
  }
}

async function run() {
  try {
    await testWithSample();
    await testWithoutSample();
  } finally {
    await close();
    report();
  }
}

run().catch(e => {
  console.error('Test failed:', e);
  process.exit(1);
});
