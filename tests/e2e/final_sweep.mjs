// Final sweep for the Oct 7 audit fixes (phase 4): every Tonight scene, past mode and the Model page at
// 320–1920px. Checks: no console errors (CSP violations surface as console errors), no horizontal
// page scroll after scrolling the whole page, and, under reduced motion, end states (nothing left in
// a "pre" state, tickets and stamps visible).
//
//   node tests/e2e/final_sweep.mjs          (server on BASE, default http://127.0.0.1:5057)
import { open, done, close, check, report } from './audit/lib.mjs';

const WIDTHS = [320, 360, 400, 768, 1024, 1440, 1920];
const SCENES = ['live', 'nextup', 'sofar', 'final', 'nobets', 'before', 'failed', 'offseason', 'edges', 'stale', 'feeddown', 'early', 'replay'];
const PAGES = [...SCENES.map(s => `/?sample=1&scene=${s}`), '/?sample=1&date=2026-11-16', '/model?sample=1'];

async function scrollThrough(p) {
  const h = await p.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < h; y += 600) { await p.evaluate(v => scrollTo(0, v), y); await p.waitForTimeout(60); }
  await p.waitForTimeout(500);
}

for (const path of PAGES) {
  const bad = [], errs = [];
  for (const w of WIDTHS) {
    const p = await open(path, w, { settle: 200 });
    await scrollThrough(p);
    const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    if (over > 0) bad.push(`${w}px +${over}`);
    errs.push(...p.errors.map(e => `${w}: ${e.slice(0, 120)}`));
    await done(p);
  }
  check(`${path}: no horizontal scroll 320–1920`, bad.length === 0, bad.join(', '));
  check(`${path}: no console errors / CSP violations`, errs.length === 0, errs.slice(0, 3).join(' | '));
}

// Reduced motion: end states only.
for (const path of ['/?sample=1&scene=live', '/?sample=1&scene=final', '/model?sample=1']) {
  for (const w of [400, 1440]) {
    const p = await open(path, w, { reducedMotion: true });
    await scrollThrough(p);
    const r = await p.evaluate(() => ({
      pre: [...document.querySelectorAll('.pre')].filter(e => e.getBoundingClientRect().height > 0).map(e => e.className).slice(0, 4),
      waiting: document.querySelectorAll('.stamp.waiting').length,
      hiddenTickets: [...document.querySelectorAll('.ticket')].filter(t => getComputedStyle(t).opacity !== '1').length
    }));
    check(`reduced motion ${path} @${w}: end states`, !r.pre.length && !r.waiting && !r.hiddenTickets, JSON.stringify(r));
    check(`reduced motion ${path} @${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
    await done(p);
  }
}
await close();
report();
