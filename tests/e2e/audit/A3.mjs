// A3: Sample data and copy describe the old logistic model; production is now gradient boosting
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

for (const w of WIDTHS) {
  // Tonight page checks
  const pTonight = await open('/?sample=1&scene=live', w);

  // Check model card facts
  const mfacts = await pTonight.evaluate(() => {
    const dl = document.querySelector('[data-testid=mfacts]');
    if (!dl) return null;
    const result = {};
    let dt = null;
    for (const child of dl.childNodes) {
      if (child.nodeType !== 1) continue; // Skip non-element nodes
      if (child.tagName === 'DT') {
        dt = child.textContent.trim();
      } else if (child.tagName === 'DD' && dt) {
        result[dt] = child.textContent.trim();
        dt = null;
      }
    }
    return result;
  });

  check(`${w}: Tonight mfacts exists`, !!mfacts && Object.keys(mfacts).length > 0, 'mfacts structure');

  if (mfacts) {
    const hasGradBoost = Object.values(mfacts).some(v => v.includes('Gradient boosting'));
    check(`${w}: Tonight mfacts contains "Gradient boosting"`, hasGradBoost, Object.values(mfacts).join(' | '));

    const hasOct7 = Object.values(mfacts).some(v => v.includes('Oct 7'));
    check(`${w}: Tonight mfacts shows "Oct 7"`, hasOct7, Object.values(mfacts).join(' | '));
  }

  // Take screenshot of model card
  await shot(pTonight, `A3-mfacts-${w}`);
  check(`${w}: No console errors on Tonight`, pTonight.errors.length === 0, pTonight.errors.join(' | '));

  await done(pTonight);

  // Model page checks
  const pModel = await open('/model?sample=1', w);

  // Check hero kicker
  const kicker = await pModel.evaluate(() => {
    const el = document.querySelector('section.claim [data-kicker]');
    return el ? el.textContent : null;
  });
  check(`${w}: Model kicker starts with "The model"`, kicker?.startsWith('The model'), kicker);
  check(`${w}: Model kicker contains "Gradient boosting"`, kicker?.includes('Gradient boosting'), kicker);
  check(`${w}: Model kicker contains "retrained Oct 7, 2026"`, kicker?.includes('retrained Oct 7, 2026'), kicker);

  // Check model footer
  const footer = await pModel.evaluate(() => {
    const el = document.querySelector('[data-foot]') || document.querySelector('footer [data-foot]');
    return el ? el.textContent : null;
  });
  check(`${w}: Model footer starts with "Model Gradient boosting"`, footer?.startsWith('Model Gradient boosting'), footer || 'footer not found');
  check(`${w}: Model footer contains "retrained Oct 7, 2026"`, footer?.includes('retrained Oct 7, 2026'), footer || 'footer not found');

  // Check step 4 text (walkthrough)
  const step4Text = await pModel.evaluate(() => {
    const el = document.querySelector('#ch3 .step[data-step="4"]');
    return el ? el.textContent : null;
  });
  check(`${w}: Step 4 contains "gradient-boosted"`, step4Text?.toLowerCase().includes('gradient-boosted'), step4Text);

  // Check #ch5 (leaderboard/features section)
  const ch5Why = await pModel.evaluate(() => {
    const el = document.querySelector('#ch5 [data-why] p');
    return el ? el.textContent : null;
  });
  check(`${w}: #ch5 [data-why] p starts with "It has the best log loss"`, ch5Why?.startsWith('It has the best log loss'), ch5Why);

  // Check feature importance rows count (should be 5, not 6)
  const featureCount = await pModel.evaluate(() => {
    const rows = document.querySelectorAll('#ch4 li.w');
    return rows.length;
  });
  check(`${w}: #ch4 has 5 feature rows`, featureCount === 5, `Got ${featureCount}`);

  // Check first feature label
  const firstFeature = await pModel.evaluate(() => {
    const row = document.querySelector('#ch4 li.w');
    return row ? row.textContent.split(':')[0].trim() : null;
  });
  check(`${w}: First feature is "Rating gap"`, firstFeature?.includes('Rating gap') || firstFeature?.includes('ELO'), firstFeature);

  // Check no "logistic" text except in leaderboard (allow "Cal. logistic" or "Calibrated logistic")
  const logisticCheck = await pModel.evaluate(() => {
    const bodyText = document.body.innerText;
    const lines = bodyText.split('\n').filter(l => l.toLowerCase().includes('logistic') && !l.includes('Cal') && !l.includes('Calibrated'));
    return lines;
  });
  check(`${w}: No problematic "logistic" text`, logisticCheck.length === 0, logisticCheck.join(' | '));

  // Take screenshots
  await shot(pModel, `A3-${w}`, 'section.claim');
  await scrollTo(pModel, '#ch5', 1000);
  await shot(pModel, `A3-ch5-${w}`, '#ch5');

  check(`${w}: No console errors on Model`, pModel.errors.length === 0, pModel.errors.join(' | '));

  await done(pModel);
}

await close();
report();
