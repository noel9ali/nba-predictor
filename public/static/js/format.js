// Formatting and shared constants (port of the prototype's common.js fmt, with null guards).
// No window/document access at import time: this module is unit-tested under Node.

export const TZ = 'America/New_York';
export const MINUS = '−';
export const NDASH = '–';

export const fmt = {
  money(v, sign) {
    if (v == null || Number.isNaN(v)) return '—';
    const r = Math.round(v * 100) / 100;
    const s = '$' + Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return sign ? (r > 0 ? '+' : r < 0 ? MINUS : '±') + s : (r < 0 ? MINUS : '') + s;
  },
  pct(p, d = 1) { return p == null || Number.isNaN(p) ? '—' : (p * 100).toFixed(d) + '%'; },
  pts(p, d = 1) { return p == null || Number.isNaN(p) ? '—' : (p >= 0 ? '+' : MINUS) + Math.abs(p * 100).toFixed(d); },
  odds(o) { return o == null ? '—' : (o > 0 ? '+' + o : MINUS + Math.abs(o)); },
  time(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(+d)) return '—';
    return d.toLocaleTimeString('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' }).replace(/[  ]/g, ' ');
  },
  date(iso, opts) {
    return new Date(String(iso).slice(0, 10) + 'T12:00:00Z').toLocaleDateString('en-US', Object.assign({ timeZone: 'UTC' }, opts));
  },
  implied(o) { return o > 0 ? 100 / (o + 100) : -o / (-o + 100); },
  payout(amount, o) { return o > 0 ? amount * o / 100 : amount * 100 / -o; },
  until(iso, nowMs) {
    const m = Math.max(0, Math.round((Date.parse(iso) - nowMs) / 60000));
    return m >= 60 ? Math.floor(m / 60) + 'h ' + String(m % 60).padStart(2, '0') + 'm' : m + 'm';
  }
};

// HTML-escape every API string before it goes into an HTML string.
export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export const pct1 = v => (Math.round(v * 10000) / 100).toFixed(1);       // 0.6811 -> "68.1"
export const fmtInt = n => (n == null ? '—' : Math.round(n).toLocaleString('en-US'));
// "2025-02-25" -> "Feb 25, 2025"
export function fmtDate(iso) {
  if (!iso) return '';
  return new Date(String(iso).slice(0, 10) + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}
// "Nov 17" from a YYYY-MM-DD
export const monthDay = iso => fmt.date(iso, { month: 'short', day: 'numeric' });
export const wl = s => String(s == null ? '' : s).replace(/(\d)-(\d)/g, '$1' + NDASH + '$2');  // "54-41" -> "54–41"
export function parseWL(s) {
  const m = /^(\d+)-(\d+)$/.exec(String(s || ''));
  return m ? [Number(m[1]), Number(m[2])] : [0, 0];
}
export const seasonLabel = s => String(s || '').replace(/(\d)-(\d)/g, '$1' + NDASH + '$2');

// A Date as YYYY-MM-DD in America/New_York.
export function dateET(d) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(d).map(x => [x.type, x.value]));
  return p.year + '-' + p.month + '-' + p.day;
}
// NBA season label of a date: Oct–Dec -> YYYY-(YY+1), Jan–Sep -> (YYYY-1)-YY.
export function seasonOf(iso) {
  const y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7));
  const start = m >= 10 ? y : y - 1;
  return start + '-' + String((start + 1) % 100).padStart(2, '0');
}

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
export const word = n => (n >= 0 && n <= 12 && Number.isInteger(n) ? WORDS[n] : String(n));
export const Word = n => { const w = word(n); return w.charAt(0).toUpperCase() + w.slice(1); };
export function ord(n) {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
export function joinAnd(list) {
  if (list.length <= 1) return list.join('');
  return list.slice(0, -1).join(', ') + ' and ' + list[list.length - 1];
}
export function fractionWord(x) {
  if (x === 0.25) return 'a quarter';
  if (x === 0.5) return 'half';
  if (x === 0.75) return 'three quarters';
  return Math.round(x * 100) + '%';
}
export function kellyNoun(x) {
  if (x === 0.25) return 'quarter';
  if (x === 0.5) return 'half';
  return Math.round(x * 100) + '%';
}

export const KELLY_FRACTION = 0.25;
export const MAX_STAKE = 0.05;
export const FEATURE_COUNT = 16;                 // no API field carries it yet (B2 follow-up)
export const PANDEMIC_2019_20_GAMES = 1059;
export const FULL_SEASON_GAMES = 1230;
export const ELO_DEFAULTS = { k: 20, home_advantage: 100, mean_reversion: 0.25, start: 1500 };   // src/elo.py

export const TEAM_COLORS = {
  MIA: '#98002E', ORL: '#0077C0', BOS: '#007A33', NYK: '#006BB6', DEN: '#0E2240', MIN: '#236192',
  CLE: '#860038', MIL: '#00471B', LAL: '#552583', PHX: '#1D1160', GSW: '#1D428A', SAC: '#5A2D81'
};
export const TRICODE = /^[A-Z]{2,4}$/;

const NICKS = ['Trail Blazers', 'Timberwolves', 'Mavericks', 'Cavaliers', 'Grizzlies', 'Clippers', 'Pelicans', 'Wizards', 'Raptors', 'Rockets',
  'Celtics', 'Hornets', 'Nuggets', 'Pistons', 'Thunder', 'Knicks', 'Lakers', 'Hawks', 'Nets', 'Bulls', 'Pacers', 'Heat', 'Bucks', 'Magic', '76ers',
  'Suns', 'Kings', 'Spurs', 'Jazz', 'Warriors'];
export function teamParts(t) {
  const n = (t && t.name) || '', tri = (t && t.tricode) || '';
  const nick = NICKS.find(k => n.endsWith(k));
  return nick ? { city: n.slice(0, -nick.length).trim() || tri, nick } : { city: n || tri, nick: n || tri };
}

export const MODEL_LABELS = {
  'gradient-boosting': 'Gradient boosting',
  'gradient-boosting-gridsearch': 'Gradient boosting',
  'calibrated-xgboost': 'Calibrated XGBoost',
  'current-xgboost': 'XGBoost',
  'lstm': 'LSTM',
  'lstm-gridsearch': 'LSTM',
  'random-forest': 'Random forest',
  'random-forest-gridsearch': 'Random forest',
  'logistic': 'Calibrated logistic',
  'legacy-calibrated-logistic': 'Calibrated logistic'
};
export function modelLabel(key) {
  if (key == null) return '';
  if (Object.prototype.hasOwnProperty.call(MODEL_LABELS, key)) return MODEL_LABELS[key];
  const s = String(key).replace(/[-_]+/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
