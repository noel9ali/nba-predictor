// A4: Final toasts show running total, not batch total
import { open, done, close, check, report, shot } from './lib.mjs';

// Parse money string to number: "−$64.07" or "+$36.28" -> 64.07 or 36.28
function amt(s) {
  const cleaned = s.replace(/[−+$,\s]/g, '');
  return parseFloat(cleaned) || 0;
}

// Get running total from previous toasts and this toast's P/L
async function getTodayToastValue(toastText) {
  const match = toastText.match(/Tonight\s+([\−+]?\$[\d,]+\.\d{2})/);
  if (!match) return null;
  return amt(match[1]);
}

async function getCashedLostAmount(toastText) {
  const match = toastText.match(/(Cashed|Lost)\s+([\−+]?\$[\d,]+\.\d{2})/);
  if (!match) return 0;
  const sign = match[1] === 'Cashed' ? 1 : -1;
  return sign * amt(match[2]);
}

const p = await open('/?sample=1&scene=replay', 1440);

let prevToastTexts = [];

for (let step = 1; step <= 6; step++) {
  // Get settled value before the step
  const settledBefore = await p.evaluate(() => {
    const el = document.querySelector('[data-testid=settled]');
    return el ? el.textContent : '';
  });
  const prevTotal = amt(settledBefore);

  // Step the feed
  await p.evaluate(() => window.__sampleFeed.step());
  await p.waitForTimeout(300);

  // Collect all toasts
  const toastTexts = await p.evaluate(() => {
    const toasts = Array.from(document.querySelectorAll('[data-toasts] .toast'));
    return toasts.map(t => t.textContent);
  });

  // Find NEW toasts with "Tonight" (that weren't there before)
  const newToastTexts = toastTexts.filter(t => !prevToastTexts.includes(t) && t.includes('Tonight'));
  prevToastTexts = toastTexts;

  if (newToastTexts.length > 0) {
    check(`step ${step}: has new toasts with Tonight`, true, `${newToastTexts.length} toasts`);

    let running = prevTotal;
    for (const toastText of newToastTexts) {
      // Extract the P/L amount (Cashed or Lost)
      const plAmount = await getCashedLostAmount(toastText);
      running += plAmount;

      // Get the Tonight value from the toast
      const tonightValue = await getTodayToastValue(toastText);

      check(
        `step ${step}: toast running total`,
        Math.abs(tonightValue - running) < 0.02,
        `expected ${running.toFixed(2)}, got ${tonightValue.toFixed(2)} from "${toastText.substring(0, 60)}..."`
      );
    }

    // Check that the last running total matches the board's settled
    const settledAfter = await p.evaluate(() => {
      const el = document.querySelector('[data-testid=settled]');
      return el ? el.textContent : '';
    });
    const boardTotal = amt(settledAfter);

    check(
      `step ${step}: final running equals board`,
      Math.abs(running - boardTotal) < 0.02,
      `running=${running.toFixed(2)}, board=${boardTotal.toFixed(2)}`
    );

    // Special check: DEN toast should show +$36.28
    const denToast = newToastTexts.find(t => t.includes('DEN'));
    if (denToast) {
      const denTonight = await getTodayToastValue(denToast);
      check(
        `step ${step}: DEN toast shows Tonight +$36.28`,
        Math.abs(denTonight - 36.28) < 0.02,
        `got ${denTonight.toFixed(2)}`
      );
    }
  }
}

// Take a screenshot of the toasts
await shot(p, 'A4-1440', '[data-toasts]');

check('console errors', p.errors.length === 0, p.errors.join(' | '));

await done(p);
await close();
report();
