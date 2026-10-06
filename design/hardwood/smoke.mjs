// node smoke.mjs <url> <width> <out.png|-> [--reduced] [--full] [--scroll=selector] [--eval=js]
import { chromium } from 'playwright';
const [url, w, out, ...flags] = process.argv.slice(2);
const has = f => flags.includes(f);
const opt = k => (flags.find(f => f.startsWith('--' + k + '=')) || '').split('=').slice(1).join('=');
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: +w, height: 900 }, ...(has('--reduced') ? { reducedMotion: 'reduce' } : {}) });
const page = await ctx.newPage();
const errs = [];
page.on('pageerror', e => errs.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.type() + ': ' + m.text()); });
page.on('requestfailed', r => errs.push('reqfail: ' + r.url()));
await page.addInitScript(() => document.addEventListener('securitypolicyviolation', e => console.error('CSP ' + e.violatedDirective + ' ' + e.blockedURI)));
await page.goto(url);
await page.waitForTimeout(1500);
if (has('--through')) {
  const dh = await page.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < dh; y += 300) { await page.evaluate(y => scrollTo(0, y), y); await page.waitForTimeout(120); }
  await page.waitForTimeout(1500); await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(800);
}
if (opt('scroll')) { await page.evaluate(s => document.querySelector(s)?.scrollIntoView({ block: 'center' }), opt('scroll')); await page.waitForTimeout(1500); }
if (opt('eval')) console.log('eval:', JSON.stringify(await page.evaluate(opt('eval'))));
const o = await page.evaluate(() => ({ sw: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), iw: innerWidth, h: document.documentElement.scrollHeight }));
console.log('overflow:', o.sw > o.iw ? 'YES ' + o.sw + '/' + o.iw : 'no', 'height', o.h);
console.log(errs.length ? errs.join('\n') : 'no errors');
if (out && out !== '-') await page.screenshot({ path: out, fullPage: has('--full') });
await browser.close();
