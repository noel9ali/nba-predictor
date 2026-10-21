// Hardwood QA: one command that checks the Tonight and Model pages for layout, copy and motion problems.
//
//   node tools/hardwood-qa/scripts/qa.mjs
//
// Env (all optional):
//   BASE      use a running server instead of the built-in static one (e.g. http://127.0.0.1:5057)
//   QA_PUBLIC folder to serve (default: <repo>/public)
//   OUT       report folder (default ./qa-out): report.md, report.json, shots/
//   WIDTHS    comma list (default 1440,768,400)
//   ONLY      comma list of lint,page,motion (default all three)
//   PAGES     only run pages whose name contains this text (e.g. PAGES=model)
//   BASELINE  a report.json from an earlier run; its issues are tagged "known" and never fail the run.
//             Default: <skill>/baseline.json when that file exists.
//
// Severity follows the Oct 7 audit: A wrong or broken data, B functional or accessibility bug,
// C chart or label collision, D layout, copy and polish.
// Exit code 1 when a new A or B issue appears, otherwise 0. Requires `playwright` and a Chromium.
import { chromium } from 'playwright';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, '..');
const REPO = path.resolve(HERE, '../../..');
const PUBLIC = process.env.QA_PUBLIC ? path.resolve(process.env.QA_PUBLIC) : path.join(REPO, 'public');
const OUT = path.resolve(process.env.OUT || 'qa-out');
const WIDTHS = (process.env.WIDTHS || '1440,768,400').split(',').map(Number);
const ONLY = (process.env.ONLY || 'lint,page,motion').split(',');
const FILTER = process.env.PAGES || '';
const BASELINE = process.env.BASELINE || (fs.existsSync(path.join(SKILL, 'baseline.json')) ? path.join(SKILL, 'baseline.json') : '');

// ---------------------------------------------------------------- shared lists
// Phrases that read as machine-written. Edit freely; a hit is a prompt to rewrite, not a verdict.
const BANNED = [
  'dive into', 'delve', 'seamless', 'unlock', 'elevate', 'leverage', 'robust', 'game[- ]changer', 'cutting[- ]edge',
  'state[- ]of[- ]the[- ]art', 'empower', 'tapestry', 'journey', 'navigate the', "in today'?s", "it'?s worth noting",
  'at its core', 'the power of', 'supercharge', 'revolutioni[sz]e', 'harness', "here'?s the thing", "let'?s ",
  "whether you'?re", 'simply put', 'buckle up', 'not just [^.]{1,40}, but', 'effortless', 'streamline', 'welcome to'
];
// Files that may name models or quote the label map; everything else must read the model from /api/model.
const MODEL_NAME_OK = ['format.js', 'model/tryouts.js', 'model/walkthrough.js', 'model/calibration.js'];
const SCENES = ['live', 'nextup', 'sofar', 'final', 'nobets', 'before', 'failed', 'offseason', 'edges', 'stale', 'feeddown'];
const PAGES = [
  ...SCENES.map(s => ({ name: 'tonight-' + s, url: `/?sample=1&scene=${s}`, sample: true, kind: 'tonight' })),
  { name: 'tonight-past', url: '/?sample=1&date=2026-11-16', sample: true, kind: 'tonight' },
  { name: 'model-sample', url: '/model?sample=1', sample: true, kind: 'model' },
  { name: 'model-prod', url: '/model', sample: false, kind: 'model', mock: {} },
  { name: 'model-prod-no-game', url: '/model', sample: false, kind: 'model', mock: { gameStatus: 404 } },
  { name: 'model-prod-null-model', url: '/model', sample: false, kind: 'model', mock: { nullModel: true } }
].filter(p => p.name.includes(FILTER));
const MOTION_PAGES = ['tonight-live', 'tonight-final', 'model-sample'];
const MOTION_LIMIT_MS = 1200;   // the last element of a reveal should be done within this long

// ---------------------------------------------------------------- issues
const issues = [];
const add = i => issues.push(i);
const fp = i => [i.check, i.page || '', i.width || '', String(i.text || i.msg || '').slice(0, 90)].join('|');

// ---------------------------------------------------------------- static server
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png' };
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'";
function serve() {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split('?')[0]);
      if (p === '/') p = '/index.html'; else if (p === '/model') p = '/model.html';
      const f = path.join(PUBLIC, p);
      if (!f.startsWith(PUBLIC) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end('not found'); }
      res.writeHead(200, { 'content-type': MIME[path.extname(f)] || 'application/octet-stream', 'content-security-policy': CSP, 'cache-control': 'no-store' });
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, '127.0.0.1', () => resolve({ srv, base: 'http://127.0.0.1:' + srv.address().port }));
  });
}

// ---------------------------------------------------------------- static lint
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) { if (!['fonts', 'logos', 'sample'].includes(e.name)) walk(f, out); }
    else if (/\.(js|html)$/.test(e.name)) out.push(f);
  }
  return out;
}
function lint() {
  const banned = new RegExp('\\b(' + BANNED.join('|') + ')', 'i');
  const modelNames = /(logistic|gradient[- ]boost|xgboost|lstm|random[- ]forest)/i;
  const hardNumbers = /\b(6[5-9]\.\d%|71\.1\b)/;
  const placeholders = /\b(TODO|FIXME|lorem ipsum|coming soon|placeholder text)\b/i;
  for (const f of walk(PUBLIC)) {
    const rel = path.relative(PUBLIC, f).split(path.sep).join('/');
    const modelOk = MODEL_NAME_OK.some(s => rel.endsWith(s));
    fs.readFileSync(f, 'utf8').split('\n').forEach((line, n) => {
      if (/^\s*(\/\/|\*|\/\*|<!--)/.test(line) || line.includes('qa-ok')) return;
      if (!/['"`>]/.test(line)) return;                                  // copy lives in strings and markup
      const where = `${rel}:${n + 1}`;
      const text = line.trim().slice(0, 140);
      const push = (check, sev, msg) => add({ check, sev, page: 'source', msg, text: where + '  ' + text });
      if (banned.test(line)) push('copy-banned-phrase', 'D', 'Machine-sounding phrase: ' + line.match(banned)[0]);
      if (/\S\s—\s\S/.test(line)) push('copy-em-dash', 'D', 'Spaced em dash in copy; use a comma, colon or full stop');
      if (!modelOk && modelNames.test(line)) push('hardcoded-model', 'A', 'Model family named in code; read it from /api/model');
      if (hardNumbers.test(line)) push('hardcoded-number', 'A', 'Accuracy figure written into the page; read it from /api/model');
      if (placeholders.test(line)) push('placeholder', 'A', 'Placeholder text');
    });
  }
}

// ---------------------------------------------------------------- mock API for production-like pages
function sampleFile(name) { return JSON.parse(fs.readFileSync(path.join(PUBLIC, 'sample', name + '.json'), 'utf8')); }
async function mockApi(page, mock) {
  await page.route('**/api/**', route => {
    const p = route.request().url().split('/api/')[1].split('?')[0];
    const ok = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    try {
      if (p === 'model') { const m = sampleFile('model'); return ok(mock.nullModel ? { ...m, production_model: null, trained_at: null, test: null } : m); }
      if (p === 'performance') return ok(sampleFile('performance-all'));
      if (p === 'featured-pick') return ok(sampleFile('featured-pick'));
      if (p.startsWith('game/')) return mock.gameStatus && mock.gameStatus !== 200
        ? route.fulfill({ status: mock.gameStatus, contentType: 'application/json', body: '{"error":"not_found"}' })
        : ok(sampleFile('game-0022600195'));
    } catch { /* fall through */ }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });
}

// ---------------------------------------------------------------- in-page audit (runs in the browser)
function auditInPage(cfg) {
  const out = [];
  const banned = new RegExp('\\b(' + cfg.banned.join('|') + ')', 'i');
  const sel = el => {
    if (!el || !el.tagName) return '';
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (c.length) s += '.' + c.join('.');
    return s;
  };
  const abs = r => ({ x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height });
  const vis = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0' && !el.closest('[hidden]');
  };
  const push = (check, sev, msg, el, text) => out.push({ check, sev, msg, text: text || msg, sel: sel(el), rect: el ? abs(el.getBoundingClientRect()) : null });
  const seen = new Set();
  const once = (k, fn) => { if (!seen.has(k)) { seen.add(k); fn(); } };

  // text nodes
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.nodeValue.trim() && n.parentElement && !n.parentElement.closest('script,style,noscript,.ambient,[hidden]') && vis(n.parentElement)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  let broken = 0;
  for (const n of nodes) {
    const t = n.nodeValue, el = n.parentElement;
    // tokens that break across lines: "4–" / "1", "SA" / "C", "$55.58 to win $52."
    if (broken < 15) {
      const re = /\S+/g; let m;
      while ((m = re.exec(t)) && broken < 15) {
        if (m[0].length < 2) continue;
        const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
        const rects = [...r.getClientRects()];
        if (rects.length > 1 && Math.max(...rects.map(x => x.top)) - Math.min(...rects.map(x => x.top)) > 4) {
          once('brk' + m[0] + sel(el), () => { broken++; push('broken-token', 'D', `"${m[0]}" breaks across lines`, el, m[0]); });
        }
      }
    }
    let m;
    if ((m = t.match(/(?<![\d-])\d{1,3}-\d{1,3}(?![\d-])/))) once('hy' + m[0], () => push('hyphen-in-record', 'D', `"${m[0]}" uses a hyphen; records and scores take an en dash`, el, m[0]));
    if ((m = t.match(/\b20\d\d-\d\d\b(?!-)/))) once('se' + m[0], () => push('hyphen-in-season', 'D', `"${m[0]}" uses a hyphen; seasons take an en dash`, el, m[0]));
    if ((m = t.match(/\b(undefined|NaN|null|Invalid Date)\b|\[object/))) once('bad' + m[0], () => push('bad-value', 'A', `"${m[0]}" is showing on the page`, el, t.trim().slice(0, 80)));
    if (/\b0 of 0\b/.test(t)) once('0of0', () => push('zero-of-zero', 'A', '"0 of 0" is showing', el, t.trim()));
    if ((m = t.match(/gridsearch|legacy-|gradient-boosting|calibrated-xgboost|current-xgboost/i))) once('raw' + m[0], () => push('raw-model-key', 'A', `Raw model key "${m[0]}" is showing`, el, t.trim().slice(0, 80)));
    if (!cfg.sample && /needs backend|\bTODO\b|lorem ipsum/i.test(t)) once('dev' + t.slice(0, 20), () => push('dev-note-public', 'A', 'Developer note visible outside sample mode', el, t.trim().slice(0, 80)));
    if (banned.test(t)) once('ban' + t.slice(0, 30), () => push('copy-banned-phrase', 'D', 'Machine-sounding phrase: ' + t.match(banned)[0], el, t.trim().slice(0, 100)));
  }

  // empty value cells
  document.querySelectorAll('dd,.val,td').forEach(el => { if (vis(el) && !el.textContent.trim() && !el.querySelector('svg,img,i')) once('empty' + sel(el), () => push('empty-cell', 'A', 'Empty value cell', el)); });

  // ellipsized text that hides content
  document.querySelectorAll('body *').forEach(el => {
    if (getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && vis(el)) {
      once('ell' + el.textContent.slice(0, 30), () => push('truncated-text', 'D', 'Text is cut off with an ellipsis', el, el.textContent.trim().slice(0, 80)));
    }
  });

  // page overflow
  if (document.documentElement.scrollWidth > innerWidth + 1) {
    const wide = [...document.body.querySelectorAll('*')].filter(e => vis(e) && e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('[style*="overflow"]'));
    push('overflow-x', 'B', `Page is ${document.documentElement.scrollWidth - innerWidth}px wider than the window`, wide[0] || document.body, wide.slice(0, 3).map(sel).join(', '));
  }

  // chart labels
  const svgTexts = [...document.querySelectorAll('svg text')].filter(e => e.textContent.trim() && vis(e));
  const rects = svgTexts.map(e => e.getBoundingClientRect());
  let hits = 0;
  for (let i = 0; i < svgTexts.length && hits < 10; i++) {
    for (let j = i + 1; j < svgTexts.length && hits < 10; j++) {
      if (svgTexts[i].parentNode === svgTexts[j].parentNode && svgTexts[i].closest('text') === svgTexts[j].closest('text')) continue;
      const a = rects[i], b = rects[j];
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 2 && h > 2 && w * h > 8) { hits++; push('label-collision', 'C', `"${svgTexts[i].textContent.trim()}" overlaps "${svgTexts[j].textContent.trim()}"`, svgTexts[i], svgTexts[i].textContent.trim() + ' / ' + svgTexts[j].textContent.trim()); }
    }
  }
  svgTexts.forEach((t, i) => {
    const svg = t.ownerSVGElement; if (!svg) return;
    const s = svg.getBoundingClientRect(), r = rects[i];
    if (r.left < s.left - 1 || r.right > s.right + 1) once('clip' + t.textContent, () => push('label-clipped', 'C', `"${t.textContent.trim()}" runs past the chart edge`, t, t.textContent.trim()));
    svg.querySelectorAll('line,path').forEach(l => {
      const cs = getComputedStyle(l);
      if (cs.strokeDasharray === 'none' || l.closest('text')) return;
      const lr = l.getBoundingClientRect();
      if (Math.min(lr.width, lr.height) > 2) return;                    // only straight horizontal or vertical rules
      const inset = 2;
      const hx = lr.height <= 2 && lr.left < r.right && lr.right > r.left && lr.top > r.top + inset && lr.top < r.bottom - inset;
      const vx = lr.width <= 2 && lr.top < r.bottom && lr.bottom > r.top && lr.left > r.left + inset && lr.left < r.right - inset;
      if (hx || vx) once('strike' + t.textContent, () => push('label-struck', 'C', `A dashed rule runs through "${t.textContent.trim()}"`, t, t.textContent.trim()));
    });
  });

  // tap targets on phones
  if (innerWidth <= 480) {
    let n = 0;
    document.querySelectorAll('a[href],button,[role=button],summary,select,input').forEach(el => {
      if (n >= 8 || !vis(el) || el.closest('p,li:not([class])')) return;
      const r = el.getBoundingClientRect();
      if (Math.min(r.width, r.height) < 44) { n++; push('tap-target', 'D', `Tap target is ${Math.round(r.width)}×${Math.round(r.height)}px; 44px is the minimum`, el, (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40)); }
    });
  }
  return out;
}

// ---------------------------------------------------------------- per-page driver
async function openPage(browser, base, def, width, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: opts.reduced ? 'reduce' : 'no-preference' });
  const page = await ctx.newPage();
  const log = [];
  // The page wraps each section in safe(), which reports a crash as a warning ("hero failed ..."), so
  // warnings that name a failure or a script error count too.
  page.on('console', m => {
    if (m.type() === 'error' || (m.type() === 'warning' && /\bfailed\b|is not defined|Error:/.test(m.text()))) log.push(m.text());
  });
  page.on('response', r => { if (r.status() >= 400 && !/\/api\/(game\/|workflow-status)/.test(r.url())) log.push(`${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`); });
  page.on('pageerror', e => log.push(String(e)));
  await page.addInitScript(() => {
    window.__cls = 0; window.__clsSrc = [];
    try {
      new PerformanceObserver(l => {
        for (const e of l.getEntries()) {
          if (e.hadRecentInput) continue;
          window.__cls += e.value;
          for (const s of e.sources || []) {
            const n = s.node && (s.node.nodeType === 1 ? s.node : s.node.parentElement);
            if (n) window.__clsSrc.push(n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className ? '.' + n.className.trim().split(/\s+/)[0] : '') + ' ' + Math.round(e.startTime) + 'ms y ' + Math.round(s.previousRect.y) + '→' + Math.round(s.currentRect.y));
          }
        }
      }).observe({ type: 'layout-shift', buffered: true });
    } catch { /* not supported */ }
  });
  if (def.mock) await mockApi(page, def.mock);
  await page.goto(base + def.url, { waitUntil: 'networkidle' }).catch(() => {});
  await page.waitForTimeout(1200);
  return { ctx, page, log };
}
async function scrollThrough(page, step = 0.8, wait = 220, probe) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight), vh = 900;
  for (let y = 0; y < h; y += vh * step) { await page.evaluate(v => scrollTo(0, v), y); await page.waitForTimeout(wait); if (probe) await probe(); }
  await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(300);
}
const tag = (i, def, width) => ({ ...i, page: def.name, width });

async function pageChecks(browser, base, def, width, shots) {
  const { ctx, page, log } = await openPage(browser, base, def, width);
  await scrollThrough(page);
  const found = await page.evaluate(auditInPage, { banned: BANNED, sample: def.sample });
  found.forEach(i => add(tag(i, def, width)));
  // console and CSP noise (expected 404s from a mocked failing /api/game are not counted)
  const expected404 = def.mock && def.mock.gameStatus === 404;
  log.filter(m => !/Failed to load resource/.test(m)).slice(0, 5).forEach(m => add({ check: 'console-error', sev: 'B', page: def.name, width, msg: 'Console error', text: m.slice(0, 160) }));
  // keyboard: is every focus stop visible and not buried under the fixed ribbon?
  const stops = new Set();
  for (let k = 0; k < 70; k++) {
    await page.keyboard.press('Tab');
    const r = await page.evaluate(() => {
      const a = document.activeElement;
      if (!a || a === document.body) return null;
      const rc = a.getBoundingClientRect();
      if (rc.width < 1 || rc.bottom < 0 || rc.top > innerHeight) return { off: true, sel: a.tagName };
      const top = document.elementFromPoint(rc.left + rc.width / 2, rc.top + Math.min(rc.height / 2, 20));
      const covered = top && !a.contains(top) && !top.contains(a);
      const name = (a.getAttribute('aria-label') || a.textContent || '').trim().slice(0, 50);
      return { covered: !!covered, by: covered ? (top.tagName.toLowerCase() + '.' + String(top.className).split(' ')[0]) : '', name, y: rc.top + scrollY, h: rc.height, x: rc.left + scrollX, w: rc.width, id: a.tagName + a.className + name };
    });
    if (!r) continue;
    if (stops.has(r.id)) break;
    stops.add(r.id);
    if (r.covered) add({ check: 'focus-hidden', sev: 'B', page: def.name, width, msg: `Focus lands under ${r.by}`, text: r.name, rect: { x: r.x, y: r.y, w: r.w, h: r.h } });
  }
  // chart tooltip must stay inside its card (Tonight season chart)
  if (def.kind === 'tonight' && width >= 768) {
    const chart = page.locator('.chart').first();
    if (await chart.count()) {
      await chart.scrollIntoViewIfNeeded().catch(() => {});
      const box = await chart.boundingBox();
      if (box) {
        for (let t = 0; t <= 12; t++) {
          await page.mouse.move(box.x + 4 + (box.width - 8) * (t / 12), box.y + box.height / 2); await page.waitForTimeout(40);
          const bad = await page.evaluate(() => {
            const tip = document.querySelector('.chart .tip:not([hidden])'); if (!tip) return null;
            const r = tip.getBoundingClientRect(), c = (tip.closest('.card') || tip.parentElement).getBoundingClientRect();
            return (r.left < c.left || r.right > c.right) ? { text: tip.textContent.slice(0, 40), by: Math.round(Math.max(c.left - r.left, r.right - c.right)) } : null;
          });
          if (bad) { add({ check: 'tooltip-clipped', sev: 'B', page: def.name, width, msg: `Tooltip sticks out of its card by ${bad.by}px`, text: bad.text }); break; }
        }
      }
    }
  }
  // screenshots of the worst spots
  const mine = issues.filter(i => i.page === def.name && i.width === width && i.rect && ['A', 'B', 'C'].includes(i.sev)).slice(0, 6);
  for (const [n, i] of mine.entries()) {
    const f = path.join(shots, `${def.name}-${width}-${i.check}-${n}.png`);
    const pad = 24, r = i.rect;
    await page.screenshot({ path: f, fullPage: true, clip: { x: Math.max(0, r.x - pad), y: Math.max(0, r.y - pad), width: Math.min(1400, r.w + pad * 2), height: Math.min(700, r.h + pad * 2) } }).catch(() => {});
    i.shot = path.relative(OUT, f);
  }
  await ctx.close();
}

async function motionChecks(browser, base, def, width) {
  for (const reduced of [false, true]) {
    const { ctx, page } = await openPage(browser, base, def, width, { reduced });
    const seenAnim = new Map();
    const probe = async () => {
      const list = await page.evaluate(() => document.getAnimations().map(a => {
        const t = a.effect && a.effect.getComputedTiming(), tg = a.effect && a.effect.target;
        const c = tg && typeof tg.className === 'string' ? tg.className.trim().split(/\s+/)[0] : '';
        return { name: a.animationName || a.transitionProperty || 'animation', sel: tg ? tg.tagName.toLowerCase() + (c ? '.' + c : '') : '', end: t ? t.endTime : 0, delay: t ? t.delay : 0, iter: t ? t.iterations : 1, dur: t ? t.duration : 0 };
      }));
      for (const a of list) { const k = a.name + '|' + a.sel; const prev = seenAnim.get(k); if (!prev || a.end > prev.end) seenAnim.set(k, a); }
    };
    await probe();
    await scrollThrough(page, 0.5, 160, probe);
    const cls = await page.evaluate(() => window.__cls);
    const clsSrc = await page.evaluate(() => [...new Set(window.__clsSrc)].slice(0, 4).join(', '));
    if (reduced) {
      for (const a of seenAnim.values()) {
        if (a.dur > 50) add({ check: 'reduced-motion', sev: 'B', page: def.name, width, msg: `${a.name} on ${a.sel} still runs with reduced motion on`, text: a.name + ' ' + a.sel });
      }
    } else {
      for (const a of seenAnim.values()) {
        if (/^amb-/.test(a.name)) continue;                              // decorative background drawing
        if (Number.isFinite(a.end) && a.end > MOTION_LIMIT_MS) add({ check: 'motion-long', sev: 'D', page: def.name, width, msg: `${a.name} on ${a.sel} finishes ${Math.round(a.end)}ms after it starts (delay ${Math.round(a.delay)}ms); the limit is ${MOTION_LIMIT_MS}ms`, text: a.name + ' ' + a.sel });
      }
      if (cls > 0.1) add({ check: 'layout-shift', sev: 'D', page: def.name, width, msg: `Content jumps while loading and scrolling (layout shift ${cls.toFixed(2)})`, text: 'CLS ' + cls.toFixed(2) + (clsSrc ? ' · ' + clsSrc : '') });
    }
    await ctx.close();
  }
}

// ---------------------------------------------------------------- report
function report(startedAt) {
  const known = new Set();
  if (BASELINE && fs.existsSync(BASELINE)) { try { JSON.parse(fs.readFileSync(BASELINE, 'utf8')).issues.forEach(i => known.add(i.fp)); } catch { /* ignore */ } }
  issues.forEach(i => { i.fp = fp(i); i.known = known.has(i.fp); });
  const fresh = issues.filter(i => !i.known);
  const sevName = { A: 'A · wrong or broken data', B: 'B · functional and accessibility', C: 'C · chart and label collisions', D: 'D · layout, copy and polish' };
  const lines = [`# Hardwood QA report`, '', `Run ${startedAt.toISOString()} · widths ${WIDTHS.join(', ')} · ${fresh.length} new, ${issues.length - fresh.length} known`, ''];
  for (const s of ['A', 'B', 'C', 'D']) {
    const list = fresh.filter(i => i.sev === s);
    lines.push(`## ${sevName[s]} (${list.length})`, '');
    const byCheck = {};
    list.forEach(i => { (byCheck[i.check] ||= []).push(i); });
    for (const [c, arr] of Object.entries(byCheck)) {
      lines.push(`### ${c} (${arr.length})`);
      const merged = new Map();
      arr.forEach(i => { const k = (i.msg || '') + '|' + (i.text || ''); const m = merged.get(k) || { i, where: [] }; m.where.push(`${i.page}${i.width ? '@' + i.width : ''}`); merged.set(k, m); });
      for (const { i, where } of merged.values()) lines.push(`- ${i.msg}${i.text && i.text !== i.msg ? ' — `' + String(i.text).replace(/`/g, "'") + '`' : ''}  \n  ${[...new Set(where)].join(', ')}${i.shot ? '  \n  ' + i.shot : ''}`);
      lines.push('');
    }
    if (!list.length) lines.push('None.', '');
  }
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'report.md'), lines.join('\n'));
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ startedAt, issues }, null, 1));
  const count = s => fresh.filter(i => i.sev === s).length;
  console.log(`\nHardwood QA: A ${count('A')} · B ${count('B')} · C ${count('C')} · D ${count('D')}   (${issues.length - fresh.length} known)`);
  console.log('Report: ' + path.join(OUT, 'report.md'));
  return count('A') + count('B');
}

// ---------------------------------------------------------------- main
const startedAt = new Date();
fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true });
if (ONLY.includes('lint')) { lint(); console.log('lint done'); }
if (ONLY.includes('page') || ONLY.includes('motion')) {
  const own = process.env.BASE ? null : await serve();
  const base = process.env.BASE || own.base;
  const browser = await chromium.launch();
  if (ONLY.includes('page')) {
    for (const def of PAGES) {
      await Promise.all(WIDTHS.map(w => pageChecks(browser, base, def, w, path.join(OUT, 'shots')).catch(e => add({ check: 'qa-crash', sev: 'B', page: def.name, width: w, msg: 'The check itself failed', text: String(e).slice(0, 160) }))));
      console.log('checked ' + def.name);
    }
  }
  if (ONLY.includes('motion')) {
    for (const def of PAGES.filter(p => MOTION_PAGES.includes(p.name))) {
      for (const w of [1440, 400].filter(x => WIDTHS.includes(x))) await motionChecks(browser, base, def, w).catch(e => add({ check: 'qa-crash', sev: 'B', page: def.name, width: w, msg: 'The motion check failed', text: String(e).slice(0, 160) }));
      console.log('motion ' + def.name);
    }
  }
  await browser.close();
  if (own) own.srv.close();
}
process.exit(report(startedAt) > 0 ? 1 : 0);
