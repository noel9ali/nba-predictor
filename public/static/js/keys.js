// The page's only keydown listener, bound to document once (a listener on the dialog itself
// stops firing when focus lands outside it; FE-F20). Esc closes the most recently opened
// thing first (explainer, popover, then the drawer); Tab is trapped inside the open dialog.

const stack = [];
let trapRoot = null;

export const escapeStack = {
  // Returns a function that removes the entry (call it when the thing closes by itself).
  push(onEscape) {
    const entry = { onEscape };
    stack.push(entry);
    return () => {
      const i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
    };
  },
};

export function trapFocus(root) {
  trapRoot = root;
}

export function releaseFocus(root) {
  if (trapRoot === root) trapRoot = null;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
}

// Arrow-key handlers for focused widgets (the season timeline) register here.
const arrowHandlers = new Set();
export function onArrowKeys(fn) {
  arrowHandlers.add(fn);
  return () => arrowHandlers.delete(fn);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && stack.length) {
    const entry = stack.pop();
    e.preventDefault();
    entry.onEscape();
    return;
  }
  if (e.key === "Tab" && trapRoot) {
    const items = focusables(trapRoot);
    if (!items.length) {
      e.preventDefault();
      trapRoot.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (!trapRoot.contains(active)) {
      e.preventDefault();
      (e.shiftKey ? last : first).focus();
    } else if (e.shiftKey && (active === first || active === trapRoot)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
    return;
  }
  for (const fn of arrowHandlers) {
    if (fn(e)) {
      e.preventDefault();
      return;
    }
  }
});
