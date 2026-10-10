// C5: One money format in the season section's titles and copy
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';

// Helper to check money format: must be $X,XXX.XX with exactly 2 decimals
// Negatives must use − (U+2212), not -
function checkMoneyFormat(text, isAxisLabel = false) {
  // Regex to find all money amounts: [+−±-]?\$[\d,]+(\.\d+)?
  const moneyRegex = /[+−±-]?\$[\d,]+(\.\d+)?/g;
  const matches = [...text.matchAll(moneyRegex)];

  const issues = [];
  for (const m of matches) {
    const str = m[0];

    // Y-axis labels should be $X,XXX (no decimals)
    if (isAxisLabel) {
      if (!/^\$[\d,]+$/.test(str)) {
        issues.push(`Axis label has decimals: ${str}`);
      }
      if (str.includes('-') && !str.includes('−')) {
        issues.push(`Axis label uses hyphen instead of minus: ${str}`);
      }
    } else {
      // All other money should have exactly 2 decimals: $X,XXX.XX
      if (!/\.\d{2}$/.test(str)) {
        issues.push(`Missing exactly 2 decimals: ${str}`);
      }
      // Negatives must use − (U+2212), not '-'
      if (str.includes('-') && !str.includes('−')) {
        issues.push(`Uses hyphen instead of minus: ${str}`);
      }
    }
  }
  return issues;
}

async function testScene(scene, isPast = false) {
  const url = isPast ? '/?sample=1&date=2026-11-16' : `/?sample=1&scene=${scene}`;

  // Test at 1440 width
  const p = await open(url, 1440);

  // Scroll to season section
  await scrollTo(p, '#season', 1000);

  // Check no console errors
  check(`${scene}/1440: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Collect all text from season section and all its aria-labels
  const seasonEl = await p.$('#season');
  if (seasonEl) {
    const seasonText = await seasonEl.evaluate(el => {
      const texts = [];
      const walk = (node) => {
        // Skip SVG text elements with class "ax" (axis labels)
        if (node.nodeType === 1) { // ELEMENT_NODE
          if (node.tagName === 'text' && node.classList.contains('ax')) {
            return; // Skip axis labels
          }
          for (const child of node.childNodes) walk(child);
        } else if (node.nodeType === 3) { // TEXT_NODE
          texts.push(node.textContent);
        } else {
          for (const child of node.childNodes) walk(child);
        }
      };
      walk(el);
      return texts.join('');
    });
    const ariaLabels = await seasonEl.evaluate(el => {
      const labels = [];
      for (const attr of el.querySelectorAll('[aria-label]')) {
        labels.push(attr.getAttribute('aria-label'));
      }
      return labels;
    });

    // Check main text
    let issues = checkMoneyFormat(seasonText);
    check(`${scene}/1440: money format in text`, issues.length === 0, issues.join('; '));

    // Check aria-labels
    for (const label of ariaLabels) {
      // Axis labels may contain non-money text; extract just the money format
      issues = checkMoneyFormat(label);
      check(`${scene}/1440: money format in aria-label`, issues.length === 0, `[${label}] — ${issues.join('; ')}`);
    }

    // Check step 1 title format: "From $X,XXX.XX to $Y,YYY.YY"
    const step1Title = await p.$('.bstep[data-bs="1"] h4');
    if (step1Title) {
      const titleText = await step1Title.textContent();
      const titleOk = /^From \$[\d,]+\.\d{2} to \$[\d,]+\.\d{2}$/.test(titleText);
      check(`${scene}/1440: step 1 title format`, titleOk, titleText);
    }
  }

  // Screenshot at 1440
  await shot(p, `C5-1440-${scene}`, '.bstep[data-bs="1"]');

  await done(p);
}

// Test title at 400 width
const p400 = await open('/?sample=1&scene=live', 400);
const step1Title400 = await p400.$('.bstep[data-bs="1"] h4');
if (step1Title400) {
  const titleText = await step1Title400.textContent();
  const titleOk = /^From \$[\d,]+\.\d{2} to \$[\d,]+\.\d{2}$/.test(titleText);
  check('400: step 1 title format', titleOk, titleText);
}
await done(p400);

// Test all scenes at 1440
await testScene('live');
await testScene('nobets');
await testScene('final');
await testScene('past', true);

await close();
report();
