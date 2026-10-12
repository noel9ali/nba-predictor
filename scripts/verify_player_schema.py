"""Verify the deployable player schema without connecting to Supabase."""
from __future__ import annotations
import argparse, re
from pathlib import Path
REQUIRED=["20261012000100","20261012000200","20261012000300","20261012000400","20261012000500","20261012000600","20261012000700","20261012000800"]
TABLES={
 "injury_snapshots":["snapshot_id","captured_at","report_time","game_id","game_date","team_id","player_id","status","source"],
 "players":["player_id","full_name","is_active"], "player_aliases":["provider","provider_name","player_id"],
 "player_games":["game_id","player_id","team_id","game_date","season","minutes"], "player_absences":["game_id","player_id","basis"],
 "player_ratings":["player_id","as_of","rating_type","value"], "player_minutes_projection":["game_id","player_id","as_of","p_play","exp_min"],
 "team_availability_features":["game_id","team_id","as_of","rating_type","feature_version"],
 "prediction_scenarios":["game_id","model_name","scenario_key","home_win_prob"], "prediction_factors":["game_id","model_name","factor_key","prob_points"],
 "prediction_availability_inputs":["game_id","model_name","as_of","home_win_prob"], "market_odds":["game_id","market","captured_at"], "player_rate_stats":["player_id","as_of","stat","rate_per_min"],
 "model_runs":["trained_at","production_model","leaderboard","candidates","feature_set_version"],
 "predictions":["prob_range_low","prob_range_high","status_changed_after_pred"],
}
def verify(migrations):
 files=sorted(Path(migrations).glob("*.sql")); issues=[]
 got=[next((x for x in REQUIRED if p.name.startswith(x)),None) for p in files]
 if [x for x in got if x] != REQUIRED: issues.append("required migrations are missing or out of order")
 if any("prop" in p.name.lower() for p in files): issues.append("reserved prop migration must remain outside deployable history")
 text="\n".join(p.read_text(encoding="utf-8") for p in files).lower()
 for table, cols in TABLES.items():
  table_re=r"(?:create|alter)\s+table\s+(?:if\s+not\s+exists\s+)?public\."+re.escape(table)+r"\b"
  if not re.search(table_re, text, re.I):
   issues.append(f"missing table {table}"); continue
  for col in cols:
   # A column may be declared in CREATE or added later with ALTER TABLE.
   if not re.search(r"\b"+re.escape(col)+r"\b", text, re.I): issues.append(f"{table}.{col} missing")
 for p in files:
  content=p.read_text(encoding="utf-8").lower()
  if any(p.name.startswith(x) for x in REQUIRED) and "create table " in content and "if not exists" not in content: issues.append(f"{p.name} is not idempotent")
 return {"ok":not issues,"issues":issues,"migrations":[p.name for p in files if any(p.name.startswith(x) for x in REQUIRED)]}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--migrations",default="supabase/migrations"); args=ap.parse_args(); out=verify(args.migrations); print(out); return 0 if out["ok"] else 1
if __name__=="__main__": raise SystemExit(main())
