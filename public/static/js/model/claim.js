// Model hero (M1/M2): one pinned court. At 30% of the pinned range the hatched gain pops out of the
// home-team baseline and the h1 swaps to the claim. Reversible; reduced motion switches instantly.
import { fmtDate, fmtInt, TZ } from '../format.js';
import { claimCourt, updateClaimCourt } from '../court.js';
import { onScrollFrame, replay } from '../reveal.js';

const $ = (s, r = document) => r.querySelector(s);
let pin, head, scrolly, court, txt = null, wired = false;

export function etDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: TZ });
}

function buildTitle(h1, k) {
  h1.textContent = '';
  const w = document.createElement('span');
  w.className = 'w';
  if (k === 'model') {
    const n = document.createElement('span');
    n.className = 'n';
    n.textContent = txt.acc + '%';
    w.append('The model is right on ', n, ' of games it never saw.');
  } else w.textContent = 'Home-team rule';
  h1.append(w);
}
function fill(root, k) {
  $('[data-step]', root).textContent = k === 'model' ? '2 of 2 · what the model adds' : '1 of 2 · the bar to beat';
  root.querySelectorAll('.pin__k i').forEach((i, n) => i.classList.toggle('on', n === 0 || k === 'model'));
  buildTitle($('.pin__t', root), k);
  $('.pin__x', root).textContent = k === 'model' ? txt.modelX : txt.baseX;
}

function setState(k, animate = true) {
  if (pin.dataset.state === k && txt.rendered) return;
  const first = !txt.rendered;
  txt.rendered = true;
  pin.dataset.state = k;
  fill(head, k);
  court.setAttribute('aria-label', k === 'model' ? txt.ariaModel : txt.ariaBase);
  $('[data-val]', court).textContent = (k === 'model' ? txt.acc : txt.base) + '%';
  if (animate && !first) { replay($('.pin__t', head), 'swap'); replay($('.pin__x', head), 'swap'); }
}

// M2: reserve the taller heading so the court never jumps when the text swaps.
function sizeHead() {
  if (!txt) return;
  const clone = head.cloneNode(true);
  clone.removeAttribute('aria-live');
  clone.querySelectorAll('[id]').forEach(e => e.removeAttribute('id'));
  clone.setAttribute('aria-hidden', 'true');
  for (const [p, v] of [['position', 'absolute'], ['visibility', 'hidden'], ['pointer-events', 'none'], ['left', '0'], ['top', '0'], ['width', head.offsetWidth + 'px'], ['min-height', '0']]) clone.style.setProperty(p, v);
  pin.append(clone);
  let max = 0;
  for (const k of ['base', 'model']) { fill(clone, k); max = Math.max(max, clone.offsetHeight); }
  clone.remove();
  head.style.setProperty('min-height', max + 'px');
}

function onScroll(animate = true) {
  const r = scrolly.getBoundingClientRect(), range = r.height - innerHeight;
  const p = range > 0 ? Math.min(1, Math.max(0, -r.top / range)) : 1;
  setState(p > 0.3 ? "model" : "base", animate);
}

export function initClaim(model) {
  pin = $('.claim .pin'); head = $('.pin__head', pin); scrolly = $('[data-scrolly]');
  const kick = $('[data-kicker]');
  const parts = ['The model'];
  if (model && model.production_model) {
    parts.push(model.production_model);
  } else if (model) {
    parts.push('Production model unavailable');
  }
  if (model && model.trained_at && !Number.isNaN(Date.parse(model.trained_at))) parts.push('retrained ' + etDate(model.trained_at));
  kick.textContent = parts.join(' · ');
  const T = model && model.test;
  if (!T || T.accuracy == null || T.baseline_home_win_rate == null) {
    scrolly.classList.add('flat');
    pin.querySelectorAll('.legend, .scroll-cue, .pin__k').forEach(e => { e.hidden = true; });
    $('.pin__t', head).textContent = 'The model behind the picks';
    $('.pin__x', head).textContent = "The model's test results aren't available right now.";
    return;
  }
  const slot = $('[data-court-slot]');
  slot.textContent = '';
  court = claimCourt({ base: 0, model: 0 });
  slot.append(court);
  const { baseP, accP, gainP } = updateClaimCourt(court, { base: T.baseline_home_win_rate, model: T.accuracy });
  const tr = model.training || {};
  const start = tr.cutoff_date || model.cutoff_date, end = tr.last_game_date;
  const games = T.games != null ? 'Graded on ' + fmtInt(T.games) + ' test games held back from training' : 'Graded on games held back from training';
  const when = start && end ? ', ' + fmtDate(start) + ' to ' + fmtDate(end) : start ? ', since ' + fmtDate(start) : '';
  const tail = gainP > 0 ? gainP.toFixed(1) + ' points better than the home-team rule. The hatched stretch is what the model adds.'
    : gainP < 0 ? Math.abs(gainP).toFixed(1) + ' points below the home-team rule.' : 'level with the home-team rule.';
  txt = {
    base: baseP.toFixed(1), acc: accP.toFixed(1), rendered: false,
    baseX: "Pick the home team in every game and you're right " + baseP.toFixed(1) + '% of the time. That\'s the bar any model has to clear.',
    modelX: games + when + ': ' + tail,
    ariaBase: 'Home-team rule: right ' + baseP.toFixed(1) + '% of the time',
    ariaModel: 'Model: right ' + accP.toFixed(1) + '% of the time, ' + Math.abs(gainP).toFixed(1) + ' points ' + (gainP >= 0 ? 'above' : 'below') + ' the home-team rule at ' + baseP.toFixed(1) + '%'
  };
  setState('base', false);
  sizeHead();
  onScroll(false);
  if (!wired) {
    wired = true;
    onScrollFrame(() => onScroll());
    let t = 0;
    addEventListener('resize', () => { cancelAnimationFrame(t); t = requestAnimationFrame(sizeHead); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(sizeHead);
  }
}

