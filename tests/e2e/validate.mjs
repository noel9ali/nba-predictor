// Acceptance test package: Tonight (dir-hybrid) + Model (model-p3).
//
// HOW TO POINT THIS AT THE REAL BUILD
//   BASE=http://127.0.0.1:5057 node validate.mjs
//   - BASE            origin of the running build. Tonight is loaded from `${BASE}${TONIGHT_PATH}?sample=1`
//                     and Model from `${BASE}${MODEL_PATH}?sample=1` (defaults: "/" and "/model").
//   - TONIGHT_URL / MODEL_URL  full URLs, override the above (used by the prototype run: file://...).
//   - OUT             output directory (default: directory of this script -> ./results.json + ./screens/).
//   - WIDTHS          comma list, default 400,768,1440.
//   - Prototype-only controls: the prototype drives its feed with [data-testid=advance]/[data-testid=reset].
//     In the real build, replace ADVANCE() below so it steps the live-replay sample files
//     (sample=1 replay: 10 steps from the "initial" file to the "after 10" file). Everything else
//     (selectors, expected numbers) is the same DOM contract. The hash deep link is #g<game_id>.
//   - The font shim (fontshim.mjs) exists ONLY because Google Fonts is blocked in the authoring sandbox.
//     It is imported dynamically (FONTSHIM env var or the sandbox path) and silently skipped when absent.
//     Do not ship it and do not use it against the real build.
//   - Requires `playwright` resolvable from the working directory and a preinstalled Chromium.
//
// Exit code: 0 when everything PASSes, 1 otherwise.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
let shimFonts = async () => {};
try { ({ shimFonts } = await import(process.env.FONTSHIM || '/home/claude/proto/fontshim.mjs')); } catch { /* real build: no shim */ }

const BASE = process.env.BASE;
const URLS = {
  tonight: process.env.TONIGHT_URL || (BASE ? `${BASE}${process.env.TONIGHT_PATH || '/'}?sample=1` : 'file:///home/claude/proto/dist/dir-hybrid.standalone.html'),
  model: process.env.MODEL_URL || (BASE ? `${BASE}${process.env.MODEL_PATH || '/model'}?sample=1` : 'file:///home/claude/proto/dist/model-p3.standalone.html'),
};
const OUT = process.env.OUT || HERE;
const SCREENS = path.join(OUT, 'screens');
fs.mkdirSync(SCREENS, { recursive: true });
const WIDTHS = (process.env.WIDTHS || '400,768,1440').split(',').map(Number);
const H = 900;
const EXPECT = { settled0: '58.36', settled10: '117.01', edgeFirst: '0022600190', bets: { bets: 5, live: 3, final: 1 }, final10: 6 };

// ---------- result bookkeeping ----------
const results = { tonight: {}, model: {} };
const rec = (page, test, w, ok, detail) => {
  const t = (results[page][test] ||= { status: 'PASS', details: [] });
  if (!ok) t.status = 'FAIL';
  t.details.push(`[${w}] ${ok ? 'ok' : 'FAIL'}: ${detail}`);
};
const errors = { tonight: [], model: [] };

const browser = await chromium.launch();
async function open(pageKey, w, { reduced = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: H }, deviceScaleFactor: 1, ...(reduced ? { reducedMotion: 'reduce' } : {}) });
  await shimFonts(ctx);
  const page = await ctx.newPage();
  const tag = `${w}${reduced ? 'r' : ''}`;
  page.on('pageerror', e => errors[pageKey].push(`[${tag}] pageerror: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') errors[pageKey].push(`[${tag}] console.error: ${m.text()}`); });
  page.on('requestfailed', r => { const u = r.url(); if (!/fonts\.(googleapis|gstatic)/.test(u)) errors[pageKey].push(`[${tag}] requestfailed: ${u} ${r.failure()?.errorText}`); });
  await page.goto(URLS[pageKey]);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  return { ctx, page };
}
const reload = async (page, url) => { await page.goto(url); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(500); };
const scrollTo = (page, y) => page.evaluate(y => window.scrollTo({ top: y, behavior: 'instant' }), y);
const scrollToEl = (page, sel, frac = 0.5, idx = 0) => page.evaluate(([sel, frac, idx]) => {
  const el = document.querySelectorAll(sel)[idx]; const r = el.getBoundingClientRect();
  window.scrollTo({ top: scrollY + r.top + r.height * frac - innerHeight * frac, behavior: 'instant' });
}, [sel, frac, idx]);
const shot = (page, key, w, scene) => page.screenshot({ path: path.join(SCREENS, `${key}-${w}-${scene}.png`) });
const widthNow = page => page.evaluate(() => ({ sw: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), iw: innerWidth }));
async function overflowTest(page, key, w) {
  const dh = await page.evaluate(() => document.documentElement.scrollHeight);
  const out = [];
  for (const [label, y] of [['top', 0], ['mid', Math.round((dh - H) / 2)], ['bottom', dh]]) {
    await scrollTo(page, y); await page.waitForTimeout(150);
    out.push({ label, ...(await widthNow(page)) });
  }
  rec(key, '1_no_horizontal_overflow', w, out.every(o => o.sw <= o.iw), out.map(o => `${o.label}: scrollWidth ${o.sw} / innerWidth ${o.iw}`).join('; '));
  await scrollTo(page, 0);
}
const runningAnims = page => page.evaluate(() => document.getAnimations().filter(a => a.playState === 'running').map(a => {
  const t = a.effect?.target; return (a.animationName || a.transitionProperty || 'anim') + '@' + (t ? t.tagName.toLowerCase() + (typeof t.className === 'string' && t.className ? '.' + t.className.split(' ')[0] : '') : '?');
}));
// PROTOTYPE-ONLY: replace with a step of the live-replay sample files in the real build.
// Real build: step the sample live-replay files through the sample-only hook (no Advance bar ships).
const ADVANCE = async (page, n, gap = 120) => { for (let i = 0; i < n; i++) { await page.evaluate(() => window.__sampleFeed.step()); await page.waitForTimeout(gap); } };
const txt = (page, sel) => page.evaluate(s => document.querySelector(s)?.textContent.replace(/\s+/g, ' ').trim() ?? null, sel);
const counts = page => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('[data-testid=filters] [data-f]')].map(b => [b.dataset.f, +(b.textContent.match(/(\d+)\s*$/)?.[1] ?? NaN)])));

// =====================================================================================
// TONIGHT
// =====================================================================================
async function tonight(w) {
  const K = 'tonight';
  const { ctx, page } = await open(K, w);
  try {
    await overflowTest(page, K, w);
    await shot(page, K, w, 'top');

    // ---- 5a filter counts, 5b sort ----
    const c0 = await counts(page);
    rec(K, '5a_filter_counts_initial', w, c0.bets === EXPECT.bets.bets && c0.live === EXPECT.bets.live && c0.final === EXPECT.bets.final, `counts=${JSON.stringify(c0)} expected bets ${EXPECT.bets.bets}, live ${EXPECT.bets.live}, final ${EXPECT.bets.final}`);
    const nTix = await page.locator('[data-testid=grid] article[data-testid=ticket]').count();
    const nBtn = await page.locator('[data-testid=grid] article[data-testid=ticket] > button').count();
    rec(K, '5h_tickets_are_articles_with_cover_button', w, nTix > 0 && nBtn === nTix, `${nTix} article[data-testid=ticket], ${nBtn} full-cover buttons`);
    await page.click('[data-testid=sorts] [data-s=edge]'); await page.waitForTimeout(300);
    const first = await page.evaluate(() => document.querySelector('[data-testid=grid] [data-testid=ticket]')?.dataset.id);
    rec(K, '5b_sort_edge_first', w, first === EXPECT.edgeFirst, `first ticket data-id after sort=edge: ${first} (expected ${EXPECT.edgeFirst})`);
    await page.click('[data-testid=sorts] [data-s=tip]'); await page.waitForTimeout(200);
    await page.click('[data-testid=filters] [data-f=bets]'); await page.waitForTimeout(250);
    const nb = await page.locator('[data-testid=grid] [data-testid=ticket]').count();
    rec(K, '5a2_filter_bets_shows_count', w, nb === c0.bets, `bets filter shows ${nb} tickets (count chip ${c0.bets})`);
    await page.click('[data-testid=filters] [data-f=all]'); await page.waitForTimeout(250);

    const s0 = await txt(page, '[data-testid=settled]');
    rec(K, '5c0_settled_initial', w, !!s0 && s0.includes(EXPECT.settled0), `[data-testid=settled]="${s0}" (expected to contain ${EXPECT.settled0})`);

    // ---- glance courts ----
    await scrollToEl(page, '[data-testid=chart]', 0.5); await page.waitForTimeout(1300);
    const gl = await page.evaluate(() => { const rows = [...document.querySelectorAll('[data-testid=chart] .gl')]; return { n: rows.length, empty: rows.filter(r => !r.textContent.trim()).length }; });
    rec(K, '5i_glance_courts_populated', w, gl.n === nTix && gl.empty === 0, `.gl rows=${gl.n}, tickets=${nTix}, empty rows=${gl.empty}`);
    await shot(page, K, w, 'glance');

    // ---- 4a keyboard (fresh load for a clean tab order) ----
    await reload(page, URLS.tonight);
    let tabs = 0, onTicket = false;
    for (; tabs < 60 && !onTicket;) { await page.keyboard.press('Tab'); tabs++; onTicket = await page.evaluate(() => !!document.activeElement?.closest('[data-testid=ticket]') && document.activeElement.tagName === 'BUTTON'); }
    const firstId = await page.evaluate(() => document.activeElement?.closest('[data-testid=ticket]')?.dataset.id);
    const firstIdDom = await page.evaluate(() => document.querySelector('[data-testid=grid] [data-testid=ticket]')?.dataset.id);
    rec(K, '4a1_tab_reaches_first_ticket_button', w, onTicket && firstId === firstIdDom, `reached after ${tabs} Tab presses; focused ticket ${firstId}, first in DOM ${firstIdDom}`);
    const fv = await page.evaluate(() => { const b = document.activeElement; const cs = getComputedStyle(b); const pcs = getComputedStyle(b.closest('[data-testid=ticket]')); const pseudo = getComputedStyle(b, '::after'); return { focusVisible: b.matches(':focus-visible'), btnOutline: cs.outlineStyle + ' ' + cs.outlineWidth, btnShadow: cs.boxShadow !== 'none', ticketOutline: pcs.outlineStyle, ticketShadowChanged: false }; });
    rec(K, '4a0_ticket_focus_visible', w, fv.focusVisible && (!/^none/.test(fv.btnOutline) || fv.btnShadow), JSON.stringify(fv));
    await page.keyboard.press('Enter'); await page.waitForTimeout(450);
    const dr = await page.evaluate(() => { const d = document.querySelector('[data-testid=drawer]'); const a = document.activeElement; const dl = d.querySelector('[role=dialog]'); return { hidden: d.hidden, open: d.hasAttribute('data-open'), dialog: !!dl, modal: dl?.getAttribute('aria-modal'), labelled: !!dl?.getAttribute('aria-labelledby'), focusInside: d.contains(a) }; });
    rec(K, '4a2_enter_opens_drawer', w, !dr.hidden && dr.open && dr.dialog && dr.modal === 'true' && dr.labelled && dr.focusInside, JSON.stringify(dr));
    await page.waitForTimeout(250);
    await shot(page, K, w, 'drawer');
    let outside = 0; const seen = new Set();
    for (let i = 0; i < 25; i++) { await page.keyboard.press('Tab'); const r = await page.evaluate(() => { const a = document.activeElement; return { inside: document.querySelector('[data-testid=drawer]').contains(a), id: a.tagName + (a.textContent || '').trim().slice(0, 12) + (a.getAttribute('data-close') !== null ? '[close]' : '') }; }); if (!r.inside) outside++; seen.add(r.id); }
    for (let i = 0; i < 3; i++) { await page.keyboard.press('Shift+Tab'); if (!(await page.evaluate(() => document.querySelector('[data-testid=drawer]').contains(document.activeElement)))) outside++; }
    rec(K, '4a3_focus_trap_25_tabs', w, outside === 0, `25 Tab + 3 Shift+Tab; presses landing outside dialog: ${outside}; distinct focus stops: ${seen.size}`);
    await page.keyboard.press('Escape'); await page.waitForTimeout(450);
    const after = await page.evaluate(() => { const d = document.querySelector('[data-testid=drawer]'); const a = document.activeElement; return { hidden: d.hidden, open: d.hasAttribute('data-open'), focusedTicket: a?.closest('[data-testid=ticket]')?.dataset.id }; });
    rec(K, '4a4_esc_closes_and_returns_focus', w, after.hidden && !after.open && after.focusedTicket === firstId, `${JSON.stringify(after)} (opener ticket ${firstId})`);
    await page.keyboard.press('Enter'); await page.waitForTimeout(450);
    let closeOk = true;
    try { await page.click('[data-testid=drawer] button[data-close]', { timeout: 1500 }); } catch { closeOk = false; await page.keyboard.press('Escape'); }
    await page.waitForTimeout(450);
    const hid2 = await page.evaluate(() => document.querySelector('[data-testid=drawer]').hidden);
    rec(K, '4a5_close_button_closes', w, closeOk && hid2, `click button[data-close] ${closeOk ? 'ok' : 'not clickable'}; drawer hidden=${hid2}`);

    // ---- 4b chart keyboard ----
    await scrollToEl(page, '[data-testid=bankroll]', 0.5); await page.waitForTimeout(900);
    await page.focus('[data-testid=bankroll]');
    const bf = await page.evaluate(() => { const b = document.querySelector('[data-testid=bankroll]'); return { tabindex: b.getAttribute('tabindex'), focused: document.activeElement === b, label: !!b.getAttribute('aria-label') }; });
    await page.keyboard.press('ArrowLeft'); await page.waitForTimeout(250);
    const tp = await page.evaluate(() => { const t = document.querySelector('[data-testid=bankroll] .tip'); const r = t?.getBoundingClientRect(); return { exists: !!t, hidden: t?.hidden, w: r && Math.round(r.width), text: t?.textContent.replace(/\s+/g, ' ').slice(0, 50) }; });
    rec(K, '4b_bankroll_focusable_arrow_shows_tip', w, bf.focused && bf.tabindex === '0' && bf.label && tp.exists && tp.hidden === false && tp.w > 0, `focus=${JSON.stringify(bf)} tip=${JSON.stringify(tp)}`);
    await page.keyboard.press('Escape');

    // ---- 4c deep link ----
    await page.goto(URLS.tonight + '#g' + EXPECT.edgeFirst); await page.reload(); await page.waitForTimeout(800);
    const dl = await page.evaluate(() => { const d = document.querySelector('[data-testid=drawer]'); return { hidden: d.hidden, open: d.hasAttribute('data-open'), text: d.querySelector('[role=dialog]')?.textContent.slice(0, 40).replace(/\s+/g, ' ') }; });
    rec(K, '4c_deeplink_opens_drawer', w, !dl.hidden && dl.open, `#g${EXPECT.edgeFirst}: ${JSON.stringify(dl)}`);
    await page.keyboard.press('Escape'); await page.waitForTimeout(400);
    await reload(page, URLS.tonight);

    // ---- 5d0 initial final ticket stamp lands on scroll ----
    {
      const info = await page.evaluate(() => [...document.querySelectorAll('[data-testid=ticket]')].filter(t => t.querySelector('.stamp')).map(t => ({ id: t.dataset.id, cls: t.querySelector('.stamp').className })));
      const id = info[0]?.id;
      if (id) {
        await scrollToEl(page, `[data-testid=ticket][data-id="${id}"]`, 0.5); await page.waitForTimeout(1100);
        const cls = await page.evaluate(id => document.querySelector(`[data-testid=ticket][data-id="${id}"] .stamp`).className, id);
        rec(K, '5d0_initial_final_stamp_lands', w, /\bin\b/.test(cls) && !/waiting/.test(cls), `${info.length} stamped ticket(s) at start; class before scroll: "${info[0].cls}"; after scroll into view: "${cls}"`);
        await shot(page, K, w, 'tickets-stamp');
      } else rec(K, '5d0_initial_final_stamp_lands', w, false, 'no ticket with .stamp at initial state');
    }

    // ---- 5e ribbon ----
    {
      await scrollTo(page, 0); await page.waitForTimeout(500);
      const top = await page.evaluate(() => document.querySelector('.ribbon').classList.contains('on'));
      await scrollToEl(page, '[data-testid=grid]', 0.3); await page.waitForTimeout(900);
      const mid = await page.evaluate(() => { const r = document.querySelector('.ribbon'); const b = r.getBoundingClientRect(); return { on: r.classList.contains('on'), top: Math.round(b.top), h: Math.round(b.height) }; });
      await scrollToEl(page, '[data-testid=grid]', 1); await page.waitForTimeout(500);
      const lowTix = await page.evaluate(() => document.querySelector('.ribbon').classList.contains('on'));
      rec(K, '5e_ribbon_on_between_board_and_season_off_at_top', w, !top && mid.on && mid.top >= -2 && lowTix, `top=${top ? 'on' : 'off'}; mid-tickets=${mid.on ? 'on' : 'off'} (ribbon top ${mid.top}px, h ${mid.h}px); end-of-tickets=${lowTix ? 'on' : 'off'}`);
      await scrollTo(page, 0); await page.waitForTimeout(300);
    }

    // ---- 5c advance 10 ----
    await ADVANCE(page, 10, 150);
    await page.waitForTimeout(600);
    const s10 = await txt(page, '[data-testid=settled]');
    const toasts = await page.locator('.toast').count();
    const finalCount = (await counts(page)).final;
    const tape = await txt(page, '[data-testid=tape]'), hero = await txt(page, '[data-testid=hero]');
    const betsOk = /4\s*[–-]\s*1/.test((tape || '') + ' ' + (hero || ''));
    rec(K, '5c_after_10_advances', w, !!s10 && s10.includes(EXPECT.settled10) && toasts <= 3 && betsOk && finalCount === EXPECT.final10,
      `settled="${s10}" (expect ${EXPECT.settled10}); .toast count=${toasts} (<=3); bets 4–1 in tape/hero=${betsOk}; final filter count=${finalCount} (expect ${EXPECT.final10})`);

    // ---- 5d stamps: waiting off-screen, .in once scrolled into view ----
    {
      const ids = await page.evaluate(() => [...document.querySelectorAll('[data-testid=ticket]')].filter(t => t.querySelector('.stamp')).map(t => t.dataset.id));
      const before = await page.evaluate(() => [...document.querySelectorAll('[data-testid=ticket] .stamp')].filter(s => s.classList.contains('waiting')).length);
      const bad = [];
      for (const id of ids) {
        await scrollToEl(page, `[data-testid=ticket][data-id="${id}"]`, 0.45); await page.waitForTimeout(420);
        if (!(await page.evaluate(id => { const s = document.querySelector(`[data-testid=ticket][data-id="${id}"] .stamp`); return s.classList.contains('in') && !s.classList.contains('waiting'); }, id))) bad.push(id);
      }
      rec(K, '5d_final_stamps_land_after_scroll', w, ids.length === EXPECT.final10 && !bad.length, `${ids.length} stamped tickets (expect ${EXPECT.final10}); .waiting before scrolling: ${before}; not .in after scrolled into view: [${bad.join(',')}]`);
      await scrollToEl(page, '[data-testid=ticket]', 0.5, 1); await page.waitForTimeout(500);
      await shot(page, K, w, 'tickets-stamps-final');
    }

    // ---- 5f / 5g bankroll steps ----
    {
      const bs = await page.evaluate(() => document.querySelectorAll('.bstep').length);
      const align = [];
      for (const i of [0, 1, 2]) {
        await page.evaluate(i => { const el = document.querySelectorAll('.bstep')[i]; const r = el.getBoundingClientRect(); window.scrollTo({ top: scrollY + r.top + r.height / 2 - innerHeight / 2 + 2, behavior: 'instant' }); }, i);
        await page.waitForTimeout(900);
        align.push(await page.evaluate(() => { const a = document.querySelector('.bstep.act'); const inn = a?.querySelector('.bstep__in').getBoundingClientRect(); const card = document.querySelector('.bcard').getBoundingClientRect(); return { step: document.querySelector('[data-testid=bankroll]').dataset.step, act: a?.dataset.bs, inTop: inn && Math.round(inn.top), cardTop: Math.round(card.top) }; }));
        await shot(page, K, w, 'season-' + (i + 1));
      }
      const seq = align.map(a => a.step);
      rec(K, '5f_bankroll_step_1_2_3', w, bs === 3 && seq.join() === '1,2,3' && align.every((a, i) => a.act === String(i + 1)), `.bstep count=${bs}; [data-testid=bankroll][data-step] as each .bstep is centred: ${seq.join('→')}; .bstep.act: ${align.map(a => a.act).join(',')}`);
      const dev = align.map(a => a.inTop - (a.cardTop + 40));
      const desktop = w >= 1024;
      rec(K, '5g_bstep_text_aligned_to_chart_card', w, desktop ? dev.every(d => Math.abs(d) <= 60) : true, desktop ? `(.bstep__in top - (.bcard top + 40)) per step: ${dev.join(', ')}px (limit ±60)` : `not asserted below desktop; measured offsets ${dev.join(', ')}px`);
      const tn = await page.evaluate(() => !!document.querySelector('[data-testid=bankroll] .tn'));
      rec(K, '5j_step3_tonight_overlay', w, tn, `[data-testid=bankroll] .tn present=${tn}`);
    }
    const o = await widthNow(page);
    rec(K, '1b_no_overflow_after_10_advances', w, o.sw <= o.iw, `scrollWidth ${o.sw} / innerWidth ${o.iw}`);
  } catch (e) { rec(K, '0_script_error', w, false, String(e.stack || e).slice(0, 500)); }
  await ctx.close();
}

async function tonightReduced(w) {
  const K = 'tonight';
  const { ctx, page } = await open(K, w, { reduced: true });
  try {
    await ADVANCE(page, 10, 120);
    const dh = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < dh; y += 300) { await scrollTo(page, y); await page.waitForTimeout(40); }
    await page.waitForTimeout(800);
    const run = await runningAnims(page);
    rec(K, '3_reduced_motion_no_running_animations', w, run.length === 0, run.length ? `running (${run.length}): ${run.slice(0, 6).join(', ')}` : '0 running animations after load + scroll-through + 10 advances');
    const st = await page.evaluate(() => { const s = [...document.querySelectorAll('[data-testid=ticket] .stamp')]; return { n: s.length, bad: s.filter(x => x.classList.contains('waiting') || getComputedStyle(x).visibility === 'hidden' || +getComputedStyle(x).opacity < 1).length }; });
    rec(K, '3b_reduced_motion_stamps_visible', w, st.n === EXPECT.final10 && st.bad === 0, `${st.n} stamps on final tickets (expect ${EXPECT.final10}), ${st.bad} waiting/hidden/translucent`);
    const pre = await page.evaluate(() => document.querySelectorAll('.pre').length);
    rec(K, '3c_reduced_motion_no_pending_reveals', w, pre === 0, `elements still carrying .pre: ${pre}`);
  } catch (e) { rec(K, '0_script_error', w + 'r', false, String(e.stack || e).slice(0, 500)); }
  await ctx.close();
}

// =====================================================================================
// MODEL
// =====================================================================================
async function model(w) {
  const K = 'model';
  const { ctx, page } = await open(K, w);
  try {
    await overflowTest(page, K, w);
    await shot(page, K, w, 'top');
    const geom = await page.evaluate(() => { const r = document.querySelector('[data-scrolly]').getBoundingClientRect(); return { top: r.top + scrollY, range: r.height - innerHeight }; });
    const h0 = await page.evaluate(() => ({ state: document.querySelector('[data-scrolly] .pin').dataset.state, title: document.querySelector('[data-title]').textContent.replace(/\s+/g, ' ') }));
    const courtTop = () => page.evaluate(() => { const c = document.querySelector('[data-court]'); const r = c.getBoundingClientRect(); return { rect: r.top, h: r.height, layout: c.offsetTop, transform: getComputedStyle(c).transform }; });
    await scrollTo(page, geom.top + geom.range * 0.2); await page.waitForTimeout(1000);
    const stBase = await page.evaluate(() => document.querySelector('[data-scrolly] .pin').dataset.state);
    const cB = await courtTop();
    await shot(page, K, w, 'claim-base');
    await scrollTo(page, geom.top + geom.range * 0.35); await page.waitForTimeout(1500);
    const h1 = await page.evaluate(() => ({ state: document.querySelector('[data-scrolly] .pin').dataset.state, title: document.querySelector('[data-title]').textContent.replace(/\s+/g, ' ') }));
    const cM = await courtTop();
    await shot(page, K, w, 'claim-model');
    // Oct 7 2026 (audit A3): production is gradient boosting, test accuracy 0.6792 -> 67.9% (was logistic 68.1%).
    rec(K, '6a_hero_state_and_title', w, h0.state === 'base' && stBase === 'base' && h1.state === 'model' && h1.title.includes('67.9%') && !h0.title.includes('67.9%'),
      `top: state=${h0.state} title="${h0.title}"; 20% in: ${stBase}; 35% in: state=${h1.state} title="${h1.title}"`);
    const dRect = Math.abs(cM.rect - cB.rect);
    rec(K, '6b_court_top_stable_between_states', w, cB.layout === cM.layout && dRect >= 3 && dRect <= 5, `[data-court] getBoundingClientRect().top base=${cB.rect.toFixed(2)} model=${cM.rect.toFixed(2)} delta=${dRect.toFixed(2)}px (M-4 amended, ruling 8: layout equal, visual lift 3–5px); layout offsetTop ${cB.layout}→${cM.layout}; transform base=${cB.transform} model=${cM.transform}; height ${cB.h.toFixed(1)}→${cM.h.toFixed(1)}`);
    await scrollTo(page, geom.top + geom.range * 0.2); await page.waitForTimeout(500);
    const back = await page.evaluate(() => document.querySelector('[data-scrolly] .pin').dataset.state);
    rec(K, '6a2_hero_reverts_to_base_scrolling_up', w, back === 'base', `state at 20% after visiting 35%: ${back}`);

    const g2 = await page.evaluate(() => { const r = document.querySelector('[data-scrolly2]').getBoundingClientRect(); return { top: r.top + scrollY, h: r.height }; });
    await scrollTo(page, g2.top + 20); await page.waitForTimeout(1300);
    const p2a = await page.evaluate(() => document.querySelector('.pin2').dataset.state);
    await shot(page, K, w, 'season-strip-all');
    await scrollTo(page, g2.top + g2.h * 0.5); await page.waitForTimeout(1300);
    const p2b = await page.evaluate(() => document.querySelector('.pin2').dataset.state);
    await shot(page, K, w, 'season-strip-split');
    rec(K, '6c_pin2_state_switches', w, p2a === 'all' && p2b === 'split', `[data-scrolly2] .pin2 state: start=${p2a}, 50% in=${p2b}`);

    const nSteps = await page.locator('.step').count();
    const gfxBad = [];
    for (let i = 0; i < nSteps; i++) {
      await scrollToEl(page, '.step .gfx', 0.5, i); await page.waitForTimeout(i === 0 || i === nSteps - 1 ? 1500 : 1100);
      const run = await page.evaluate(i => document.querySelectorAll('.step .gfx')[i].getAnimations({ subtree: true }).filter(a => a.playState === 'running').map(a => (a.animationName || a.transitionProperty || 'anim') + (a.effect?.getComputedTiming().iterations === Infinity ? '(infinite)' : '')), i);
      if (run.length) gfxBad.push(`step ${i + 1}: ${run.join('|')}`);
      if (i === 0) await shot(page, K, w, 'walkthrough-1');
      if (i === nSteps - 1) await shot(page, K, w, 'walkthrough-7');
    }
    rec(K, '6e_walkthrough_gfx_settled', w, nSteps === 7 && !gfxBad.length, `${nSteps} .step (expect 7); running animations/transitions in .gfx after settle: ${gfxBad.length ? gfxBad.join('; ') : 'none'}`);

    await scrollToEl(page, '[data-bump]', 0.5); await page.waitForTimeout(1500);
    const bump = await page.evaluate(() => { const s = document.querySelector('[data-bump] svg'); const r = s?.getBoundingClientRect(); return { svg: !!s, w: r && Math.round(r.width), paths: s ? s.querySelectorAll('path').length : 0 }; });
    await shot(page, K, w, 'bump');
    await scrollToEl(page, '[data-cal]', 0.5); await page.waitForTimeout(1500);
    const cal = await page.evaluate(() => { const s = document.querySelector('[data-cal] svg'); const r = s?.getBoundingClientRect(); return { svg: !!s, w: r && Math.round(r.width), circles: s ? s.querySelectorAll('circle').length : 0 }; });
    await shot(page, K, w, 'calibration');
    rec(K, '6f_bump_and_calibration_render', w, bump.svg && bump.w > 0 && bump.paths > 0 && cal.svg && cal.w > 0 && cal.circles > 0, `[data-bump] svg ${JSON.stringify(bump)}; [data-cal] svg ${JSON.stringify(cal)}`);

    await scrollTo(page, 0);
    const dh = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < dh; y += 150) { await scrollTo(page, y); await page.waitForTimeout(45); }
    await page.waitForTimeout(700);
    const rv = await page.evaluate(() => ({ total: document.querySelectorAll('[data-reveal]').length, notIn: [...document.querySelectorAll('[data-reveal]:not(.in)')].map(e => String(e.className).slice(0, 30) + '@h' + Math.round(e.getBoundingClientRect().height)) }));
    rec(K, '6d_all_reveals_get_in', w, rv.total > 0 && rv.notIn.length === 0, `${rv.total} [data-reveal]; without .in after scroll-through: ${rv.notIn.length ? rv.notIn.join(', ') : 'none'}`);

    await reload(page, URLS.model);
    const nFocusable = await page.evaluate(() => [...document.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,summary,[tabindex]:not([tabindex="-1"])')].filter(e => e.offsetParent !== null).length);
    const noRing = []; let stops = 0;
    for (let i = 0; i < 80; i++) {
      await page.keyboard.press('Tab');
      const r = await page.evaluate(() => { const a = document.activeElement; if (!a || a === document.body) return null; const cs = getComputedStyle(a); return { desc: a.tagName.toLowerCase() + (a.id ? '#' + a.id : '') + '[' + (a.textContent || '').trim().slice(0, 18) + ']', vis: (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none' }; });
      if (!r) break; stops++; if (!r.vis) noRing.push(r.desc);
    }
    rec(K, '4_every_focusable_has_visible_focus', w, stops > 0 && !noRing.length, `${stops} Tab stops (${nFocusable} visible focusable elements in DOM); without outline/box-shadow: ${noRing.length ? noRing.join(', ') : 'none'}`);
  } catch (e) { rec(K, '0_script_error', w, false, String(e.stack || e).slice(0, 500)); }
  await ctx.close();
}

async function modelReduced(w) {
  const K = 'model';
  const { ctx, page } = await open(K, w, { reduced: true });
  try {
    const dh = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < dh; y += 250) { await scrollTo(page, y); await page.waitForTimeout(40); }
    await page.waitForTimeout(800);
    const run = await runningAnims(page);
    rec(K, '3_reduced_motion_no_running_animations', w, run.length === 0, run.length ? `running (${run.length}): ${run.slice(0, 6).join(', ')}` : '0 running animations after load + scroll-through');
    const rv = await page.evaluate(() => ({ total: document.querySelectorAll('[data-reveal]').length, notIn: document.querySelectorAll('[data-reveal]:not(.in)').length }));
    rec(K, '3b_reduced_motion_reveals_visible', w, rv.notIn === 0, `${rv.total} [data-reveal], ${rv.notIn} without .in`);
  } catch (e) { rec(K, '0_script_error', w + 'r', false, String(e.stack || e).slice(0, 500)); }
  await ctx.close();
}

// =====================================================================================
const t0 = Date.now();
const el = () => ((Date.now() - t0) / 1000).toFixed(0) + 's';
for (const w of WIDTHS) { await tonight(w); console.log('tonight', w, el()); }
for (const w of WIDTHS) await tonightReduced(w);
console.log('tonight reduced', el());
for (const w of WIDTHS) { await model(w); console.log('model', w, el()); }
for (const w of WIDTHS) await modelReduced(w);
await browser.close();

for (const k of ['tonight', 'model']) {
  const e = errors[k];
  results[k]['2_no_console_or_page_errors'] = { status: e.length ? 'FAIL' : 'PASS', details: e.length ? e.slice(0, 20) : ['0 pageerror, 0 console.error, 0 non-font failed requests across all widths and reduced-motion runs'] };
  results[k] = Object.fromEntries(Object.entries(results[k]).sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true })));
}
fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ generated: new Date().toISOString(), urls: URLS, widths: WIDTHS, results }, null, 2));
let fail = 0, total = 0;
for (const k of Object.keys(results)) for (const [t, v] of Object.entries(results[k])) { total++; if (v.status !== 'PASS') { fail++; console.log('FAIL', k, t, '\n   ' + v.details.filter(d => !/\] ok:/.test(d)).join('\n   ')); } }
console.log(`${total - fail}/${total} PASS in ${el()}`);
process.exit(fail ? 1 : 0);
