// DOM building without HTML strings. Every piece of API data reaches the page as a text
// node (textContent) or an attribute value, never as markup. CSP (script-src 'self';
// style-src 'self') also rules out inline handlers and style attributes, so this helper
// refuses them outright: listeners go through addEventListener, and geometry through the
// CSSOM (el.style.width = ...), which the CSP allows.

const SVG_NS = "http://www.w3.org/2000/svg";
const FORBIDDEN_ATTR = /^(on|style$|srcdoc$|formaction$)/i;
const SAFE_URL = /^(#|\/(?!\/)|\?)/; // same-page anchors, same-origin paths and query strings

function setAttrs(el, attrs) {
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (FORBIDDEN_ATTR.test(name)) throw new Error(`attribute not allowed: ${name}`);
    if ((name === "href" || name === "src" || name === "action") && !SAFE_URL.test(String(value))) {
      throw new Error(`unsafe URL for ${name}`);
    }
    el.setAttribute(name, value === true ? "" : String(value));
  }
}

function append(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(el, child);
    else if (child instanceof Node) el.appendChild(child);
    else el.appendChild(document.createTextNode(String(child)));
  }
}

// h("div.card.card--live", {attrs, on, style, dataset}, ...children)
// The first argument may carry classes after dots: "span.cond.muted".
export function h(spec, props = {}, ...children) {
  if (props === null || typeof props !== "object" || props instanceof Node || Array.isArray(props)) {
    children.unshift(props);
    props = {};
  }
  const [tag, ...classes] = spec.split(".");
  const el = document.createElement(tag || "div");
  if (classes.length) el.classList.add(...classes);
  applyProps(el, props);
  append(el, children);
  return el;
}

function applyProps(el, props) {
  const { class: cls, attrs, on, style, dataset, text } = props;
  if (cls) {
    for (const c of [].concat(cls)) {
      if (c) el.classList.add(...String(c).split(" ").filter(Boolean));
    }
  }
  if (attrs) setAttrs(el, attrs);
  if (dataset) for (const [k, v] of Object.entries(dataset)) if (v !== undefined && v !== null) el.dataset[k] = String(v);
  if (style) for (const [k, v] of Object.entries(style)) el.style.setProperty(k, String(v));
  if (on) for (const [event, fn] of Object.entries(on)) el.addEventListener(event, fn);
  if (text !== undefined && text !== null) el.textContent = String(text);
}

export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  const { class: cls, ...rest } = attrs;
  if (cls) el.setAttribute("class", cls);
  setAttrs(el, rest);
  append(el, children);
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function mount(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

export function $(selector, root = document) {
  return root.querySelector(selector);
}

// Stroke icons (paths from the canvas boards). aria-hidden: the button carries the label.
const ICONS = {
  lock: ["rect:5,11,14,10,1", "M8 11V7a4 4 0 0 1 8 0v4"],
  chevronDown: ["M6 9l6 6 6-6"],
  chevronRight: ["M9 6l6 6-6 6"],
  chevronLeft: ["M15 6l-6 6 6 6"],
  calendar: ["rect:4,5,16,16,1", "M4 10h16M9 3v4M15 3v4"],
  info: ["circle:12,12,9", "M12 11v6M12 7.5v.5"],
  refresh: ["M20 12a8 8 0 1 1-2.3-5.6", "M20 4v5h-5"],
  warn: ["M12 4l9 16H3z", "M12 10v4M12 17v.5"],
  close: ["M6 6l12 12M18 6L6 18"],
  play: ["fill:M7 5v14l12-7z"],
};

export function icon(name, size = 16, strokeWidth = 2.4) {
  const el = s("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", "stroke-width": strokeWidth, "aria-hidden": "true", focusable: "false" });
  for (const part of ICONS[name] || []) {
    if (part.startsWith("rect:")) {
      const [x, y, w, hgt, r] = part.slice(5).split(",");
      el.appendChild(s("rect", { x, y, width: w, height: hgt, rx: r }));
    } else if (part.startsWith("circle:")) {
      const [cx, cy, r] = part.slice(7).split(",");
      el.appendChild(s("circle", { cx, cy, r }));
    } else if (part.startsWith("fill:")) {
      el.appendChild(s("path", { d: part.slice(5), fill: "currentColor", stroke: "none" }));
    } else {
      el.appendChild(s("path", { d: part }));
    }
  }
  return el;
}

export function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
