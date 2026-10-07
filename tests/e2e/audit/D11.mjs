// D11: Replace "№" with "No." in ticket band and drawer kicker
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';
import { execSync } from 'child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

async function findTextNodesWithChar(page, char) {
  return await page.evaluate((c) => {
    const walker = document.createTreeWalker(
      document.documentElement,
      NodeFilter.SHOW_TEXT,
      null
    );
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent.includes(c)) {
        nodes.push(node.textContent.trim());
      }
    }
    return nodes;
  }, char);
}

async function checkBandAndDrawerKicker(page) {
  // Check band
  const bandEl = await page.$('.ticket__body .band span');
  const bandText = await bandEl?.textContent();
  check('band text contains "No."', bandText?.includes('No.'), `band: "${bandText}"`);
  check('band matches "Paper ticket · No. XXXX"', /Paper ticket · No\. \d{4}/.test(bandText), `band: "${bandText}"`);

  // Scroll to first ticket and click to open drawer
  await scrollTo(page, '.ticket', 1600);
  await page.click('.ticket__hit');
  await page.waitForTimeout(500);

  // Check drawer kicker
  const kickerEl = await page.$('.drawer .panel .ph .kk');
  const kickerText = await kickerEl?.textContent();
  check('drawer kicker text contains "No."', kickerText?.includes('No.'), `kicker: "${kickerText}"`);
  check('drawer kicker matches "Back of ticket · No. XXXX"', /Back of ticket · No\. \d{4}/.test(kickerText), `kicker: "${kickerText}"`);
}

// Test at multiple widths
for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=live', w);

  // Check for no console errors
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));

  // Check no text nodes contain '№'
  const nodesWithNumero = await findTextNodesWithChar(p, '№');
  check(`${w}: no text nodes contain '№'`, nodesWithNumero.length === 0,
    nodesWithNumero.length > 0 ? `found in: ${nodesWithNumero.join(' | ')}` : '');

  // Check band and drawer kicker
  await checkBandAndDrawerKicker(p);

  // Take screenshots
  if (w === 1440) {
    await shot(p, 'D11-before-1440', '.ticket:first-child');
    await shot(p, 'D11-before-drawer-1440', '.drawer .panel .ph');
  }

  await done(p);
}

// Run grep to confirm no '№' in the source code
try {
  execSync('grep -rn "№" public/static/js public/*.html', { cwd: ROOT });
  check('grep: no "№" in source', false, 'grep found matches');
} catch (e) {
  // grep exits with 1 when no matches found
  if (e.status === 1) {
    check('grep: no "№" in source', true);
  } else {
    check('grep: no "№" in source', false, `grep error: ${e.message}`);
  }
}

await close();
report();
