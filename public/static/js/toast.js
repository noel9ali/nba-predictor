// Toasts land in #toasts, a role="status" live region, so screen readers announce them.
import { h, icon } from "./dom.js";

const MAX = 3;
const LIFETIME_MS = 9000;

// toast({ kind: "live"|"hit"|"miss"|"info", tag: "Tip-off", strong: "MIA @ ORL", text: "is live." })
export function toast({ kind = "info", tag = "", strong = "", text = "" }) {
  const region = document.getElementById("toasts");
  if (!region) return;
  const item = h(`div.toast.toast--${kind}`,
    tag ? h("span.toast-tag.cond", tag) : null,
    h("span.toast-text", strong ? h("strong", strong) : null, strong && text ? " " : "", text),
    h("button.toast-close", { attrs: { type: "button", "aria-label": "Dismiss notification" },
      on: { click: () => item.remove() } }, icon("close", 16, 2.4)));
  region.appendChild(item);
  while (region.children.length > MAX) region.firstElementChild.remove();
  window.setTimeout(() => item.remove(), LIFETIME_MS);
}
