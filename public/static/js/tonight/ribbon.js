// Night ribbon (T12): once the glance board has scrolled above the viewport, a fixed ribbon carries
// the night's numbers until the season section reaches mid-screen. aria-hidden: it duplicates the board.
import { fmt } from '../format.js';
import { signCls } from '../board.js';
import { store, FEED_COPY } from '../state.js';

const $ = s => document.querySelector(s);
let ribbon, board, season, cells = [];
let past = false, before = true, on = false;

const enabled = () => {
  const phase = store.slate && (store.slate.offseason ? 'offseason' : store.slate.phase);
  return store.status === 'ready' && store.games.length > 0 && !['no_games', 'offseason', 'before_predictions', 'prediction_failed'].includes(phase);
};

function updateScrollPaddingTop() {
  if (on && ribbon) {
    const bottom = ribbon.offsetTop + ribbon.offsetHeight;
    document.documentElement.style.setProperty('scroll-padding-top', (bottom + 12) + 'px');
  } else {
    document.documentElement.style.removeProperty('scroll-padding-top');
  }
}

function apply() {
  const next = past && before && enabled();
  if (next === on) return;
  on = next;
  ribbon.classList.toggle('on', on);
  board.classList.toggle('docked', on);
  updateScrollPaddingTop();
}

export function mountRibbon() {
  ribbon = $('[data-ribbon]'); board = $('[data-testid=tape]'); season = document.getElementById('season');
  if (!ribbon || !board || !season) return;
  const dl = ribbon.querySelector('[data-ribbon-cells]');
  dl.textContent = '';
  cells = ['At risk', 'Settled', 'If it ended now', 'Bets'].map((label, i) => {
    const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label;
    div.append(dt, dd);
    div.style.setProperty('--k', String(i));
    dl.append(div);
    return dd;
  });
  if (!('IntersectionObserver' in window)) return;
  new IntersectionObserver(([e]) => { past = !e.isIntersecting && e.boundingClientRect.top < 0; apply(); }).observe(board);
  new IntersectionObserver(([e]) => { before = e.boundingClientRect.top > innerHeight * 0.5; apply(); }, { threshold: [0, 0.1, 0.5, 1] }).observe(season);
  let queued = false;
  const recheck = () => {
    queued = false;
    const b = season.getBoundingClientRect().top > innerHeight * 0.5;
    if (b !== before) { before = b; apply(); }
  };
  const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(recheck); } };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', () => {
    updateScrollPaddingTop();
    onScroll();
  }, { passive: true });

  // Focus trap: ensure focused elements don't land under the ribbon
  document.addEventListener('focusin', (e) => {
    if (!on) return;
    const target = e.target;
    const ribbonEl = $('[data-ribbon]');
    const drawer = $('.drawer');

    // Skip if focus is inside ribbon or drawer
    if (ribbonEl?.contains(target) || drawer?.contains(target)) return;

    const ribbonBottom = ribbonEl?.offsetTop + ribbonEl?.offsetHeight;
    if (ribbonBottom === undefined) return;

    const targetRect = target.getBoundingClientRect();
    const threshold = ribbonBottom + 12;

    if (targetRect.top < threshold) {
      // Scroll the element into view above the ribbon
      window.scrollBy({ top: targetRect.top - threshold, behavior: 'auto' });
    }
  });
}

function put(dd, text, cls) {
  if (dd.textContent !== text) dd.textContent = text;
  if (dd.className !== (cls || '')) dd.className = cls || '';
}

export function updateRibbon(s) {
  if (!ribbon || !cells.length) return;
  const title = ribbon.querySelector('[data-ribbon-title]');
  const t = store.isPast && store.slate ? fmt.date(store.slate.date, { month: 'short', day: 'numeric' }) : 'Tonight';
  if (title.textContent !== t) title.textContent = t;
  put(cells[0], fmt.money(s.staked));
  put(cells[1], fmt.money(s.settled, true), signCls(s.settled));
  put(cells[2], fmt.money(s.ifEnded, true), signCls(s.ifEnded));
  put(cells[3], s.betW + '–' + s.betL);
  let live = s.live ? s.live + ' live · ' + s.ahead + ' of ' + s.liveBets + ' bets ahead' : s.upcoming ? s.upcoming + ' to come' : 'All final';
  if (!store.isPast && (store.feed.status === 'delayed' || store.feed.status === 'down') && store.feed.asOf) live = FEED_COPY.delayed(store.feed.asOf);
  const liveEl = ribbon.querySelector('[data-ribbon-live]');
  if (liveEl.textContent !== live) liveEl.textContent = live;
  apply();
}
