import csv, json, os, sys, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import pandas as pd
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import availability_predict as ap
from injuries import snapshot_health
from model_contract import check_candidate_publication

class _Model:
    def predict_proba(self, x): return [[.4,.6] for _ in x]
class _Scaler:
    def transform(self, x): return x

class ProductionReadinessTests(unittest.TestCase):
    def test_candidate_round_trip_and_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ap, "CANDIDATE_DIR", d):
            path=ap.save_candidate("test-candidate", _Model(), _Scaler(), ["a", "b"], {"feature_set_version": ap.EXPECTED_FEATURE_SET_VERSION})
            self.assertEqual(ap.load_candidate("test-candidate")["name"], "test-candidate")
            Path(path).write_bytes(Path(path).read_bytes()+b"x")
            with self.assertRaises(ap.CandidateArtifactError): ap.load_candidate("test-candidate")
    def test_explicit_missing_candidate_is_actionable(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ap, "CANDIDATE_DIR", d), patch.dict(os.environ, {"NBA_PRODUCTION_MODEL":"lr-calibrated-availability-v1"}):
            with self.assertRaisesRegex(ap.CandidateArtifactError, "Deploy the matching"):
                ap.load_candidate(required=True)
    def test_legacy_configuration_does_not_require_candidate(self):
        with tempfile.TemporaryDirectory() as d, patch.object(ap, "CANDIDATE_DIR", d), patch.dict(os.environ, {"NBA_PRODUCTION_MODEL":"gradient-boosting-gridsearch"}):
            self.assertIsNone(ap.load_candidate())
    def test_snapshot_health_states(self):
        now=datetime(2026,10,12,19,0,tzinfo=timezone.utc)
        games=pd.DataFrame([{"game_id":"0000000001"},{"game_id":"0000000002"}])
        fresh=pd.DataFrame([{"game_id":"0000000001","report_time":"2026-10-12T18:30:00+00:00"},{"game_id":"0000000002","report_time":"2026-10-12T18:30:00+00:00"}])
        self.assertEqual(snapshot_health(fresh,games,as_of=now)["state"],"fresh")
        self.assertEqual(snapshot_health(fresh.iloc[:1],games,as_of=now)["state"],"partial")
        stale=fresh.assign(report_time="2026-10-12T15:00:00+00:00")
        self.assertEqual(snapshot_health(stale,games,as_of=now)["state"],"stale")
        self.assertEqual(snapshot_health(None,games,as_of=now)["state"],"missing")
    def test_metadata_csv_consistency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=root/"candidates"; c.mkdir(); (c/"x.pkl").write_bytes(b"artifact")
            import hashlib
            h=hashlib.sha256(b"artifact").hexdigest()
            (c/"x.manifest.json").write_text(json.dumps({"model_name":"x","artifact_sha256":h,"feature_set_version":"v1","evaluated_at":"t"}))
            csvp=root/"c.csv"; csvp.write_text("model,feature_set,feature_set_version,evaluated_at,test_games,accuracy,log_loss,brier_score,roc_auc,calibration_ece\nx,s,v1,t,1,0.5,0.5,0.25,0.5,0.1\n")
            meta={"candidates":{"path":"data/c.csv","feature_set_version":"v1","evaluated_at":"t","rows":[{"model":"x","feature_set":"s","feature_set_version":"v1","evaluated_at":"t","test_games":1,"accuracy":"0.5","log_loss":"0.5","brier_score":"0.25","roc_auc":"0.5","calibration_ece":"0.1"}]}}
            mp=root/"m.json"; mp.write_text(json.dumps(meta))
            self.assertTrue(check_candidate_publication(mp,csvp,c)["ok"])

if __name__ == "__main__": unittest.main()

