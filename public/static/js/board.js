// Scorer's board: six dt/dd cells. Updates change the existing dd text and class in place, so a
// live batch never rebuilds the list (no flash; node identity kept).
// cells: [{ label, value, cls?: 'pos'|'neg'|'', small?, testid?, id? }]

export function renderBoard(dl, cells) {
  if (!dl) return;
  const list = cells.slice(0, 6);
  while (list.length < 6) list.push({ label: '', value: '—' });
  if (dl.children.length !== 6) {
    dl.textContent = '';
    for (let i = 0; i < 6; i++) {
      const div = document.createElement('div');
      div.append(document.createElement('dt'), document.createElement('dd'));
      dl.append(div);
    }
  }
  list.forEach((c, i) => {
    const div = dl.children[i], dt = div.firstElementChild, dd = div.lastElementChild;
    if (dt.textContent !== c.label) dt.textContent = c.label;
    const cls = c.cls || '';
    if (dd.className !== cls) dd.className = cls;
    if (c.testid) dd.dataset.testid = c.testid;
    if (c.id) dd.dataset.cell = c.id;
    const want = c.value + (c.small ? '\u0000' + c.small : '');
    if (dd.dataset.v !== want) {
      dd.dataset.v = want;
      dd.textContent = c.value;
      if (c.small) { const s = document.createElement('small'); s.textContent = c.small; dd.append(s); }
    }
  });
}

// Class for a signed value: v > 0 pos, v < 0 neg, 0 none (rounded to cents first).
export function signCls(v) {
  if (v == null || Number.isNaN(v)) return '';
  const r = Math.round(v * 100) / 100;
  return r > 0 ? 'pos' : r < 0 ? 'neg' : '';
}
