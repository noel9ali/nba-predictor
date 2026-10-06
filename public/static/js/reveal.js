// Scroll-reveal helpers. Hidden "before" states only exist under html.js (set by gate.js when
// IntersectionObserver exists and reduced motion is off), so without motion every callback
// fires at once and nothing is ever hidden.

export const motionOn = () => document.documentElement.classList.contains('js');
export const reduceMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
export const hasIO = () => 'IntersectionObserver' in window;

// One-shot: cb(el) the first time el meets opts.threshold, then stop watching.
export function watch(el, cb, opts) {
  if (!el) return;
  if (!motionOn() || !hasIO()) { cb(el); return; }
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { io.unobserve(e.target); cb(e.target); }
  }), opts || { threshold: 0.25 });
  io.observe(el);
}

// Model page: every [data-reveal] gains .in once it is 30% visible (M5–M8). Without motion
// they get .in immediately so tests that look for .in pass under reduced motion too.
let revealIO = null;
export function observeReveals(root = document) {
  const els = [...root.querySelectorAll('[data-reveal]:not(.in)')];
  if (!motionOn() || !hasIO()) { els.forEach(el => el.classList.add('in')); return; }
  if (!revealIO) {
    revealIO = new IntersectionObserver(entries => entries.forEach(e => {
      if (e.isIntersecting) { revealIO.unobserve(e.target); e.target.classList.add('in'); }
    }), { threshold: 0.3 });
  }
  els.forEach(el => revealIO.observe(el));
}

// One passive scroll listener for the page; handlers run once per animation frame.
const scrollFns = new Set();
let queued = false;
function flush() { queued = false; scrollFns.forEach(fn => { try { fn(); } catch (e) { console.warn(e); } }); }
function onScroll() { if (!queued) { queued = true; requestAnimationFrame(flush); } }
export function onScrollFrame(fn) {
  if (!scrollFns.size) {
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onScroll, { passive: true });
  }
  scrollFns.add(fn);
  return () => scrollFns.delete(fn);
}

// Restart a CSS animation class on an element.
export function replay(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}
