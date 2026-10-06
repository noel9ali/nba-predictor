// Ticket toolbar: filter group (with counts) and sort group. Buttons are created once; later
// updates change aria-pressed, the count text and the aria-label in place so focus never moves.
import { store, FILTERS, SORTS, counts, setFilter, setSort } from '../state.js';

let bar = null, filtersEl = null, sortsEl = null, renderGridFn = null;

const plural = n => n + (n === 1 ? ' game' : ' games');

function build() {
  filtersEl.textContent = '';
  for (const [key, label] of FILTERS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.dataset.f = key;
    b.append(document.createTextNode(label));
    const c = document.createElement('span');
    c.setAttribute('aria-hidden', 'true');
    b.append(c);
    filtersEl.append(b);
  }
  sortsEl.textContent = '';
  for (const [key, label] of SORTS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.dataset.s = key;
    b.textContent = label;
    sortsEl.append(b);
  }
}

// Sync pressed state, counts and labels with the store. Also hides the whole toolbar when there
// is nothing to filter.
export function updateToolbar() {
  if (!bar) return;
  const c = counts();
  for (const [key, label] of FILTERS) {
    const b = filtersEl.querySelector('[data-f="' + key + '"]');
    if (!b) continue;
    b.setAttribute('aria-pressed', String(store.filter === key));
    b.setAttribute('aria-label', label + ', ' + plural(c[key]));
    b.querySelector('span').textContent = String(c[key]);
  }
  for (const [key] of SORTS) {
    const b = sortsEl.querySelector('[data-s="' + key + '"]');
    if (b) b.setAttribute('aria-pressed', String(store.sort === key));
  }
  bar.hidden = store.games.length === 0;
}

function press(kind, key) {
  if (kind === 'f') setFilter(key); else setSort(key);
  updateToolbar();
  if (renderGridFn) renderGridFn({ replay: true });
  const b = (kind === 'f' ? filtersEl : sortsEl).querySelector('[data-' + kind + '="' + key + '"]');
  if (b) b.focus();
}

// Used by the grid's empty-state "Show all games" button: filter all, focus the All button.
export function showAllGames() { press('f', 'all'); }

export function mountToolbar({ renderGrid } = {}) {
  renderGridFn = renderGrid || null;
  bar = document.querySelector('[data-toolbar]');
  filtersEl = document.querySelector('[data-testid="filters"]');
  sortsEl = document.querySelector('[data-testid="sorts"]');
  if (!bar || !filtersEl || !sortsEl) return;
  build();
  bar.addEventListener('click', e => {
    const t = e.target instanceof Element ? e.target.closest('button') : null;
    if (!t || !bar.contains(t)) return;
    if (t.dataset.f) press('f', t.dataset.f);
    else if (t.dataset.s) press('s', t.dataset.s);
  });
  bar.hidden = false;
  updateToolbar();
}
