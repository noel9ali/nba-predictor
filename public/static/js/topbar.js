// Top bar: tabs, the refresh status (Games tonight only), the pipeline pill and popover
// (Nav-Pipeline board) and the "Sample data" tag. Run now / Retry render only when
// /api/workflow-status says controls_allowed (the laptop running Flask); public viewers get
// the read-only popover.
import { ApiError, SAMPLE, api, now } from "./api.js";
import { clear, h, icon, mount } from "./dom.js";
import { dateTimeET, elapsed, modelName, pct, timeET } from "./format.js";
import { escapeStack } from "./keys.js";
import { toast } from "./toast.js";

const state = { status: null, model: null, open: false, releaseEsc: null, runStartedAt: null, poll: null, tick: null };
let onRunFinished = () => {};

export function initTopbar({ onRunDone }) {
  onRunFinished = onRunDone || onRunFinished;
  document.getElementById("sample-tag").hidden = !SAMPLE;
  document.addEventListener("click", (e) => {
    const wrap = document.getElementById("pipeline");
    if (state.open && !wrap.contains(e.target)) closePopover();
  });
  loadPipeline();
}

export function setActiveTab(name) {
  for (const tab of ["games", "performance"]) {
    const el = document.getElementById(`tab-${tab}`);
    if (tab === name) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  }
}

// ------------------------------------------------------------------ refresh status
// status: null (hidden) | {kind: "normal"|"busy"|"stale"|"done", at: Date|null, onRefresh}
export function setRefreshStatus(status) {
  const el = document.getElementById("refresh-status");
  if (!status) {
    el.hidden = true;
    clear(el);
    return;
  }
  el.hidden = false;
  el.className = "refresh";
  const at = status.at ? timeET(status.at.toISOString()) : null;
  if (status.kind === "busy") {
    el.classList.add("is-busy");
    mount(el, "Updating scores…",
      h("button.icon-btn", { attrs: { type: "button", "aria-label": "Refreshing", disabled: true } }, icon("refresh", 16)));
  } else if (status.kind === "stale") {
    el.classList.add("is-stale");
    mount(el, icon("warn", 16, 2.2), at ? `Scores delayed · last update ${at}` : "Scores delayed",
      h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: status.onRefresh } }, "Retry"));
  } else if (status.kind === "done") {
    mount(el, "All games final · updates stopped");
  } else {
    mount(el, h("span.refresh-dot", { attrs: { "aria-hidden": "true" } }),
      at ? `Updated ${at} · every 30s` : "Scores refresh every 30s",
      h("button.icon-btn", { attrs: { type: "button", "aria-label": "Refresh scores now" }, on: { click: status.onRefresh } },
        icon("refresh", 16)));
  }
}

// ------------------------------------------------------------------ pipeline pill
async function loadPipeline() {
  try {
    const [status, model] = await Promise.all([api.workflowStatus(), api.model().catch(() => null)]);
    state.status = status;
    state.model = model;
  } catch {
    state.status = null;
  }
  renderPill();
}

export function pipelineStatus() {
  return state.status;
}

function pillState() {
  const ws = state.status;
  if (!ws) return { kind: "unknown", label: "Pipeline · status unavailable" };
  const runs = ["morning", "predict", "manual"].map((k) => ws.latest && ws.latest[k]).filter(Boolean);
  if (ws.running || state.runStartedAt || runs.some((r) => r.state === "running")) return { kind: "running", label: "Pipeline running" };
  if (!runs.length) return { kind: "unknown", label: "Pipeline · status unavailable" };
  if (runs.some((r) => r.state === "failed")) return { kind: "failed", label: "Pipeline failed" };
  const morning = ws.latest.morning;
  if (morning && morning.state === "missed") return { kind: "missed", label: "No run today" };
  const ref = morning || runs[0];
  const t = timeET(ref.finished_at || ref.started_at);
  return { kind: "ok", label: t ? `Pipeline · ${t}` : "Pipeline OK" };
}

function renderPill() {
  const wrap = document.getElementById("pipeline");
  const { kind, label } = pillState();
  const button = h(`button.pill.pill--${kind}.cond`, {
    attrs: { type: "button", "aria-expanded": state.open ? "true" : "false", "aria-controls": "pipeline-popover", "aria-haspopup": "dialog" },
    on: { click: (e) => { e.stopPropagation(); state.open ? closePopover() : openPopover(); } },
  }, h("span.dot", { attrs: { "aria-hidden": "true" } }), label, icon("chevronDown", 16, 2.5));
  mount(wrap, button);
  if (state.open) wrap.appendChild(popover());
}

function openPopover() {
  state.open = true;
  state.releaseEsc = escapeStack.push(() => closePopover(true));
  renderPill();
}

function closePopover(restoreFocus = false) {
  if (!state.open) return;
  state.open = false;
  if (state.releaseEsc) state.releaseEsc();
  state.releaseEsc = null;
  renderPill();
  if (restoreFocus) document.querySelector("#pipeline .pill").focus();
}

function runLine(run, { fallbackSub, okLabel = "OK" }) {
  if (!run) return { value: "No run yet", cls: "muted", sub: fallbackSub };
  const t = timeET(run.finished_at || run.started_at) || "";
  if (run.state === "running") return { value: `Running · started ${timeET(run.started_at) || ""}`, cls: "accent", sub: fallbackSub };
  if (run.state === "failed") return { value: `Failed · ${t}`, cls: "neg", sub: run.notes ? `Notes: ${run.notes}` : fallbackSub };
  if (run.state === "missed") return { value: "Missed", cls: "accent", sub: "The 6:00 AM run hasn't reported today" };
  return { value: `${okLabel} · ${t}`, cls: "pos", sub: run.notes || fallbackSub };
}

function popRow(label, line) {
  return h("div.popover-row",
    h("span.popover-label.cond", label),
    h("span.popover-value",
      h("span.cond", { class: line.cls }, line.value),
      line.sub ? h("span.popover-sub", line.sub) : null));
}

function popover() {
  const ws = state.status;
  const latest = (ws && ws.latest) || {};
  const rows = [];
  if (!ws || (!latest.morning && !latest.predict && !latest.manual)) {
    rows.push(h("div.popover-row", h("span.popover-sub",
      ws && ws.migration_pending
        ? "Run history appears here once the pipeline starts logging its runs to the database."
        : "Run history isn't available right now.")));
  } else {
    const morning = runLine(latest.morning, { fallbackSub: "Collect, features, Elo, retrain, settle" });
    const predict = latest.predict ? runLine(latest.predict, { fallbackSub: "About an hour before the first tip" })
      : latest.morning && latest.morning.state === "failed"
        ? { value: "Not run", cls: "muted", sub: "Waits for a good pipeline run" }
        : { value: "Not run yet", cls: "muted", sub: "About an hour before the first tip" };
    const smsRun = [latest.predict, latest.morning].find((r) => r && r.sms_sent !== null && r.sms_sent !== undefined);
    const sms = smsRun
      ? (smsRun.sms_sent ? { value: `Sent ${timeET(smsRun.finished_at) || ""}`, cls: "" } : { value: "Not sent", cls: "muted" })
      : { value: "—", cls: "muted" };
    rows.push(popRow("Morning pipeline", morning), popRow("Evening predictions", predict), popRow("SMS summary", sms));
    if (latest.manual) rows.push(popRow("Manual run", runLine(latest.manual, { fallbackSub: "Started from this computer" })));
  }
  const m = state.model;
  if (m && m.production_model) {
    const trained = m.trained_at ? `Trained ${dateTimeET(m.trained_at)}` : "";
    const acc = m.test && m.test.accuracy !== null ? `${pct(m.test.accuracy, 1)} test accuracy` : "";
    rows.push(popRow("Live model", { value: modelName(m.production_model), cls: "", sub: [trained, acc].filter(Boolean).join(" · ") }));
  } else {
    rows.push(popRow("Live model", { value: "Not published yet", cls: "muted", sub: "Appears after the next training run" }));
  }
  rows.push(popFoot(ws));
  return h("div.popover", { attrs: { id: "pipeline-popover", role: "dialog", "aria-label": "Pipeline status" } }, rows);
}

function popFoot(ws) {
  const controls = ws && ws.controls_allowed;
  if (!controls) {
    return h("div.popover-foot", "Runs automatically every morning and evening. Bets are paper bets sized with quarter-Kelly, capped at 5% of bankroll.");
  }
  if (state.runStartedAt || ws.running) {
    const started = state.runStartedAt || now().getTime();
    return h("div.popover-foot",
      h("span", `Started ${timeET(new Date(started).toISOString()) || ""} from this page.`, h("br"), "The page reloads its data when the run ends."),
      h("button.btn.cond", { attrs: { type: "button", disabled: true, id: "run-elapsed" } }, `Running · ${elapsed(now().getTime() - started)}`));
  }
  const failed = ["morning", "predict"].some((k) => ws.latest && ws.latest[k] && ws.latest[k].state === "failed");
  return h("div.popover-foot",
    h("span", failed ? "Tonight's picks are missing until a run succeeds." : "Runs pipeline, predictions and SMS now.", h("br"), "Shown only on this computer."),
    h("button.btn.btn--accent.cond", { attrs: { type: "button" }, on: { click: runNow } }, icon("play", 16), failed ? "Retry" : "Run now"));
}

export async function runNow() {
  try {
    const result = await api.runWorkflow();
    if (result && result.sample) {
      toast({ kind: "info", tag: "Sample", text: "Sample mode: nothing was started." });
      return;
    }
    state.runStartedAt = now().getTime();
    toast({ kind: "info", tag: "Pipeline", text: "Run started. The page reloads its data when it ends." });
    renderPill();
    watchRun();
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    const text = status === 409 ? "A run is already going."
      : status === 403 ? "Run now only works on the computer that runs the dashboard."
        : "The run didn't start. Try again in a moment.";
    toast({ kind: "miss", tag: "Pipeline", text });
  }
}

function watchRun() {
  window.clearInterval(state.poll);
  window.clearInterval(state.tick);
  state.tick = window.setInterval(() => {
    const el = document.getElementById("run-elapsed");
    if (el && state.runStartedAt) el.textContent = `Running · ${elapsed(now().getTime() - state.runStartedAt)}`;
  }, 1000);
  state.poll = window.setInterval(async () => {
    try {
      const status = await api.workflowStatus();
      state.status = status;
      if (!status.running) {
        window.clearInterval(state.poll);
        window.clearInterval(state.tick);
        state.runStartedAt = null;
        await loadPipeline();
        toast({ kind: "info", tag: "Pipeline", text: "The run finished. Data reloaded." });
        onRunFinished();
      }
    } catch {
      // keep polling; a transient error isn't the end of the run
    }
  }, 10000);
}

export function refreshPipeline() {
  loadPipeline();
}
