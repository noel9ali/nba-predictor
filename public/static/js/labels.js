// Pure helpers for fitting chart labels and tooltips; no DOM, so the unit tests can run them.

// Centre x for a box of width w that must stay inside [0, hostW]. A box wider than the host is centred.
export function clampCenter(x, w, hostW) {
  const half = w / 2;
  if (half * 2 >= hostW) return hostW / 2;
  return Math.min(Math.max(x, half), hostW - half);
}

// Width of a label in the 12px mono face (about 7.3px a character).
export const labelWidth = text => String(text).length * 7.3;

// x and text-anchor for a label centred on cx that must stay between minX and maxX.
export function fitAnchor(cx, w, minX, maxX) {
  if (cx + w / 2 > maxX) return { x: maxX, anchor: 'end' };
  if (cx - w / 2 < minX) return { x: minX, anchor: 'start' };
  return { x: cx, anchor: 'middle' };
}

// Vertical centre for a label so no rule in `rules` passes through it. A label that straddles a rule
// moves to the nearer clear side, `gap` away from the rule.
export function nudgeClear(center, rules, gap = 9) {
  let c = center;
  for (const r of rules) if (Math.abs(c - r) < gap) c = c >= r ? r + gap : r - gap;
  return c;
}
