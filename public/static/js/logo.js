// Team logo <img> (same-origin /static/logos/<TRI>.svg), falling back to a team-colour chip when
// the tricode is unknown or the file fails to load. The tricode text next to it carries the name.
import { TEAM_COLORS, TRICODE } from './format.js';

function chip(tri) {
  const i = document.createElement('i');
  i.className = 'chip';
  i.setAttribute('aria-hidden', 'true');
  i.style.setProperty('--c', TEAM_COLORS[tri] || '#6a4e2e');
  return i;
}

export function logo(tri, cls, size) {
  if (!TRICODE.test(String(tri || ''))) return chip(tri);
  const img = document.createElement('img');
  img.className = 'logo' + (cls ? ' ' + cls : '');
  img.src = '/static/logos/' + tri + '.svg';
  img.alt = '';
  img.width = size; img.height = size;
  img.decoding = 'async';
  img.addEventListener('error', () => img.replaceWith(chip(tri)), { once: true });
  return img;
}
