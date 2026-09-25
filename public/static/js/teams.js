// Team nicknames for cards; colours live in dashboard.css as .team-XXX classes (no inline
// styles under the CSP). Unknown codes fall back to the neutral circle.
import { h } from "./dom.js";

const NICKNAMES = {
  ATL: "Hawks", BOS: "Celtics", BKN: "Nets", CHA: "Hornets", CHI: "Bulls", CLE: "Cavaliers",
  DAL: "Mavericks", DEN: "Nuggets", DET: "Pistons", GSW: "Warriors", HOU: "Rockets",
  IND: "Pacers", LAC: "Clippers", LAL: "Lakers", MEM: "Grizzlies", MIA: "Heat", MIL: "Bucks",
  MIN: "Timberwolves", NOP: "Pelicans", NYK: "Knicks", OKC: "Thunder", ORL: "Magic",
  PHI: "76ers", PHX: "Suns", POR: "Trail Blazers", SAC: "Kings", SAS: "Spurs", TOR: "Raptors",
  UTA: "Jazz", WAS: "Wizards",
};

export function isKnownTeam(code) {
  return typeof code === "string" && Object.prototype.hasOwnProperty.call(NICKNAMES, code);
}

export function teamClass(code) {
  return isKnownTeam(code) ? `team-${code}` : "team-unknown";
}

export function nickname(code, fullName) {
  if (isKnownTeam(code)) return NICKNAMES[code];
  return fullName || "";
}

// The team-colour circle with the tricode (09 Q5 fallback; no real logos yet).
export function logo(code, size = "") {
  const label = code || "?";
  return h("span", {
    class: ["logo", size ? `logo--${size}` : "", teamClass(code)],
    attrs: { "aria-hidden": "true" },
  }, label.length > 4 ? label.slice(0, 3) : label);
}
