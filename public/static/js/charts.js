// Performance charts (Perf-Final board), built as SVG nodes (no markup strings):
// - the season timeline: bankroll line over nightly P/L columns on the same date axis (two
//   charts, never one chart with two axes), with a shared crosshair driven by the mouse or
//   the arrow keys; Enter or a click opens that night on Games;
// - the calibration mini-chart (actual vs predicted by probability bucket).
import { h, s } from "./dom.js";
import { dayShort, isNum, money, pct, record, signedMoney, weekday } from "./format.js";
import { onArrowKeys } from "./keys.js";

const W = 1260;
const X0 = 64;
const X1 = 1150;

function dayNum(date) {
  return Date.parse(`${date}T12:00:00Z`) / 86400000;
}

function niceStep(range, target = 4) {
  const raw = range / target;
  for (const step of [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000]) if (step >= raw) return step;
  return 5000;
}

function upper(text) {
  return String(text).toUpperCase();
}

// points: [{date, bankroll, nightly_pl, bets, picks, pending}], first = the start point.
export function seasonTimeline(points, { start, drawdown, onOpen }) {
  const first = dayNum(points[0].date);
  const last = dayNum(points[points.length - 1].date);
  const span = Math.max(1, last - first);
  const xOf = (date) => X0 + ((dayNum(date) - first) / span) * (X1 - X0);

  // ---------------------------------------------------------------- bankroll chart
  const H1 = 320;
  const top = 34;
  const bottom = 286;
  const values = points.map((p) => p.bankroll).concat([start]);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const step = niceStep(Math.max(hi - lo, 50));
  const vMin = Math.floor((lo - step * 0.2) / step) * step;
  const vMax = Math.ceil((hi + step * 0.2) / step) * step;
  const yOf = (v) => bottom - ((v - vMin) / (vMax - vMin)) * (bottom - top);

  const bank = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H1}`, role: "img",
    "aria-label": bankrollSummary(points, start, drawdown) });
  if (drawdown && drawdown.amount > 0 && drawdown.peak_date && drawdown.trough_date) {
    const xa = xOf(drawdown.peak_date);
    const xb = xOf(drawdown.trough_date);
    bank.append(
      s("rect", { class: "ch-dd-rect", x: xa, y: top, width: Math.max(2, xb - xa), height: bottom - top }),
      s("line", { class: "ch-dd", x1: xa, x2: xb, y1: 24, y2: 24 }),
      s("line", { class: "ch-dd", x1: xa, x2: xa, y1: 18, y2: 30 }),
      s("line", { class: "ch-dd", x1: xb, x2: xb, y1: 18, y2: 30 }),
      s("text", { class: "ch-dd-label", x: (xa + xb) / 2, y: 16, "text-anchor": "middle", "font-size": 15 },
        `MAX DRAWDOWN ${upper(signedMoney(-drawdown.amount))}`));
  }
  for (let v = vMin; v <= vMax + 0.001; v += step) {
    const y = yOf(v);
    bank.append(s("line", { class: "ch-grid", x1: X0, x2: X1, y1: y, y2: y }),
      s("text", { class: "ch-label", x: X0 - 10, y: y + 5, "text-anchor": "end", "font-size": 15 }, money(v).replace(".00", "")));
  }
  const ys = yOf(start);
  bank.append(s("line", { class: "ch-start", x1: X0, x2: X1, y1: ys, y2: ys }),
    s("text", { class: "ch-label", x: X1 + 8, y: ys + 5, "font-size": 15 }, `START ${money(start).replace(".00", "")}`));
  const coords = points.map((p) => `${xOf(p.date).toFixed(1)},${yOf(p.bankroll).toFixed(1)}`);
  bank.append(
    s("polygon", { class: "ch-area", points: `${xOf(points[0].date).toFixed(1)},${ys.toFixed(1)} ${coords.join(" ")} ${xOf(points[points.length - 1].date).toFixed(1)},${ys.toFixed(1)}` }),
    s("polyline", { class: "ch-line", points: coords.join(" ") }));
  const peak = points.reduce((a, b) => (b.bankroll > a.bankroll ? b : a), points[0]);
  const end = points[points.length - 1];
  if (peak !== end && peak.bankroll > start) {
    bank.append(s("circle", { class: "ch-dot", cx: xOf(peak.date), cy: yOf(peak.bankroll), r: 5 }),
      s("text", { class: "ch-label", x: xOf(peak.date), y: yOf(peak.bankroll) - 12, "text-anchor": "middle", "font-size": 14 },
        `PEAK ${money(peak.bankroll)}`));
  }
  bank.append(s("circle", { class: "ch-dot", cx: xOf(end.date), cy: yOf(end.bankroll), r: 6 }),
    s("text", { class: "ch-end-label", x: X1 + 8, y: yOf(end.bankroll) + 5, "font-size": 16 }, money(end.bankroll)));
  for (const d of axisDates(points)) {
    bank.append(s("text", { class: "ch-label", x: xOf(d), y: 312, "text-anchor": "middle", "font-size": 14 }, upper(dayShort(d))));
  }

  // ---------------------------------------------------------------- nightly P/L chart
  const H2 = 140;
  const zero = 65;
  const maxAbs = Math.max(20, ...points.map((p) => Math.abs(p.nightly_pl || 0)));
  const plStep = niceStep(maxAbs, 2);
  const plMax = Math.ceil(maxAbs / plStep) * plStep;
  const yPl = (v) => zero - (v / plMax) * 55;
  const nightly = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H2}`, role: "img",
    "aria-label": `Nightly P/L, ${dayShort(points[1] ? points[1].date : points[0].date)} to ${dayShort(end.date)}` });
  for (const v of [-plMax, -plMax / 2, plMax / 2, plMax]) {
    nightly.append(s("line", { class: "ch-grid", x1: X0, x2: X1, y1: yPl(v), y2: yPl(v) }),
      s("text", { class: "ch-label", x: X0 - 10, y: yPl(v) + 5, "text-anchor": "end", "font-size": 14 }, signedMoney(v).replace(".00", "")));
  }
  nightly.append(s("line", { class: "ch-zero", x1: X0, x2: X1, y1: zero, y2: zero }),
    s("text", { class: "ch-label", x: X0 - 10, y: zero + 5, "text-anchor": "end", "font-size": 14 }, "$0"));
  const barW = Math.max(3, Math.min(16, ((X1 - X0) / Math.max(1, points.length)) * 0.6));
  for (const p of points.slice(1)) {
    const v = p.nightly_pl || 0;
    if (Math.abs(v) < 0.005) continue;
    const y = Math.min(yPl(v), zero);
    nightly.append(s("rect", { class: v > 0 ? "bar-win" : "bar-loss", x: xOf(p.date) - barW / 2, y,
      width: barW, height: Math.max(1, Math.abs(yPl(v) - zero)) }));
  }

  // ---------------------------------------------------------------- crosshair
  const xhairBank = s("line", { class: "xhair", x1: 0, x2: 0, y1: top, y2: bottom, visibility: "hidden" });
  const xhairNight = s("line", { class: "xhair", x1: 0, x2: 0, y1: 10, y2: 120, visibility: "hidden" });
  const marker = s("circle", { class: "ch-dot ch-dot--hover", r: 5, cx: 0, cy: 0, visibility: "hidden" });
  const tip = s("g", { class: "tooltip-box", visibility: "hidden" });
  const tipBg = s("rect", { class: "tt-bg", width: 300, height: 104 });
  const tipLines = [0, 1, 2, 3].map((i) => s("text", { class: i === 0 ? "tt-title" : "tt-text", x: 14, y: 26 + i * 22, "font-size": i === 0 ? 17 : 15 }));
  tip.append(tipBg, ...tipLines);
  bank.append(xhairBank, marker, tip);
  nightly.append(xhairNight);

  const live = h("p.sr-only", { attrs: { "aria-live": "polite" } });
  let index = -1;
  const nights = points.slice(1);

  function show(i) {
    if (i < 0 || i >= nights.length) return;
    index = i;
    const p = nights[i];
    const x = xOf(p.date);
    for (const line of [xhairBank, xhairNight]) {
      line.setAttribute("x1", x);
      line.setAttribute("x2", x);
      line.setAttribute("visibility", "visible");
    }
    marker.setAttribute("cx", x);
    marker.setAttribute("cy", yOf(p.bankroll));
    marker.setAttribute("visibility", "visible");
    const lines = [
      upper(`${weekday(p.date)}, ${dayShort(p.date)}`),
      `BANKROLL ${money(p.bankroll)}`,
      upper(`Night ${signedMoney(p.nightly_pl)} · bets ${record(p.bets)}`),
      upper(`Picks ${record(p.picks)}${p.pending ? ` · ${p.pending} pending` : ""} · click to open night`),
    ];
    lines.forEach((text, j) => { tipLines[j].textContent = text; });
    const tx = x + 316 > X1 + 100 ? x - 316 : x + 16;
    const ty = Math.max(38, Math.min(bottom - 104, yOf(p.bankroll) - 52));
    tip.setAttribute("transform", `translate(${tx.toFixed(1)},${ty.toFixed(1)})`);
    tip.setAttribute("visibility", "visible");
    live.textContent = `${dayShort(p.date)}: bankroll ${money(p.bankroll)}, night ${signedMoney(p.nightly_pl)}, bets ${record(p.bets)}, picks ${record(p.picks)}.`;
  }

  function hide() {
    for (const el of [xhairBank, xhairNight, marker, tip]) el.setAttribute("visibility", "hidden");
  }

  function nearest(evt, svg) {
    const rect = svg.getBoundingClientRect();
    const vx = ((evt.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestD = Infinity;
    nights.forEach((p, i) => {
      const d = Math.abs(xOf(p.date) - vx);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }

  for (const svg of [bank, nightly]) {
    const hit = s("rect", { class: "hit-area", x: X0 - 12, y: 0, width: X1 - X0 + 24, height: svg === bank ? H1 : H2 });
    svg.append(hit);
    hit.addEventListener("pointermove", (e) => show(nearest(e, svg)));
    hit.addEventListener("click", (e) => {
      const i = nearest(e, svg);
      if (nights[i]) onOpen(nights[i].date);
    });
  }

  const wrap = h("div.chart-wrap", {
    attrs: { tabindex: "0", role: "group",
      "aria-label": "Season timeline. Left and right arrow keys move through nights; Enter opens the night on Games." },
  });
  wrap.addEventListener("pointerleave", () => {
    if (document.activeElement !== wrap) hide();
  });
  wrap.addEventListener("focus", () => show(index >= 0 ? index : nights.length - 1));
  wrap.addEventListener("blur", hide);
  const unbind = onArrowKeys((e) => {
    if (document.activeElement !== wrap) return false;
    const at = index >= 0 ? index : nights.length; // nothing selected yet: start from the latest night
    if (e.key === "ArrowLeft") show(Math.max(0, at - 1));
    else if (e.key === "ArrowRight") show(Math.min(nights.length - 1, index >= 0 ? at + 1 : nights.length - 1));
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(nights.length - 1);
    else if (e.key === "Enter" && nights[index]) onOpen(nights[index].date);
    else return false;
    return true;
  });
  wrap.append(h("span.chart-label.chart-label--top.cond", "Bankroll"), bank,
    h("span.chart-label.cond", "Nightly P/L"), nightly, live);
  return { el: wrap, dispose: unbind };
}

function bankrollSummary(points, start, drawdown) {
  const end = points[points.length - 1];
  const peak = points.reduce((a, b) => (b.bankroll > a.bankroll ? b : a), points[0]);
  let text = `Bankroll by night, ${money(start)} start to ${money(end.bankroll)}; peak ${money(peak.bankroll)} on ${dayShort(peak.date)}`;
  if (drawdown && drawdown.amount > 0) text += `; max drawdown ${money(drawdown.amount)} to ${dayShort(drawdown.trough_date)}`;
  return text;
}

function axisDates(points) {
  const first = points[0].date;
  const last = points[points.length - 1].date;
  const out = [first];
  for (const p of points) {
    const day = Number(p.date.slice(8, 10));
    if ([1, 8, 15, 22].includes(day) && dayNum(p.date) - dayNum(first) >= 4 && dayNum(last) - dayNum(p.date) >= 4) out.push(p.date);
  }
  out.push(last);
  // Thin to at most 6 labels.
  if (out.length > 6) {
    const keep = [out[0]];
    const inner = out.slice(1, -1);
    const every = Math.ceil(inner.length / 4);
    inner.forEach((d, i) => { if (i % every === 0) keep.push(d); });
    keep.push(out[out.length - 1]);
    return keep;
  }
  return out;
}

// ------------------------------------------------------------------ calibration
export function calibrationChart(buckets) {
  const size = 220;
  const left = 34;
  const right = 210;
  const topY = 10;
  const bottomY = 186;
  const hiVal = Math.max(0.8, ...buckets.map((b) => Math.max(b.predicted, b.actual)));
  const lo = 0.5;
  const hi = Math.min(1, Math.ceil(hiVal * 10) / 10);
  const x = (v) => left + ((v - lo) / (hi - lo)) * (right - left);
  const y = (v) => bottomY - ((Math.max(lo, v) - lo) / (hi - lo)) * (bottomY - topY);
  const svg = s("svg", { class: "chart chart--calib", viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img",
    "aria-label": `Calibration: ${buckets.map((b) => `predicted ${pct(b.predicted)} won ${pct(b.actual)} of ${b.n}`).join("; ")}` });
  for (let v = lo; v <= hi + 0.001; v += 0.1) {
    svg.append(s("line", { class: "ch-grid", x1: left, x2: right, y1: y(v), y2: y(v) }),
      s("text", { class: "ch-label", x: left - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 12 }, pct(v)));
  }
  svg.append(s("line", { class: "ch-start", x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi) }));
  const pts = buckets.filter((b) => isNum(b.predicted) && isNum(b.actual));
  if (pts.length) {
    svg.append(s("polyline", { class: "ch-line", points: pts.map((b) => `${x(b.predicted).toFixed(1)},${y(b.actual).toFixed(1)}`).join(" ") }));
    for (const b of pts) svg.append(s("circle", { class: "ch-dot", cx: x(b.predicted), cy: y(b.actual), r: 4.5 }));
  }
  svg.append(s("text", { class: "ch-label", x: right, y: 214, "text-anchor": "end", "font-size": 12 }, "PREDICTED →"));
  return svg;
}
