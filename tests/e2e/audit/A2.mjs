// A2 · No empty model facts when production_model is null
// Test that when production_model and trained_at are null, we don't show empty rows
import { open, done, close, check, report, shot, WIDTHS } from './lib.mjs';

// Route to patch model.json with production_model: null and trained_at: null
const patchedRoute = async (route) => {
  const j = await (await route.fetch()).json();
  j.production_model = null;
  j.trained_at = null;
  await route.fulfill({ json: j });
};

console.log('Testing A2: No empty model facts when production_model is null\n');

for (const w of WIDTHS) {
  console.log(`\n=== Width ${w} ===`);

  // Test 1: Model page with patched model
  const modelPage = await open('/model?sample=1', w, {
    route: [['**/sample/model.json', patchedRoute]]
  });
  const kicker = await modelPage.evaluate(() => {
    const el = document.querySelector('[data-kicker]');
    return el ? el.textContent : null;
  });
  check(
    `${w}: Model page kicker is correct`,
    kicker === 'The model · Production model unavailable',
    `Got: "${kicker}"`
  );
  check(
    `${w}: Model page no console errors`,
    modelPage.errors.length === 0,
    modelPage.errors.join(' | ')
  );
  await shot(modelPage, `A2-before-${w}`, '.claim');
  await done(modelPage);

  // Test 2: Tonight page with patched model
  const tonightPage = await open('/?sample=1&scene=live', w, {
    route: [['**/sample/model.json', patchedRoute]]
  });

  // Check that mfacts doesn't have empty dd cells or certain dt values
  const mfactsInfo = await tonightPage.evaluate(() => {
    const dl = document.querySelector('[data-testid=mfacts]');
    if (!dl) return { error: 'mfacts not found' };

    const dts = Array.from(dl.querySelectorAll('dt')).map(el => ({
      text: el.textContent.trim(),
      hasSep: el.classList.contains('sep')
    }));
    const dds = Array.from(dl.querySelectorAll('dd')).map(el => ({
      text: el.textContent.trim(),
      hasSep: el.classList.contains('sep')
    }));

    return { dts, dds };
  });

  if (mfactsInfo.error) {
    check(`${w}: Tonight page has mfacts`, false, mfactsInfo.error);
  } else {
    const { dts, dds } = mfactsInfo;

    // Check no empty dd cells (excluding '—')
    const emptyDds = dds.filter(d => d.text === '');
    check(
      `${w}: Tonight mfacts has no empty dd cells`,
      emptyDds.length === 0,
      `Found ${emptyDds.length} empty dd cells`
    );

    // Check that "Live model" dt is not present
    const hasLiveModelDt = dts.some(dt => dt.text === 'Live model');
    check(
      `${w}: Tonight mfacts has no "Live model" dt`,
      !hasLiveModelDt,
      hasLiveModelDt ? 'Found "Live model" dt' : 'OK'
    );

    // Check that "Retrained" dt is not present
    const hasRetrainedDt = dts.some(dt => dt.text === 'Retrained');
    check(
      `${w}: Tonight mfacts has no "Retrained" dt`,
      !hasRetrainedDt,
      hasRetrainedDt ? 'Found "Retrained" dt' : 'OK'
    );

    // Check that first dt (if it exists) doesn't have sep class
    if (dts.length > 0 && dts[0].text !== 'This season') {
      check(
        `${w}: Tonight mfacts first dt (before "This season") has no sep`,
        !dts[0].hasSep,
        dts[0].hasSep ? 'First dt has sep class' : 'OK'
      );
    }

    // Check that at least 4 dts exist (should have This season, Test set, Always pick home, Brier score)
    check(
      `${w}: Tonight mfacts has expected rows`,
      dts.length === 4,
      `Expected 4 dts, got ${dts.length}: ${dts.map(d => d.text).join(', ')}`
    );
  }

  check(
    `${w}: Tonight page no console errors`,
    tonightPage.errors.length === 0,
    tonightPage.errors.join(' | ')
  );

  await shot(tonightPage, `A2-tonight-${w}`, '[data-testid=mfacts]');
  await done(tonightPage);
}

// Test 3: Verify unpatched data still works
console.log('\n=== Unpatched data (normal sample) ===');
const normalPage = await open('/?sample=1&scene=live', 400);
const normalMfactsInfo = await normalPage.evaluate(() => {
  const dl = document.querySelector('[data-testid=mfacts]');
  if (!dl) return { error: 'mfacts not found' };

  const dts = Array.from(dl.querySelectorAll('dt')).map(el => el.textContent.trim());
  return { dts, count: dts.length };
});

check(
  '400: Normal data has 6 mfacts rows',
  normalMfactsInfo.count === 6,
  `Got ${normalMfactsInfo.count} rows: ${normalMfactsInfo.dts.join(', ')}`
);
check(
  '400: Normal data has "Live model" and "Retrained" rows',
  normalMfactsInfo.dts.includes('Live model') && normalMfactsInfo.dts.includes('Retrained'),
  normalMfactsInfo.dts.join(', ')
);
check(
  '400: Normal page no console errors',
  normalPage.errors.length === 0,
  normalPage.errors.join(' | ')
);
await done(normalPage);

// Test 4: Verify undefined production_model also shows "Production model unavailable"
console.log('\n=== Undefined production_model ===');
const undefinedRoute = async (route) => {
  const j = await (await route.fetch()).json();
  delete j.production_model;
  j.trained_at = null;
  await route.fulfill({ json: j });
};
const undefinedPage = await open('/model?sample=1', 400, {
  route: [['**/sample/model.json', undefinedRoute]]
});
const kickerUndefined = await undefinedPage.evaluate(() => {
  const el = document.querySelector('[data-kicker]');
  return el ? el.textContent : null;
});
check(
  '400: Model page kicker handles undefined production_model',
  kickerUndefined === 'The model · Production model unavailable',
  `Got: "${kickerUndefined}"`
);
check(
  '400: Undefined model page no console errors',
  undefinedPage.errors.length === 0,
  undefinedPage.errors.join(' | ')
);
await done(undefinedPage);

await close();
report();
