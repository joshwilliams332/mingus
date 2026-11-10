"""Tests for scripts/model_review.py: python3 -m unittest discover -s tests"""

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_review as R  # noqa: E402
import projections as N  # noqa: E402
from test_projections import make_data  # noqa: E402


def write_stats(path, rows):
    cols = ["player_id", "week", "team", "season_type", "passing_yards", "rushing_yards", "receiving_yards", "receptions",
            "rushing_tds", "receiving_tds"]
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
        stats = self.dir / "stats.csv"
        write_stats(stats, [{"player_id": "TE1", "week": 9, "team": "PHI", "receiving_yards": 60, "receptions": 6},
                            {"player_id": "QB1", "week": 9, "team": "WAS", "passing_yards": 250, "rushing_yards": 30}])
        card = R.score(self.data, self.store, R.load_week_stats(stats))
        wk = card["weeks"]["9"]
        self.assertEqual(wk["n"], 4)                       # TE rec yds + catches, QB pass + rush yds
        self.assertIn("rec_yds", wk["by_stat"])
        self.assertFalse(wk["complete"])                   # DAL @ NYG has no box score yet

    def test_td_chances_saved_and_scored(self):
        R.snapshot(self.data, self.store, self.at("2026-11-08T10:00"))
        doc = json.loads((self.store / "model" / "projections" / "2026-w09.json").read_text())
        td = {r["pid"]: r["p"] for r in doc["games"]["2026_09_PHI_WAS"]["td"]}
        self.assertIn("TE1", td)
        self.assertTrue(0 < td["TE1"] < 1)
        stats = self.dir / "stats.csv"
        write_stats(stats, [{"player_id": "TE1", "week": 9, "team": "PHI", "receiving_yards": 60, "receiving_tds": 1},
                            {"player_id": "QB1", "week": 9, "team": "WAS", "passing_yards": 250}])
        t = R.score(self.data, self.store, R.load_week_stats(stats))["weeks"]["9"]["td"]
        self.assertEqual(t["rate"], 0.5)                   # TE scored, QB didn't (passing TDs don't count)
        self.assertEqual(t["n"], 2)

    def test_sources_compare_ours_and_sleeper(self):
        rows = [{"st": "rec_yds", "mean": 50, "mingus": 40, "sleeper": 60, "actual": 50, "err": 0, "p_over": .5, "hit": 1.0}]
        so = R.summarize_rows(rows)["sources"]
        self.assertEqual((so["ours"], so["sleeper"], so["blend"]), (20.0, 20.0, 0.0))

    def test_settings_round_trip(self):
        P = N.model_settings()
        N.write(self.store / "model" / "settings.json", {"settings": {**P, "hl": 6, "cs": {"pass_yds": 0.95}, "Ks": {"rush_yds": 300}},
                                                          "adopted_at": "x", "version": N.SETTINGS_VERSION})
        saved = (N.VOL_HALF_LIFE, dict(N.MEAN_ADJ), dict(N.RATE_PAD_BY))
        try:
            N.apply_settings(self.store)
            self.assertEqual(N.VOL_HALF_LIFE, 6)
            self.assertAlmostEqual(N.MEAN_ADJ["pass_yds"], P["c"] * 0.95)
            self.assertAlmostEqual(N.MEAN_ADJ["rec_yds"], P["c"])
            self.assertEqual(N.RATE_PAD_BY, {"rush_yds": 300})
        finally:
            N.VOL_HALF_LIFE, N.MEAN_ADJ, N.RATE_PAD_BY = saved

    def test_older_settings_file_is_replaced(self):
        old = {"settings": {**N.model_settings(), "c": 1.2}, "adopted_at": "2026-10-31T14:34+00:00", "week": 7}   # no version
        N.write(self.store / "model" / "settings.json", old)
        self.assertIsNone(N.apply_settings(self.store))                     # the code's defaults stay
        r = R.migrate_settings(self.store, datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.assertEqual(r["state"], "replaced")
        doc = N.read(self.store / "model" / "settings.json")
        self.assertEqual((doc["version"], doc["settings"]["c"]), (N.SETTINGS_VERSION, N.model_settings()["c"]))
        self.assertIn("2016-2025", N.read(self.store / "model" / "settings-history.json")[-1]["why"])
        self.assertEqual(R.migrate_settings(self.store, datetime(2026, 11, 10, tzinfo=timezone.utc))["state"], "current")

    def test_adoption_needs_most_past_seasons(self):
        self.assertTrue(R.should_adopt([1], {"wins": 8, "seasons": 10}, 0.24, 0.239))
        self.assertFalse(R.should_adopt([1], {"wins": 6, "seasons": 10}, 0.24, 0.239))    # not most seasons
        self.assertFalse(R.should_adopt([1], {"wins": 9, "seasons": 10}, 0.24, 0.25))     # worse on the new week
        self.assertFalse(R.should_adopt([], {"wins": 10, "seasons": 10}, 0.24, 0.239))    # nothing changed

    def test_neighbors(self):
        self.assertEqual(R.neighbors([1, 2, 3, 4], 2), [1, 3])
        self.assertEqual(R.neighbors([1, 2, 3], 1), [2])
        self.assertEqual(R.neighbors([2, 4], 3), [2, 4])            # a value between grid points


if __name__ == "__main__":
    unittest.main()
