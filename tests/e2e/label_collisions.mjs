// Label-collision check for every SVG chart on Tonight and the Model page (Oct 7 audit, phase 4).
// At 400, 768 and 1440, for every visible SVG <text>: no two text boxes intersect, every rendered
// text is >= 11px, and every text box (and the bankroll tooltip, swept night by night) stays inside
// its card. Tonight runs scenes live, final, nobets, feeddown and replay (after 6 feed steps); the
// bankroll chart is checked at each of its three scroll steps.
//
//   node tests/e2e/label_collisions.mjs          (server on BASE, default http://127.0.0.1:5057)
import { open, done, close, check, report, scrollTo } from './audit/lib.mjs';

const WIDTHS = [400, 768, 1440];
const SCENES = ['live', 'final', 'nobets', 'feeddown', 'replay'];

// Runs in the page: every problem among the visible texts of the SVGs inside `root`.
function auditTexts(rootSel) {
  const out = [];
  const visible = el => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
      if (n instanceof SVGElement && n.getAttribute('visibility') === 'hidden') return false;
    }
    let op = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) op *= parseFloat(getComputedStyle(n).opacity);
    return op > 0.05;
  };
  const cardOf = el => el.closest('.card, .ticket, .mini-ticket') || el.closest('svg').parentElement;
  const roots = rootSel ? [...document.querySelectorAll(rootSel)] : [document];
  for (const root of roots) {
    for (const svg of root.querySelectorAll('svg')) {
      const r = svg.getBoundingClientRect();
      if (!r.width || !r.height || !visible(svg)) continue;
      const name = svg.closest('[data-testid], [data-cal], [data-bump], section[id]');
      const where = (name && (name.dataset.testid || (name.dataset.cal !== undefined ? 'ch6-cal' : name.dataset.bump !== undefined ? 'bump' : name.id))) || 'svg';
      const texts = [...svg.querySelectorAll('text')].filter(t => t.textContent.trim() && visible(t))
        .map(t => {
          const m = t.getScreenCTM();
          const scale = m ? Math.hypot(m.a, m.b) : 1;
          return { t, label: t.textContent.trim().slice(0, 30), rect: t.getBoundingClientRect(), px: parseFloat(getComputedStyle(t).fontSize) * scale };
        });
      for (const a of texts) {
        if (a.px < 10.95) out.push(`${where}: "${a.label}" renders at ${a.px.toFixed(1)}px`);
        const c = cardOf(a.t).getBoundingClientRect();
        if (a.rect.left < c.left - 0.5 || a.rect.right > c.right + 0.5 || a.rect.top < c.top - 0.5 || a.rect.bottom > c.bottom + 0.5) {
          out.push(`${where}: "${a.label}" leaves its card`);
        }
      }
      for (let i = 0; i < texts.length; i++) {
        for (let j = i + 1; j < texts.length; j++) {
          const a = texts[i].rect, b = texts[j].rect;
          if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) {
            out.push(`${where}: "${texts[i].label}" overlaps "${texts[j].label}"`);
          }
        }
      }
    }
  }
  return out;
}

async function settleAll(p) {
  // Scroll the whole page through once so every reveal-on-scroll chart has drawn.
  const h = await p.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < h; y += 500) { await p.evaluate(v => scrollTo(0, v), y); await p.waitForTimeout(120); }
  await p.waitForTimeout(2200);
}

async function bankrollSteps(p, tag) {
  for (const n of [1, 2, 3]) {
    await scrollTo(p, `.bstep[data-bs="${n}"]`, 1100);
    const step = await p.evaluate(() => document.querySelector('[data-testid=bankroll]')?.dataset.step);
    const probs = await p.evaluate(auditTexts, '.bcard');
    check(`${tag} bankroll step ${n} (on ${step}): labels clear`, probs.length === 0, probs.join(' | '));
  }
  // Tooltip sweep: every night, keyboard.
  await scrollTo(p, '.bstep[data-bs="1"]', 900);
  await p.focus('[data-testid=bankroll]');
  const n = await p.evaluate(() => document.querySelectorAll('[data-testid=bankroll] svg .ax').length);
  for (let i = 0; i < 80; i++) await p.keyboard.press('ArrowLeft');
  const bad = [];
  for (let i = 0; i < 80; i++) {
    const r = await p.evaluate(() => {
      const host = document.querySelector('[data-testid=bankroll]'), tip = host.querySelector('.tip'), card = host.closest('.card');
      if (!tip || tip.hidden) return null;
      const a = tip.getBoundingClientRect(), c = card.getBoundingClientRect();
      return { inside: a.left >= c.left - 0.5 && a.right <= c.right + 0.5 && a.top >= c.top - 0.5 && a.bottom <= c.bottom + 0.5, text: tip.textContent.slice(0, 24) };
    });
    if (r && !r.inside) bad.push(r.text);
    const before = await p.evaluate(() => document.querySelector('[data-testid=bankroll] .tip')?.textContent);
    await p.keyboard.press('ArrowRight');
    const after = await p.evaluate(() => document.querySelector('[data-testid=bankroll] .tip')?.textContent);
    if (after === before) break;
  }
  check(`${tag} bankroll tooltip inside its card for every night`, bad.length === 0, bad.join(' | ') || `${n} axis labels`);
  await p.keyboard.press('Escape');
}

for (const w of WIDTHS) {
  for (const scene of SCENES) {
    const tag = `${w} ${scene}`;
    const p = await open(`/?sample=1&scene=${scene}`, w);
    if (scene === 'replay') for (let i = 0; i < 6; i++) { await p.evaluate(() => window.__sampleFeed.step()); await p.waitForTimeout(250); }
    await settleAll(p);
    const probs = await p.evaluate(auditTexts, null);
    check(`${tag} Tonight: SVG labels clear`, probs.length === 0, probs.join(' | '));
    if (await p.$('[data-testid=bankroll] svg')) await bankrollSteps(p, tag);
    check(`${tag} no console errors`, p.errors.length === 0, p.errors.join(' | '));
    await done(p);
  }
  const p = await open('/model?sample=1', w);
  await settleAll(p);
  const probs = await p.evaluate(auditTexts, null);
  check(`${w} Model: SVG labels clear`, probs.length === 0, probs.join(' | '));
  check(`${w} Model: no console errors`, p.errors.length === 0, p.errors.join(' | '));
  await done(p);
}
await close();
report();
