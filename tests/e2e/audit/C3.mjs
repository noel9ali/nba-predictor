import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

async function testBankrollDomain(p, w, step) {
  const host = await p.locator('[data-testid=bankroll]').elementHandle();
  if (!host) {
    check(`${w} step ${step}: host found`, false, 'host not found');
    return null;
  }

  // Get the y ticks (axis labels on the left)
  const tickLabels = await host.evaluate((h) => {
    const ticks = [];
    h.querySelectorAll('text.ax').forEach((t) => {
      const text = t.textContent;
      if (text.includes('$')) {
        const rect = t.getBoundingClientRect();
        const hostRect = h.getBoundingClientRect();
        const relX = rect.left - hostRect.left;
        if (relX < 60) { // left-aligned axis labels
          const match = text.match(/\$[\d,]+/);
          if (match) {
            const value = parseInt(match[0].replace(/[$,]/g, ''), 10);
            ticks.push({
              value,
              y: rect.top - hostRect.top + rect.height / 2, // center y
              text: text
            });
          }
        }
      }
    });
    return ticks;
  });

  // Sort by value for analysis
  tickLabels.sort((a, b) => a.value - b.value);

  // Check tick spacing: consecutive tick centres should be ≥ 28px apart
  const spacingOk = tickLabels.length <= 1 || tickLabels.slice(1).every((t, i) => {
    const spacing = Math.abs(tickLabels[i].y - t.y);
    return spacing >= 28;
  });

  const spacingDetail = tickLabels.length <= 1
    ? 'only ' + tickLabels.length + ' tick(s)'
    : 'spacings: ' + tickLabels.slice(1).map((t, i) => Math.abs(tickLabels[i].y - t.y).toFixed(1)).join(', ');

  check(`${w} step ${step}: tick spacing ≥28px`, spacingOk, spacingDetail);

  // Parse tick values for domain checks
  const tickValues = tickLabels.map(t => t.value);
  const minTick = Math.min(...tickValues);
  const maxTick = Math.max(...tickValues);
  const tickStep = tickLabels.length > 1 ? tickValues[1] - tickValues[0] : 50;

  return { tickLabels, minTick, maxTick, tickStep };
}

async function testC3() {
  const stepsData = {}; // Store data per step for cross-step checks

  for (const w of WIDTHS) {
    const p = await open('/?sample=1&scene=live', w);

    // Test each step
    for (const step of [1, 2, 3]) {
      // Scroll to the step
      await scrollTo(p, `.bstep[data-bs="${step}"]`, 900);

      // Verify we're on the right step
      const currentStep = await p.locator('[data-testid=bankroll]').evaluate((h) => h.dataset.step);
      check(`${w} step ${step}: data-step matches`, currentStep === String(step), `got ${currentStep}`);

      // Get domain info
      const domainInfo = await testBankrollDomain(p, w, step);
      if (!domainInfo) {
        check(`${w} step ${step}: domain data collected`, false, 'failed to get domain data');
        await done(p);
        return;
      }

      stepsData[step] = domainInfo;

      // Take screenshot
      await shot(p, `C3-s${step}-${w}`, '.bcard');

      // Step 3: check that tonight range bar is inside the plot
      if (step === 3) {
        const tnrInside = await p.locator('[data-testid=bankroll]').evaluate((h) => {
          const tnr = h.querySelector('line.tnr');
          if (!tnr) return null; // No range bar (no open bets)

          const tny1 = parseFloat(tnr.getAttribute('y1'));
          const tny2 = parseFloat(tnr.getAttribute('y2'));
          const svg = h.querySelector('svg');
          const svgRect = svg.getBoundingClientRect();
          const pad = { t: 22, b: 28 };
          const plotTop = pad.t;
          const plotBottom = svgRect.height - pad.b;

          return {
            y1: tny1,
            y2: tny2,
            plotTop,
            plotBottom,
            inside: tny1 >= plotTop && tny2 <= plotBottom && tny2 >= plotTop && tny1 <= plotBottom
          };
        });

        if (tnrInside) {
          check(`${w} step 3: tonight range bar inside plot`, tnrInside.inside,
            tnrInside.inside ? 'OK' : `y1=${tnrInside.y1.toFixed(1)}, y2=${tnrInside.y2.toFixed(1)}, plot=[${tnrInside.plotTop.toFixed(1)}, ${tnrInside.plotBottom.toFixed(1)}]`);
        }
      }

      // Check console errors
      check(`${w} step ${step}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
    }

    // Cross-step domain checks: step-1 and step-3 top ticks should differ when range expands
    if (stepsData[1] && stepsData[3]) {
      const topTickStep1 = stepsData[1].maxTick;
      const topTickStep3 = stepsData[3].maxTick;

      // Step 3 should have a higher or equal top tick because it includes tonight's potential
      check(`${w}: step 3 top tick >= step 1 top tick`, topTickStep3 >= topTickStep1,
        `s1=${topTickStep1}, s3=${topTickStep3}`);
    }

    await done(p);
  }

  await close();
  report();
}

await testC3();
