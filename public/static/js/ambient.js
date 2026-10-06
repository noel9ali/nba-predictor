// Ambient arena (A4 second half): the faint court drifts at -0.06 x scrollY. The drawing, the
// lamps and the sheen are pure CSS; reduced motion leaves the court still.

export function initAmbient() {
  const court = document.querySelector('.ambient .court-bg');
  if (!court || !window.matchMedia) return;
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (mq.matches) return;
  let queued = false;
  const update = () => { court.style.setProperty('--py', (-window.scrollY * 0.06).toFixed(1) + 'px'); queued = false; };
  const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
  addEventListener('scroll', onScroll, { passive: true });
  update();
  const stop = e => {
    if (!e.matches) return;
    removeEventListener('scroll', onScroll);
    court.style.removeProperty('--py');
  };
  if (mq.addEventListener) mq.addEventListener('change', stop);
}
