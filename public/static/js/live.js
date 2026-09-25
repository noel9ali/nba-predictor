// Live scores for tonight (04 sec3, Games-Controls board):
// - poll /api/live-scores every 30 s while a game is live (and from just before the first
//   tip), with a manual refresh;
// - 2 failed polls in a row -> "stale" (Scores delayed · last update HH:MM, Retry);
// - 5+ minutes without a good update -> "down" (the feed-down banner);
// - every game final -> stop ("All games final · updates stopped").
// A 404 (the route isn't deployed yet, build task B7) or any error counts as a failed poll,
// and a 200 with stale:true does too (the server is serving its last good snapshot).
import { SAMPLE, SCENE, SCENES, api, now } from "./api.js";

const INTERVAL_MS = 30000;
const STALE_AFTER_FAILURES = 2;
const DOWN_AFTER_MS = 5 * 60 * 1000;

export class LiveFeed {
  constructor({ date, onScores, onStatus }) {
    this.date = date;
    this.onScores = onScores;
    this.onStatus = onStatus;
    this.failures = 0;
    this.lastGood = null;
    this.firstFailure = null;
    this.timer = null;
    this.inFlight = false;
    this.stopped = false;
    this.done = false;
    this.interval = SAMPLE && SCENES[SCENE].pollMs ? SCENES[SCENE].pollMs : INTERVAL_MS;
  }

  start() {
    this.stopped = false;
    this.poll();
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.timer);
  }

  retry() {
    window.clearTimeout(this.timer);
    this.poll();
  }

  status() {
    if (this.done) return { kind: "done", at: this.lastGood };
    if (this.inFlight) return { kind: "busy", at: this.lastGood };
    const since = this.lastGood || this.firstFailure;
    const down = this.failures > 0 && since && now().getTime() - since.getTime() >= DOWN_AFTER_MS;
    if (this.failures >= STALE_AFTER_FAILURES || down) return { kind: "stale", at: this.lastGood, down: Boolean(down), since };
    return { kind: "normal", at: this.lastGood };
  }

  async poll() {
    if (this.stopped || this.inFlight) return;
    this.inFlight = true;
    this.onStatus(this.status());
    let allFinal = false;
    try {
      const body = await api.liveScores(this.date);
      if (body.stale) this.fail(body.fetched_at);
      else {
        this.failures = 0;
        this.firstFailure = null;
        this.lastGood = body.fetched_at ? new Date(body.fetched_at) : now();
      }
      allFinal = this.onScores(body.games || [], Boolean(body.stale));
    } catch {
      this.fail(null);
    } finally {
      this.inFlight = false;
    }
    if (allFinal) {
      this.done = true;
      this.stop();
    }
    this.onStatus(this.status());
    if (!this.stopped) this.timer = window.setTimeout(() => this.poll(), this.interval);
  }

  fail(lastFetchedAt) {
    this.failures += 1;
    if (!this.firstFailure) this.firstFailure = now();
    if (lastFetchedAt && !this.lastGood) this.lastGood = new Date(lastFetchedAt);
  }
}
