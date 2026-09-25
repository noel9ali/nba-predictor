// Entry point: the hash router (#games, #night/<date>, #performance, and #game/<id> for the
// drawer over whichever view is showing), the top bar and the page title.
import { SAMPLE, SCENE, SCENES } from "./api.js";
import { h, mount } from "./dom.js";
import { closeDrawer, initDrawer, isDrawerOpen, openDrawer } from "./drawer.js";
import { renderGames } from "./games.js";
import { renderPerformance } from "./performance.js";
import { initTopbar, refreshPipeline, setActiveTab } from "./topbar.js";

const main = document.getElementById("main");
let current = null; // { key, cleanup }
let drawerPushed = false;

function parse(hash) {
  const raw = (hash || "").replace(/^#/, "");
  let m = raw.match(/^game\/(\d{10})$/);
  if (m) return { name: "game", id: m[1] };
  m = raw.match(/^night\/(\d{4}-\d{2}-\d{2})$/);
  if (m) return { name: "games", date: m[1] };
  if (raw === "performance") return { name: "performance" };
  return { name: "games" };
}

function viewKey(route) {
  return route.name === "games" && route.date ? `night/${route.date}` : route.name;
}

async function showView(route) {
  const key = viewKey(route);
  if (current && current.key === key) return;
  if (current && current.cleanup) current.cleanup();
  current = { key, cleanup: null };
  setActiveTab(route.name === "performance" ? "performance" : "games");
  document.title = route.name === "performance" ? "Performance · NBA Predictor"
    : route.date ? `Night of ${route.date} · NBA Predictor` : "Games · NBA Predictor";
  mount(main, h("p.loading", "Loading…"));
  try {
    const render = route.name === "performance" ? renderPerformance : renderGames;
    const cleanup = await render(main, route);
    if (current && current.key === key) current.cleanup = cleanup;
    else if (typeof cleanup === "function") cleanup();
  } catch (err) {
    if (!current || current.key !== key) return;
    const offline = err && err.status === 503;
    mount(main, h("div.error-box", { attrs: { role: "alert" } },
      h("span.title.cond", offline ? "Game data is unavailable right now" : "This page didn't load"),
      h("span.note-line", offline ? "The database didn't answer. Try again in a few minutes." : "Try again in a moment."),
      h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: () => { current = null; route_(); } } }, "Retry")));
  }
}

function closeFromDrawer() {
  // Opened from a card or row on this page: step back in history, so Back/Forward behave.
  // Opened from a shared link: replace the hash with the view underneath.
  if (drawerPushed) {
    drawerPushed = false;
    window.history.back();
  } else {
    window.location.replace(`#${current ? current.key : "games"}`);
  }
}

function route_() {
  const route = parse(window.location.hash);
  if (route.name === "game") {
    if (!isDrawerOpen()) drawerPushed = Boolean(current);
    if (!current) showView({ name: "games" });
    openDrawer(route.id, { onClose: closeFromDrawer });
    return;
  }
  if (isDrawerOpen()) closeDrawer();
  drawerPushed = false;
  showView(route);
}

function boot() {
  initDrawer();
  initTopbar({ onRunDone: () => { current = null; route_(); refreshPipeline(); } });
  if (SAMPLE) {
    const tag = document.getElementById("sample-tag");
    tag.textContent = `Sample data · ${SCENES[SCENE].label}`;
  }
  window.addEventListener("hashchange", route_);
  route_();
}

boot();
