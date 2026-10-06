// "One game, one row": the 16 numbers the model sees for the featured game, on a paper card.
// Built with createElement/textContent only. Returns true when it rendered, false when there was
// nothing to show (no game, or no tape), in which case nothing is added to the mount.
import { fmtDate, monthDay, pct1, fmtInt, teamParts, FEATURE_COUNT, MINUS } from '../format.js';

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const has = v => typeof v === 'number' && Number.isFinite(v);
const one = v => (has(v) ? v.toFixed(1) : '—');
const signed = n => (n > 0 ? '+' + n : n < 0 ? MINUS + Math.abs(n) : '0');
const days = n => (n === 0 ? '0 days' : (n > 0 ? '+' : MINUS) + Math.abs(n) + (Math.abs(n) === 1 ? ' day' : ' days'));

export function renderRowCard(mount, { detail, rollingWindow } = {}) {
  if (!mount) return false;
  mount.textContent = '';
  const g = detail && detail.game, tape = detail && detail.tape;
  if (!g || !g.home || !g.away || !tape || !(tape.home || tape.away)) return false;
  const th = tape.home || {}, ta = tape.away || {};
  const hasAny = o => Object.keys(o).some(k => has(o[k]));
  if (!hasAny(th) && !hasAny(ta)) return false;

  const W = has(rollingWindow) ? rollingWindow : 10;
  const H = g.home.tricode, A = g.away.tricode;
  const hp = teamParts(g.home), ap = teamParts(g.away);
  const date = g.date || null;

  const root = el('div', 'rowcard'); root.setAttribute('data-rowcard', '');

  // Text column
  const txt = el('div');
  txt.append(el('h3', null, 'One game, one row'),
    el('p', null, `Each game becomes ${FEATURE_COUNT} numbers about the two teams going in: their ratings, their last ${W} games, and their rest. This is the row for ${ap.nick} at ${hp.nick}${date ? ' on ' + monthDay(date) : ''}. The answer it learned to predict: did the home team win?`));

  // Paper card
  const paper = el('div', 'paper');
  const band = el('div', 'band');
  band.append(el('span', null, `Row · ${A} at ${H}${date ? ' · ' + fmtDate(date) : ''}`), el('span', null, `${FEATURE_COUNT} inputs`));

  const wrap = el('div', 'tblwrap');
  const table = el('table');
  table.append(el('caption', 'sr', `The ${FEATURE_COUNT} inputs the model sees for ${ap.city} at ${hp.city}${date ? ' on ' + fmtDate(date) : ''}`));

  const thead = el('thead'), hr = el('tr');
  [['Input'], [`${H} (home)`], [`${A} (away)`]].forEach(([t]) => { const c = el('th', null, t); c.scope = 'col'; hr.append(c); });
  thead.append(hr);

  const fmtElo = v => (has(v) ? fmtInt(v) : '—');
  const rows = [
    ['Elo rating', 'elo', fmtElo],
    [`Points · last ${W}`, 'roll_pts', one],
    [`FG% · last ${W}`, 'roll_fg_pct', v => (has(v) ? pct1(v) + '%' : '—')],
    [`Rebounds · last ${W}`, 'roll_reb', one],
    [`Assists · last ${W}`, 'roll_ast', one],
    [`Turnovers · last ${W}`, 'roll_tov', one],
    [`Steals+blocks · last ${W}`, 'roll_stocks', one]
  ];
  const tbody = el('tbody');
  rows.forEach(([label, key, f]) => {
    const tr = el('tr'), rh = el('th', null, label);
    rh.scope = 'row';
    tr.append(rh, el('td', null, f(th[key])), el('td', null, f(ta[key])));
    tbody.append(tr);
  });

  // Footer: Elo gap from the rounded ratings, then the rest gap.
  const eloGap = has(th.elo) && has(ta.elo) ? signed(Math.round(th.elo) - Math.round(ta.elo)) : '—';
  const restGap = has(th.rest_days) && has(ta.rest_days) ? days(Math.round(th.rest_days) - Math.round(ta.rest_days)) : '—';
  const tfoot = el('tfoot'), fr = el('tr'), fh = el('th', null, 'Elo gap · rest gap');
  fh.scope = 'row';
  const fd = el('td', null, `${eloGap} · ${restGap}`);
  fd.colSpan = 2;
  fr.append(fh, fd); tfoot.append(fr);

  table.append(thead, tbody, tfoot);
  wrap.append(table);
  paper.append(band, wrap);
  root.append(txt, paper);
  mount.append(root);

  // Keyboard-scrollable only when the table really overflows (320px fallback).
  const sync = () => {
    const over = wrap.scrollWidth > wrap.clientWidth + 1;
    if (over) {
      wrap.setAttribute('tabindex', '0');
      wrap.setAttribute('role', 'region');
      wrap.setAttribute('aria-label', 'Row of model inputs, scrolls sideways');
    } else {
      wrap.removeAttribute('tabindex'); wrap.removeAttribute('role'); wrap.removeAttribute('aria-label');
    }
  };
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(sync).observe(wrap);
  return true;
}
