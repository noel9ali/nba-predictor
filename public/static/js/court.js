// The 0–100% court: probability painted as territory from a baseline, a dashed market (or
// reference) line, and the orange hatch for the edge. Every position is written through the
// CSSOM (setProperty), never as a style="" attribute, so the strict CSP holds.
import { fmt, pct1 } from './format.js';
import { logo } from './logo.js';

const P = x => String(Math.round(x * 1000) / 1000) + '%';
const clamp01 = v => (v == null || Number.isNaN(v) ? null : Math.min(1, Math.max(0, v)));

export function courtGeometry({ p, m, fromLeft, gap = 'auto' }) {
  p = clamp01(p); m = clamp01(m);
  if (p == null) return null;
  const X = v => (fromLeft ? v * 100 : 100 - v * 100);
  const hasM = m != null;
  const paintTo = hasM && gap !== 'none' ? Math.min(p, m) : p;
  const g = { origin: fromLeft ? 'left' : 'right', paintWidth: paintTo * 100, edgeLeft: X(p), mkLeft: hasM ? X(m) : null, gap: null };
  if (hasM && gap === 'auto' && p !== m) {
    g.gap = { kind: p > m ? 'hat' : 'short', left: Math.min(X(m), X(p)), width: Math.abs(X(p) - X(m)) };
  }
  return g;
}

function span(cls, text) {
  const s = document.createElement('span');
  s.className = cls;
  if (text != null) s.textContent = text;
  return s;
}
const setLeft = (el, pct) => el.style.setProperty('left', P(pct));
const tagLeft = (el, pct, slack) => el.style.setProperty('left', 'clamp(' + slack + 'px, ' + P(pct) + ', calc(100% - ' + slack + 'px))');

// Paint, gap and the two lines into a court element, in paint order.
function marks(court, g, { hook = false } = {}) {
  const paint = span('seg paint');
  paint.style.setProperty('--o', g.origin);
  paint.style.setProperty(g.origin, '0%');
  paint.style.setProperty('width', P(g.paintWidth));
  court.append(paint);
  if (g.gap) {
    const s = span('seg ' + (g.gap.kind === 'hat' ? 'hat' + (hook ? ' edgefill' : '') : 'short'));
    s.style.setProperty('--o', g.origin);
    setLeft(s, g.gap.left);
    s.style.setProperty('width', P(g.gap.width));
    court.append(s);
  }
  const edge = span('edge-line' + (hook ? ' edgeline' : ''));
  setLeft(edge, g.edgeLeft);
  court.append(edge);
  if (g.mkLeft != null) {
    const mk = span('mk' + (hook ? ' mline' : ''));
    setLeft(mk, g.mkLeft);
    court.append(mk);
  }
}

function lines(court, { cc = true } = {}) {
  court.append(span('key l'), span('key r'));
  if (cc) court.append(span('cc'));
}

// ---------- glance (Tonight rows) ----------
export function glanceCourt(g, rowIndex) {
  const court = document.createElement('div');
  court.className = 'court-strip court-strip--glance';
  court.setAttribute('aria-hidden', 'true');
  lines(court);
  const ps = g.pick == null ? null : g.pick === g.home.tricode ? 'home' : g.pick === g.away.tricode ? 'away' : null;
  const geo = ps ? courtGeometry({ p: g.pick_prob, m: g.implied_prob, fromLeft: ps === 'away' }) : null;
  if (geo) {
    marks(court, geo, { hook: true });
    if (geo.mkLeft != null) {
      const t = span('tag t', 'Mkt ' + fmt.pct(clamp01(g.implied_prob), 0));
      tagLeft(t, geo.mkLeft, 40);
      court.append(t);
    }
    const n = Math.round(clamp01(g.pick_prob) * 100);
    const b = span('tag b', 'Model ');
    const c = span('', String(n));
    c.dataset.count = String(n);
    b.append(c, document.createTextNode('%'));
    tagLeft(b, geo.edgeLeft, 40);
    court.append(b);
  }
  const tri = (side, cls) => {
    const t = span('tri ' + cls);
    const disc = span('disc');
    disc.append(logo(g[side].tricode, 'm-logo', 22));
    t.append(disc, document.createTextNode(g[side].tricode));
    if (geo && ps === side) { const ball = span('ball'); ball.setAttribute('aria-hidden', 'true'); t.append(ball); }
    return t;
  };
  court.append(tri('away', 'l'), tri('home', 'r'));
  return court;
}

// T4: the model % counts up from 0 (motion only; the final text is always the right number).
export function countUp(rowEl) {
  const i = parseFloat(getComputedStyle(rowEl).getPropertyValue('--i')) || 0;
  rowEl.querySelectorAll('[data-count]').forEach(n => {
    const to = Number(n.dataset.count), t0 = performance.now() + i * 90 + 700;
    n.textContent = '0';
    const step = t => {
      const k = Math.min(1, Math.max(0, (t - t0) / 600));
      n.textContent = String(Math.round(to * (k < 1 ? 1 - Math.pow(1 - k, 3) : 1)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// ---------- claim (Model hero) ----------
// base/model are fractions already rounded to one decimal of a percent (0.55, 0.681).
export function claimCourt({ base, model }) {
  const court = document.createElement('div');
  court.className = 'court-strip court-strip--claim';
  court.dataset.court = '';
  court.setAttribute('role', 'img');
  lines(court);
  const add = span('seg hat add'); add.dataset.add = '';
  court.append(span('seg paint'), add, span('mk'));
  const edge = span('edge-line'); edge.dataset.edge = '';
  court.append(edge);
  updateClaimCourt(court, { base, model });
  return court;
}
export function updateClaimCourt(court, { base, model }) {
  const baseP = Math.round(base * 1000) / 10, accP = Math.round(model * 1000) / 10;
  const gainP = (Math.round(accP * 10) - Math.round(baseP * 10)) / 10;
  court.style.setProperty('--base', P(baseP));
  court.style.setProperty('--model', P(accP));
  court.style.setProperty('--gain', P(Math.max(0, gainP)));
  court.classList.toggle('no-gain', gainP <= 0);
  court.classList.toggle('high', accP > 88);
  court.querySelectorAll('.tag, .side').forEach(x => x.remove());
  const baseTag = span('tag b base-tag', 'Home rule ' + baseP.toFixed(1) + '%');
  const addTag = span('tag t add-tag', gainP > 0 ? '+' + gainP.toFixed(1) + ' pts' : gainP < 0 ? '−' + Math.abs(gainP).toFixed(1) + ' pts' : '0.0 pts');
  const val = span('tag b val-tag', baseP.toFixed(1) + '%'); val.dataset.val = '';
  court.append(baseTag, addTag, val, span('side l', '0%'), span('side r', '100%'));
  return { baseP, accP, gainP };
}

// ---------- compare (Model chapter 1) ----------
export function compareCourt(a) {
  const court = document.createElement('div');
  court.className = 'court-strip court-strip--compare';
  court.setAttribute('role', 'img');
  court.dataset.strip = '';
  updateCompareCourt(court, a);
  return court;
}
export function updateCompareCourt(court, { subject, reference, ariaLabel }) {
  court.textContent = '';
  court.setAttribute('aria-label', ariaLabel);
  const geo = courtGeometry({ p: subject.value, m: reference.value, fromLeft: true, gap: 'none' });
  marks(court, geo);
  const subLower = subject.value <= reference.value;
  const sb = span('tag b ' + (subLower ? 'lo' : 'hi'), subject.label + ' ' + pct1(subject.value) + '%');
  setLeft(sb, subject.value * 100);
  const rt = span('tag t ' + (subLower ? 'hi' : 'lo'), reference.label + ' ' + pct1(reference.value) + '%');
  setLeft(rt, reference.value * 100);
  court.append(sb, rt);
}

// ---------- step (Model walkthrough 4 and 5) ----------
export function stepCourt({ pickHome, p, ref, modelText, gap, labels, ariaLabel }) {
  const court = document.createElement('div');
  court.className = 'court-strip court-strip--step';
  court.setAttribute('role', 'img');
  court.setAttribute('aria-label', ariaLabel);
  lines(court, { cc: false });
  const geo = courtGeometry({ p, m: ref ? ref.value : null, fromLeft: !pickHome, gap });
  if (geo) {
    marks(court, geo);
    if (ref && geo.mkLeft != null) { const t = span('tag t', ref.text); tagLeft(t, geo.mkLeft, 56); court.append(t); }
    const b = span('tag b', modelText); tagLeft(b, geo.edgeLeft, 56); court.append(b);
  }
  court.append(span('lbl', labels.left), span('lbl r', labels.right));
  return court;
}
