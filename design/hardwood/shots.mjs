// node shots.mjs <url> <width> <prefix> sel[:frac] ...   viewport shots with the element at frac of its height
import { chromium } from 'playwright';
const [url, w, prefix, ...targets] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: +w, height: 900 } })).newPage();
const errs = [];
page.on('pageerror', e => errs.push(e.message));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.goto(url); await page.waitForTimeout(1200);
let i = 0;
for (const t of targets) {
  const [sel, frac = '0'] = t.split(':');
  await page.evaluate(([s, f]) => { const el = document.querySelector(s); const r = el.getBoundingClientRect(); scrollTo(0, scrollY + r.top + r.height * +f - 60); }, [sel, frac]);
  await page.waitForTimeout(1600);
  await page.screenshot({ path: `${prefix}-${++i}.png` });
}
console.log(errs.length ? errs.join('\n') : 'no errors');
await browser.close();
