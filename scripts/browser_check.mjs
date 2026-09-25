// Browser check for the dashboard (build step 9), driving a headless Chrome over the DevTools
// protocol (Node 22+, no dependencies). For each page it records console errors, CSP
// violations, horizontal overflow and, optionally, a screenshot.
//
//   node scripts/browser_check.mjs <base-url> <out-dir> [chrome-path]
//
// It never touches the network beyond <base-url> and a local Chrome; results go to
// <out-dir>/report.json and <out-dir>/*.png.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, outDir, chromePath = "C:/Program Files/Google/Chrome/Application/chrome.exe"] = process.argv.slice(2);
if (!base || !outDir) {
  console.error("usage: node scripts/browser_check.mjs <base-url> <out-dir> [chrome-path]");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const PAGES = JSON.parse(process.env.PAGES || "null") || [
  { name: "games-live", path: "/?sample=1" },
  { name: "games-nextup", path: "/?sample=1&scene=nextup" },
  { name: "games-sofar", path: "/?sample=1&scene=sofar" },
  { name: "games-final", path: "/?sample=1&scene=final" },
  { name: "games-nobets", path: "/?sample=1&scene=nobets" },
  { name: "games-before", path: "/?sample=1&scene=before" },
  { name: "games-failed", path: "/?sample=1&scene=failed" },
  { name: "games-offseason-sample", path: "/?sample=1&scene=offseason" },
  { name: "games-stale", path: "/?sample=1&scene=stale" },
  { name: "games-feeddown", path: "/?sample=1&scene=feeddown" },
  { name: "games-edges", path: "/?sample=1&scene=edges" },
  { name: "games-past-night", path: "/?sample=1#night/2026-11-16" },
  { name: "drawer", path: "/?sample=1#game/0022600195" },
  { name: "performance", path: "/?sample=1#performance" },
  { name: "performance-early", path: "/?sample=1&scene=early#performance" },
  { name: "popover-local", path: "/?sample=1&scene=failed&view=local", click: "#pipeline .pill" },
  { name: "real-root", path: "/" },
];
const WIDTHS = (process.env.WIDTHS || "1440,375").split(",").map(Number);
const SHOTS = process.env.SHOTS !== "0";
const REDUCED = process.env.REDUCED === "1";

const port = 9300 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(join(tmpdir(), "dash-chrome-"));
const chrome = spawn(chromePath, [
  "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars",
  "--force-device-scale-factor=1", "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      // Chrome still starting
    }
    await sleep(200);
  }
  throw new Error("Chrome didn't start");
}

function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) reject(new Error(data.error.message));
      else resolve(data.result);
    } else if (data.method) listeners.forEach((fn) => fn(data));
  };
  return new Promise((resolve) => {
    ws.onopen = () => resolve({
      send: (method, params = {}) => new Promise((res, rej) => {
        id += 1;
        pending.set(id, { resolve: res, reject: rej });
        ws.send(JSON.stringify({ id, method, params }));
      }),
      on: (fn) => listeners.push(fn),
      close: () => ws.close(),
    });
  });
}

const PROBE = `(() => {
  const d = document.documentElement;
  const small = [...document.querySelectorAll('button, a[href], input, select, [role=button]')]
    .filter((el) => el.offsetParent !== null && !el.closest('[hidden]'))
    .map((el) => { const r = el.getBoundingClientRect(); return { el, w: r.width, h: r.height }; })
    .filter((x) => (x.w > 0 && x.h > 0) && (x.w < 44 || x.h < 44) && !x.el.matches('.rail-day, .log-row, .ln-row, .open-bet, .closest, .bestworst-row, .skip-link'))
    .map((x) => (x.el.getAttribute('aria-label') || x.el.textContent.trim()).slice(0, 40) + ' ' + Math.round(x.w) + 'x' + Math.round(x.h));
  const unlabeled = [...document.querySelectorAll('button')].filter((b) => !b.textContent.trim() && !b.getAttribute('aria-label')).length;
  return JSON.stringify({ scrollWidth: d.scrollWidth, innerWidth: window.innerWidth, overflow: d.scrollWidth - window.innerWidth,
    h1: (document.querySelector('h1') || {}).textContent || null, errorBox: (document.querySelector('.error-box') || {}).textContent || null,
    smallTargets: small.slice(0, 12), unlabeledButtons: unlabeled, animations: document.getAnimations().length,
    flashes: document.querySelectorAll('.flash-live, .flash-hit, .flash-miss').length,
    height: Math.max(d.scrollHeight, document.body.scrollHeight) });
})()`;

async function main() {
  const cdp = await connect(await target());
  const events = [];
  cdp.on((e) => events.push(e));
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  if (REDUCED) await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  // Record CSP violations from inside the page.
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source:
    "window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI));" });
  const report = [];
  for (const width of WIDTHS) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: width < 600 ? 812 : 900, deviceScaleFactor: 1, mobile: width < 600 });
    for (const page of PAGES) {
      events.length = 0;
      await cdp.send("Page.navigate", { url: base + page.path });
      await sleep(page.wait || 3500);
      if (page.click) {
        await cdp.send("Runtime.evaluate", { expression: `document.querySelector(${JSON.stringify(page.click)}).click()` });
        await sleep(500);
      }
      const probe = JSON.parse((await cdp.send("Runtime.evaluate", { expression: PROBE, returnByValue: true })).result.value);
      const csp = (await cdp.send("Runtime.evaluate", { expression: "JSON.stringify(window.__csp||[])", returnByValue: true })).result.value;
      const consoleErrors = events
        .filter((e) => (e.method === "Runtime.exceptionThrown") || (e.method === "Log.entryAdded" && e.params.entry.level === "error")
          || (e.method === "Runtime.consoleAPICalled" && e.params.type === "error"))
        .map((e) => e.method === "Runtime.exceptionThrown" ? e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text
          : e.method === "Log.entryAdded" ? `${e.params.entry.text} ${e.params.entry.url || ""}` : e.params.args.map((a) => a.value).join(" "));
      const xssFired = events.filter((e) => e.method === "Runtime.consoleAPICalled"
        && e.params.args.some((a) => String(a.value).includes("XSS-FIRED"))).length;
      const entry = { page: page.name, width, reduced: REDUCED, ...probe, csp: JSON.parse(csp), consoleErrors, xssFired };
      if (SHOTS) {
        const full = width < 600 || page.full || process.env.FULL === "1";
        const format = process.env.FORMAT || "png";
        const shot = await cdp.send("Page.captureScreenshot", { format, ...(format === "jpeg" ? { quality: 82 } : {}),
          captureBeyondViewport: Boolean(full),
          ...(full ? { clip: { x: 0, y: 0, width, height: Math.min(probe.height, 16000), scale: 1 } } : {}) });
        const file = `${page.name}-${width}${REDUCED ? "-reduced" : ""}.${format === "jpeg" ? "jpg" : "png"}`;
        writeFileSync(join(outDir, file), Buffer.from(shot.data, "base64"));
        entry.screenshot = file;
      }
      report.push(entry);
      console.log(`${page.name} @${width}: overflow ${probe.overflow}, csp ${entry.csp.length}, errors ${consoleErrors.length}, small ${probe.smallTargets.length}, xss ${xssFired}`);
    }
  }
  writeFileSync(join(outDir, REDUCED ? "report-reduced.json" : "report.json"), JSON.stringify(report, null, 2));
  cdp.close();
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
}).finally(() => chrome.kill());
