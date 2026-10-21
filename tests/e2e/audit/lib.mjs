// Shared helpers for the Oct 7 audit fix checks (design/hardwood/audit/tasks/*.md).
// Each finding has tests/e2e/audit/<ID>.mjs built on these. Server: Flask with the production
// CSP on BASE (default http://127.0.0.1:5057). Run: node tests/e2e/audit/<ID>.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const BASE = process.env.BASE || 'http://127.0.0.1:5057';
export const WIDTHS = [400, 768, 1440];
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
export const AFTER_DIR = path.join(ROOT, 'design', 'hardwood', 'audit', 'after');

let browser = null;
export async function launch() {
  if (!browser) browser = await chromium.launch();
  return browser;
}
export async function close() { if (browser) await browser.close(); browser = null; }

// Open a page at a width. opts: { height=900, reducedMotion=false, route: [[pattern, handler]] }.
// Waits for html[data-ready] (both pages set it once their first data has landed) and fonts.
export async function open(urlPath, width, opts = {}) {
  const b = await launch();
  const ctx = await b.newContext({
    viewport: { width, height: opts.height || 900 },
    reducedMotion: opts.reducedMotion ? 'reduce' : 'no-preference'
  });
  const page = await ctx.newPage();
  page.errors = [];
  page.on('pageerror', e => page.errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') page.errors.push(m.text()); });
  for (const [pattern, handler] of opts.route || []) await page.route(pattern, handler);
  await page.goto(BASE + urlPath, { waitUntil: 'load' });
  await page.waitForSelector('html[data-ready]', { timeout: 15000 }).catch(() => {});
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.waitForTimeout(opts.settle ?? 400);
  return page;
}
export async function done(page) { await page.context().close(); }

// Scroll an element into the middle of the viewport and let reveal animations finish.
export async function scrollTo(page, selector, wait = 1500) {
  await page.evaluate(s => { const el = document.querySelector(s); if (el) el.scrollIntoView({ block: 'center' }); }, selector);
  await page.waitForTimeout(wait);
}

// Screenshot: of an element (selector) or the viewport. name -> design/hardwood/audit/after/<name>.png
export async function shot(page, name, selector) {
  fs.mkdirSync(AFTER_DIR, { recursive: true });
  const file = path.join(AFTER_DIR, name + '.png');
  if (selector) {
    const el = await page.$(selector);
    if (el) { await el.screenshot({ path: file }); return file; }
  }
  await page.screenshot({ path: file });
  return file;
}

// Tiny assertion collector: check(name, ok, detail). report() prints and sets the exit code.
const results = [];
export function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? '  — ' + detail : ''));
}
export function report() {
  const failed = results.filter(r => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
  process.exitCode = failed ? 1 : 0;
  return failed === 0;
}

// Two DOMRects intersect (with a tolerance in px; positive tol = must be clearly apart).
export const intersects = (a, b, tol = 0) =>
  a.left < b.right - tol && b.left < a.right - tol && a.top < b.bottom - tol && b.top < a.bottom - tol;
