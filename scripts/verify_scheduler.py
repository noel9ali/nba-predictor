"""Static scheduler contract check; never registers a Windows task."""
from pathlib import Path
def verify(root="."):
 r=Path(root); issues=[]
 daily=(r/"scheduler"/"task_scheduler_setup.ps1").read_text(encoding="utf-8")
 injury=(r/"scheduler"/"register_injury_snapshot_task.ps1").read_text(encoding="utf-8")
 bat=(r/"scheduler"/"run_injury_snapshot.bat").read_text(encoding="utf-8")
 pipe=(r/"run_pipeline.bat").read_text(encoding="utf-8"); pred=(r/"run_predict.bat").read_text(encoding="utf-8")
 for label,text,need in [("daily",daily,"NBA-Predictor-Daily"),("injury",injury,"NBA-Predictor-Injury-Snapshot"),("injury command",bat,"python -m src.injuries --snapshot"),("morning",pipe,"python -m src.injuries --snapshot"),("predict",pred,"python -m src.injuries --snapshot")]:
  if need not in text: issues.append(f"{label}: missing {need}")
 if "EveryMinutes = 30" not in injury and "-RepetitionInterval (New-TimeSpan -Minutes 30)" not in injury and "-RI 30" not in injury: issues.append("injury: not scheduled every 30 minutes")
 if "11:00" not in injury: issues.append("injury: missing 11:00 start")
 return {"ok":not issues,"issues":issues}
if __name__=="__main__":
 import argparse; a=argparse.ArgumentParser();a.add_argument("--root",default="."); o=verify(a.parse_args().root); print(o); raise SystemExit(0 if o["ok"] else 1)

