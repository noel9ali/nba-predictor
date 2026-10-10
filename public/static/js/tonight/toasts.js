// Toasts: one plain sentence when a game tips off or finishes (components/toasts.md).
// Built with createElement + textContent only; tricodes and numbers from the API are never parsed as HTML.
import { store, on, game, summary } from '../state.js';
import { fmt } from '../format.js';

const MAX = 3, SHOW_MS = 6000, FADE_MS = 400;
let ready = false;

export function toast(head, tail) {
  const host = document.querySelector('[data-toasts]');
  if (!host) return;
  const t = document.createElement('div');
  t.className = 'toast';
  const b = document.createElement('b');
  b.textContent = head;
  t.append(b);
  if (tail) t.append(document.createTextNode(' ' + tail));
  host.append(t);
  while (host.children.length > MAX) host.firstElementChild.remove();
  setTimeout(() => {
    t.classList.add('toast--out');
    setTimeout(() => t.remove(), FADE_MS);
  }, SHOW_MS);
}

function tipSentence(g) {
  const head = 'Tip-off: ' + g.away.tricode + ' at ' + g.home.tricode + '.';
  return [head, g.bet ? 'Ticket on ' + g.pick + ' is live.' : 'No ticket on this one.'];
}

function finalSentence(g, rec, running) {
  const A = g.away.tricode, H = g.home.tricode;
  const head = (g.as == null || g.hs == null) ? 'Final: ' + A + ' at ' + H + '.' : 'Final: ' + A + ' ' + g.as + ', ' + H + ' ' + g.hs + '.';
  let tail = '';
  if (g.bet) {
    const tonight = ' Tonight ' + fmt.money(running, true) + '.';
    if (rec.result === 'hit') tail = 'Cashed ' + fmt.money(rec.pl, true) + '.' + tonight;
    else if (rec.result === 'miss') tail = 'Lost ' + fmt.money(rec.pl, true) + '.' + tonight;
  } else if (rec.result === 'hit') tail = 'Pick right, no bet.';
  else if (rec.result === 'miss') tail = 'Pick wrong, no bet.';
  return [head, tail];
}

function onBatch(changes) {
  if (store.isPast) return;
  // Calculate running total for final toasts in this batch.
  // end = final settled total after batch; inBatch = sum of P/L in this batch; running = end - inBatch.
  const end = summary().settled;
  let inBatch = 0;
  for (const c of changes) {
    if (c.type === 'final') {
      const g = game(c.id);
      if (g && g.bet && c.pl != null) inBatch += c.pl;
    }
  }
  let running = end - inBatch;
  // Walk changes in order, building toasts and updating running total.
  for (const c of changes) {
    if (c.type !== 'tip' && c.type !== 'final') continue;
    const g = game(c.id);
    if (!g) continue;
    let head, tail;
    if (c.type === 'tip') {
      [head, tail] = tipSentence(g);
    } else {
      // Final: update running total before building toast.
      if (g.bet && c.pl != null) running += c.pl;
      [head, tail] = finalSentence(g, c, running);
    }
    toast(head, tail);
  }
}

export function initToasts() {
  if (ready) return;
  ready = true;
  on(onBatch);
}
