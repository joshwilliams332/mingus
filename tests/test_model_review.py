"""Tests for scripts/model_review.py: python3 -m unittest discover -s tests"""

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_review as R  # noqa: E402
import nfl_picks as N  # noqa: E402
from test_nfl_picks import make_data  # noqa: E402


def write_stats(path, rows):
    cols = ["player_id", "week", "team", "season_type", "passing_yards", "rushing_yards", "receiving_yards", "receptions"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0) for c in cols} | {"season_type": "REG"})


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.data = make_data(self.dir)                  # Week 9: PHI @ WAS Sun 8:20 PM, DAL @ NYG 1 PM
        for g in self.data.games:
            g["home_score"] = None
        self.store = self.dir / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, s):
        return datetime.fromisoformat(s).replace(tzinfo=N.ET)

    def test_snapshot_freezes_games_once_they_start(self):
        r = R.snapshot(self.data, self.store, self.at("2026-11-08T10:00"))
        self.assertEqual((r["week"], r["games"]), (9, 2))
        f = self.store / "model" / "projections" / "2026-w09.json"
        first = json.loads(f.read_text())["games"]["2026_09_DAL_NYG"]["saved"]
        R.snapshot(self.data, self.store, self.at("2026-11-08T15:00"))   # after the 1 PM kickoff
        doc = json.loads(f.read_text())
        self.assertEqual(doc["games"]["2026_09_DAL_NYG"]["saved"], first)          # frozen
        self.assertNotEqual(doc["games"]["2026_09_PHI_WAS"]["saved"], first)       # night game still updating
        self.assertTrue(any(r["pid"] == "TE1" and r["st"] == "rec_yds" for r in doc["games"]["2026_09_PHI_WAS"]["rows"]))

    def test_score_after_box_score(self):
        R.snapshot(self.data, self.store, self.at("2026-11-08T10:00"))
        N.write(self.store / "odds" / "props" / "2026_09_PHI_WAS.json",
                {"rows": [{"pid": "TE1", "stat": "rec_yds", "line": 45.5, "fair_o": 0.52}]})
        stats = self.dir / "stats.csv"
        write_stats(stats, [{"player_id": "TE1", "week": 9, "team": "PHI", "receiving_yards": 60, "receptions": 6},
                            {"player_id": "QB1", "week": 9, "team": "WAS", "passing_yards": 250, "rushing_yards": 30}])
        card = R.score(self.data, self.store, R.load_week_stats(stats))
        wk = card["weeks"]["9"]
        self.assertEqual(wk["n"], 4)                       # TE rec yds + catches, QB pass + rush yds
        self.assertIn("rec_yds", wk["by_stat"])
        self.assertEqual(wk["books"]["n"], 1)              # the one prop with a real line
        self.assertAlmostEqual(wk["books"]["books"], (0.52 - 1) ** 2, places=4)
        self.assertFalse(wk["complete"])                   # DAL @ NYG has no box score yet

    def test_adoption_rule(self):
        change = [{"setting": "hl", "from": 4, "to": 6}]
        self.assertTrue(R.should_adopt(change, 0.2400, 0.2390))
        self.assertFalse(R.should_adopt(change, 0.2400, 0.2398))   # within the margin: keep
        self.assertFalse(R.should_adopt(change, 0.2400, 0.2410))   # worse on the unseen week: keep
        self.assertFalse(R.should_adopt([], 0.2400, 0.2300))       # nothing to change

    def test_settings_round_trip(self):
        P = N.model_settings()
        N.write(self.store / "model" / "settings.json", {"settings": {**P, "hl": 6, "cs": {"pass_yds": 0.95}}, "adopted_at": "x"})
        saved = (N.VOL_HALF_LIFE, dict(N.MEAN_ADJ))
        try:
            N.apply_settings(self.store)
            self.assertEqual(N.VOL_HALF_LIFE, 6)
            self.assertAlmostEqual(N.MEAN_ADJ["pass_yds"], P["c"] * 0.95)
            self.assertAlmostEqual(N.MEAN_ADJ["rec_yds"], P["c"])
        finally:
            N.VOL_HALF_LIFE, N.MEAN_ADJ = saved[0], saved[1]

    def test_neighbors(self):
        self.assertEqual(R.neighbors([1, 2, 3, 4], 2), [1, 3])
        self.assertEqual(R.neighbors([1, 2, 3], 1), [2])
        self.assertEqual(R.neighbors([2, 4], 3), [2, 4])            # a value between grid points


if __name__ == "__main__":
    unittest.main()
