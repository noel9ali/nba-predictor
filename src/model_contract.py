"""Offline consistency checks for published availability candidate metadata."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path

def _hash(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def check_candidate_publication(metadata_path, leaderboard_path, candidate_dir=None):
    metadata=json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    with Path(leaderboard_path).open(encoding="utf-8", newline="") as handle:
        rows=list(csv.DictReader(handle))
    pub=metadata.get("candidates") or {}
    issues=[]
    if pub.get("path") and Path(pub["path"]).as_posix() != Path(leaderboard_path).as_posix():
        # Relative metadata paths are expected to resolve from the repository root.
        if Path(pub["path"]).name != Path(leaderboard_path).name: issues.append("candidate leaderboard path mismatch")
    by_csv={r.get("model"):r for r in rows}
    by_meta={r.get("model"):r for r in pub.get("rows",[]) if isinstance(r,dict)}
    if set(by_csv) != set(by_meta): issues.append("candidate model names differ between CSV and metadata")
    for name, row in by_csv.items():
        m=by_meta.get(name)
        if not m: continue
        for key in ("feature_set_version","evaluated_at","test_games","log_loss","brier_score","accuracy","roc_auc","calibration_ece"):
            if str(row.get(key)) != str(m.get(key)):
                issues.append(f"{name}: {key} differs between CSV and metadata")
        if pub.get("feature_set_version") != row.get("feature_set_version"):
            issues.append(f"{name}: publication feature_set_version mismatch")
        if pub.get("evaluated_at") != row.get("evaluated_at"):
            issues.append(f"{name}: publication evaluated_at mismatch")
        if candidate_dir is not None:
            p=Path(candidate_dir)/(name+".pkl"); manifest=p.with_suffix(".manifest.json")
            if not p.exists() or not manifest.exists(): issues.append(f"{name}: artifact or manifest missing")
            else:
                man=json.loads(manifest.read_text(encoding="utf-8"))
                if man.get("artifact_sha256") != _hash(p): issues.append(f"{name}: artifact hash mismatch")
                if row.get("artifact_sha256") and row.get("artifact_sha256") != _hash(p): issues.append(f"{name}: published artifact hash mismatch")
                if row.get("artifact_path") and Path(row["artifact_path"]).name != p.name: issues.append(f"{name}: published artifact path mismatch")
                if man.get("model_name") != name: issues.append(f"{name}: manifest model name mismatch")
                if man.get("feature_set_version") != row.get("feature_set_version"): issues.append(f"{name}: artifact feature-set version mismatch")
                if man.get("evaluated_at") != row.get("evaluated_at"): issues.append(f"{name}: artifact evaluated_at mismatch")
    return {"ok": not issues, "issues": issues, "models": sorted(by_csv)}
