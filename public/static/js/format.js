// Number, money, odds and date formatting. Signs use the real minus (U+2212) and records use
// an en dash, as the design does. Every P/L carries a sign (DESIGN sec1: colour is never
// the only cue).

export const MINUS = "−";
const TZ = "America/New_York";

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

const moneyFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(v) {
  if (!isNum(v)) return "—";
  return (v < 0 ? MINUS : "") + "$" + moneyFmt.format(Math.abs(v));
}

export function signedMoney(v) {
  if (!isNum(v)) return "—";
  const r = Math.round(v * 100) / 100;
  if (r === 0) return "$0.00";
  return (r > 0 ? "+" : MINUS) + "$" + moneyFmt.format(Math.abs(r));
}

export function odds(v) {
  if (!isNum(v)) return "—";
  return (v > 0 ? "+" : MINUS) + Math.abs(Math.round(v));
}

export function pct(v, digits = 0) {
  if (!isNum(v)) return "—";
  return (v < 0 ? MINUS : "") + (Math.abs(v) * 100).toFixed(digits) + "%";
}

export function signedPct(v, digits = 1) {
  if (!isNum(v)) return "—";
  const r = Number((v * 100).toFixed(digits));
  if (r === 0) return (0).toFixed(digits) + "%";
  return (r > 0 ? "+" : MINUS) + Math.abs(r).toFixed(digits) + "%";
}

export function record(text) {
  return typeof text === "string" ? text.replace("-", "–") : "—";
}

export function recordParts(text) {
  const m = typeof text === "string" ? text.match(/^(\d+)-(\d+)$/) : null;
  return m ? [Number(m[1]), Number(m[2])] : [0, 0];
}

export function signClass(v) {
  if (!isNum(v) || Math.round(v * 100) === 0) return "";
  return v > 0 ? "pos" : "neg";
}

// Implied probability of an American price.
export function impliedProb(price) {
  if (!isNum(price) || price === 0) return null;
  return price > 0 ? 100 / (price + 100) : Math.abs(price) / (Math.abs(price) + 100);
}

// Profit on a winning stake at an American price, rounded to cents.
export function payout(stake, price) {
  if (!isNum(stake) || !isNum(price) || price === 0) return null;
  const mult = price > 0 ? price / 100 : 100 / Math.abs(price);
  return Math.round(stake * mult * 100) / 100;
}

// ---------------------------------------------------------------- dates (US Eastern)
function parseDay(day) {
  // YYYY-MM-DD at noon UTC, so it lands on the same calendar day in Eastern time.
  return new Date(`${day}T12:00:00Z`);
}

const fmtCache = new Map();
function fmt(options) {
  const key = JSON.stringify(options);
  if (!fmtCache.has(key)) fmtCache.set(key, new Intl.DateTimeFormat("en-US", { timeZone: TZ, ...options }));
  return fmtCache.get(key);
}

export function dayLong(day) { // "Tue, Nov 17"
  return day ? fmt({ weekday: "short", month: "short", day: "numeric" }).format(parseDay(day)) : "—";
}
export function dayShort(day) { // "Nov 17"
  return day ? fmt({ month: "short", day: "numeric" }).format(parseDay(day)) : "—";
}
export function weekday(day) { // "Tue"
  return day ? fmt({ weekday: "short" }).format(parseDay(day)) : "";
}
export function timeET(iso) { // "7:00 PM"
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : fmt({ hour: "numeric", minute: "2-digit" }).format(d);
}
export function dateTimeET(iso) { // "Nov 17, 6:31 PM"
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : fmt({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
}
export function dateET(date) { // YYYY-MM-DD for an instant, in Eastern time
  const parts = fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
export function addDays(day, n) {
  const d = parseDay(day);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function countdown(ms) {
  if (ms <= 0) return "Tipping off";
  const mins = Math.ceil(ms / 60000);
  if (mins < 60) return `Tips in ${mins} min`;
  const hrs = Math.floor(mins / 60);
  const rest = mins % 60;
  return rest ? `Tips in ${hrs}h ${rest}m` : `Tips in ${hrs}h`;
}

export function elapsed(ms) {
  const secs = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(secs / 60);
  return m ? `${m}m ${secs % 60}s` : `${secs}s`;
}

export function seasonLabel(season) { // "2025-26" -> "2025–26"
  if (season === "all") return "All seasons";
  return typeof season === "string" ? season.replace("-", "–") : "—";
}

// Model ids from model_metadata.json -> short display names.
const MODEL_NAMES = {
  "legacy-calibrated-logistic": "Calibrated logistic",
  "current-xgboost": "XGBoost",
  "calibrated-xgboost": "Calibrated XGBoost",
  "gradient-boosting-gridsearch": "Gradient boosting",
};
export function modelName(id) {
  if (!id) return null;
  return MODEL_NAMES[id] || id;
}
