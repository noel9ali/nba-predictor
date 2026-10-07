import { open, done, close, check, report, WIDTHS } from './lib.mjs';

const scenes = ['live', 'nextup', 'final', 'nobets', 'before', 'failed'];
const WIDTH = 1440;

// Pattern for valid aria-label start (matchup + time/status)
const startPattern = /^[A-Z]{2,4} at [A-Z]{2,4}, (\d{1,2}:\d{2} [AP]M ET|Time TBD|live(, .+)?|final \d+–\d+|final|postponed|void)\. /;
const endPattern = /Open details\.$/;

async function testScene(scene) {
  const p = await open(`/?sample=1&scene=${scene}`, WIDTH);
  const buttons = await p.$$('.ticket__hit');

  if (buttons.length === 0) {
    check(`${scene}: has ticket buttons`, false, 'no buttons found');
    await done(p);
    return;
  }

  const labels = await p.evaluate(() => {
    return [...document.querySelectorAll('.ticket__hit')].map(b => b.getAttribute('aria-label'));
  });

  check(`${scene}: has ticket buttons`, labels.length > 0, `found ${labels.length} buttons`);

  // Print 3 sample labels per scene
  const samples = labels.slice(0, 3);
  console.log(`  Sample labels from ${scene}:`);
  samples.forEach((label, i) => {
    console.log(`    [${i}] ${label}`);
  });

  // Check each label
  for (let i = 0; i < labels.length; i++) {
    const label = labels[i];

    // Check start pattern
    check(
      `${scene}:label[${i}] starts with matchup + time/status`,
      startPattern.test(label),
      label.substring(0, 50)
    );

    // Check ends with "Open details."
    check(
      `${scene}:label[${i}] ends with "Open details."`,
      endPattern.test(label),
      label.substring(Math.max(0, label.length - 30))
    );

    // Check for no hyphens between digits (should be en dashes)
    const hasHyphenBetweenDigits = /\d-\d/.test(label);
    check(
      `${scene}:label[${i}] uses en dash not hyphen for scores`,
      !hasHyphenBetweenDigits,
      hasHyphenBetweenDigits ? `Found hyphen in: ${label}` : 'OK'
    );

    // Check for "Bet on" when bet exists (we look for the pattern in stub)
    const hasStubBet = await p.evaluate((idx) => {
      const buttons = [...document.querySelectorAll('.ticket__hit')];
      const ticket = buttons[idx].closest('.ticket');
      const stub = ticket.querySelector('.stub');
      if (!stub) return false;
      return stub.textContent.includes('Bet on');
    }, i);

    if (hasStubBet) {
      const hasLabelBet = /Bet on [A-Z]{2,4}, \$/.test(label);
      check(
        `${scene}:label[${i}] contains bet info when ticket has bet`,
        hasLabelBet,
        hasLabelBet ? 'OK' : label
      );
    }

    // Check for "Pick * no bet" when no bet (but not pending)
    const hasStubNoBet = await p.evaluate((idx) => {
      const buttons = [...document.querySelectorAll('.ticket__hit')];
      const ticket = buttons[idx].closest('.ticket');
      const stub = ticket.querySelector('.stub');
      if (!stub) return false;
      // "Pick · no bet" has a bullet, "Pick pending" does not
      const whoSpan = stub.querySelector('.who');
      if (!whoSpan) return false;
      return whoSpan.textContent.includes('Pick') && whoSpan.textContent.includes('·');
    }, i);

    if (hasStubNoBet && !hasStubBet) {
      const hasLabelNoBet = /Pick [A-Z]{2,4}, no bet/.test(label);
      check(
        `${scene}:label[${i}] contains "Pick *, no bet" when applicable`,
        hasLabelNoBet,
        hasLabelNoBet ? 'OK' : label
      );
    }

    // Check for Model vs market when lines show it
    const hasModelMarket = await p.evaluate((idx) => {
      const buttons = [...document.querySelectorAll('.ticket__hit')];
      const ticket = buttons[idx].closest('.ticket');
      const lines = ticket.querySelector('.lines');
      if (!lines) return false;
      const text = lines.textContent;
      return text.includes('Model') && text.includes('market');
    }, i);

    if (hasModelMarket) {
      const hasLabelModel = /Model \d+\.\d% vs market \d+\.\d%/.test(label);
      check(
        `${scene}:label[${i}] contains model vs market when shown on ticket`,
        hasLabelModel,
        hasLabelModel ? 'OK' : label
      );
    }
  }

  // In final scene, every label should contain result
  if (scene === 'final') {
    for (let i = 0; i < labels.length; i++) {
      const label = labels[i];
      const hasResult = /Cashed|Lost|Pick right|Pick wrong|Void/.test(label);
      check(
        `${scene}:label[${i}] contains result status`,
        hasResult,
        hasResult ? 'OK' : label
      );
      // Labels with "no bet" must not contain "unofficial"
      if (label.includes('no bet')) {
        const hasUnofficial = label.includes('unofficial');
        check(
          `${scene}:label[${i}] with "no bet" has no "unofficial"`,
          !hasUnofficial,
          hasUnofficial ? 'Found unofficial in: ' + label : 'OK'
        );
      }
    }
  }

  // Check for console errors
  check(`${scene}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  await done(p);
}

async function testReplay() {
  const p = await open('/?sample=1&scene=live', WIDTH);

  const initialLabels = await p.evaluate(() => {
    return [...document.querySelectorAll('.ticket__hit')].map(b => b.getAttribute('aria-label'));
  });

  check('replay: initial labels exist', initialLabels.length > 0, `${initialLabels.length} labels`);

  // Step through the feed 6 times to trigger state changes
  for (let step = 0; step < 6; step++) {
    await p.evaluate(() => {
      if (window.__sampleFeed && window.__sampleFeed.step) {
        window.__sampleFeed.step();
      }
    });
    await p.waitForTimeout(200);
  }

  const finalLabels = await p.evaluate(() => {
    return [...document.querySelectorAll('.ticket__hit')].map(b => b.getAttribute('aria-label'));
  });

  // At least one label should have changed to 'final'
  const changedToFinal = finalLabels.some(label => label.includes('final'));
  check(
    'replay: labels updated after steps, at least one shows final',
    changedToFinal,
    changedToFinal ? 'Found final label' : 'No final label found'
  );

  // At least one label should be different
  const anyChanged = finalLabels.some((label, i) => label !== initialLabels[i]);
  check(
    'replay: at least one label changed',
    anyChanged,
    anyChanged ? 'Labels changed' : 'No changes detected'
  );

  check('replay: no console errors', p.errors.length === 0, p.errors.join(' | '));

  await done(p);
}

async function testPastDate() {
  const p = await open('/?sample=1&date=2026-11-16', WIDTH);

  const labels = await p.evaluate(() => {
    return [...document.querySelectorAll('.ticket__hit')].map(b => b.getAttribute('aria-label'));
  });

  if (labels.length > 0) {
    console.log(`  Sample labels from past date (2026-11-16):`);
    labels.slice(0, 3).forEach((label, i) => {
      console.log(`    [${i}] ${label}`);
    });

    for (let i = 0; i < labels.length; i++) {
      const label = labels[i];
      check(
        `past:label[${i}] matches pattern`,
        startPattern.test(label) && endPattern.test(label),
        label.substring(0, 60)
      );
    }
  }

  check('past: no console errors', p.errors.length === 0, p.errors.join(' | '));

  await done(p);
}

// Run all tests
async function runAll() {
  for (const scene of scenes) {
    await testScene(scene);
  }
  await testReplay();
  await testPastDate();
  await close();
  report();
}

runAll().catch(e => {
  console.error('Test error:', e);
  process.exit(1);
});
