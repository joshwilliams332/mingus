"""Tests for scripts/projections.py (the fantasy projection model): python3 -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import projections as N  # noqa: E402

ET = N.ET


def log(weeks, opp, **stats):
    return [{"week": w, "team": None, "opp": opp, **{k: (v[i] if isinstance(v, list) else v) for k, v in stats.items()}}
            for i, w in enumerate(weeks)]


def make_data(folder, sleeper=None, injury=None):
    """Week 9 SNF: PHI @ WAS, Sun Nov 8 2026 20:20 ET (plus a 1 PM game that must be ignored)."""
    teams = {"PHI": {"city": "Philadelphia", "nickname": "Eagles"}, "WAS": {"city": "Washington", "nickname": "Commanders"},
             "DAL": {"city": "Dallas", "nickname": "Cowboys"}, "NYG": {"city": "New York", "nickname": "Giants"}}
    games = [
        {"id": "2026_09_PHI_WAS", "week": 9, "date": "2026-11-08", "time": "20:20", "away": "PHI", "home": "WAS",
         "home_spread": -3, "home_implied": 24.0, "away_implied": 21.0},
        {"id": "2026_09_DAL_NYG", "week": 9, "date": "2026-11-08", "time": "13:00", "away": "DAL", "home": "NYG",
         "home_spread": 1, "home_implied": 22.0, "away_implied": 23.0},
    ]
    weeks = list(range(1, 9))
    te = {"id": "TE1", "name": "Dallas Goedert", "pos": "TE", "team": "PHI", "injury": injury,
          "log": log(weeks, "NYG", rec_yds=[40, 55, 30, 62, 48, 51, 44, 58], rec=[4, 5, 3, 6, 4, 5, 4, 5], tgt=[5, 6, 4, 7, 5, 6, 5, 6])}
    if sleeper is not None:
        te["proj"] = {"sleeper": {"9": {"line": {"rec_yds": sleeper}}}}
    qb = {"id": "QB1", "name": "Jayden Daniels", "pos": "QB", "team": "WAS", "injury": None,
          "log": log(weeks, "DAL", pass_yds=[230, 250, 210, 270, 240, 220, 260, 245], rush_yds=[30, 40, 20, 35, 25, 45, 30, 38], att=32, car=6)}
    # Defenses: WAS gives up a lot to TEs (the DvP sample).
    opp_te = [{"id": f"X{i}", "name": f"Other TE {i}", "pos": "TE", "team": "NYG", "injury": None,
               "log": log([i], "WAS", rec_yds=90, rec=8, tgt=10)} for i in range(1, 9)]
    other = [{"id": "Y1", "name": "Some TE", "pos": "TE", "team": "DAL", "injury": None, "log": log(weeks, "PHI", rec_yds=30, rec=3, tgt=4)}]
    players = [te, qb, *opp_te, *other]
    meta = {"season": 2026}
    for name, v in (("teams", teams), ("games", games), ("players", players), ("meta", meta)):
        (Path(folder) / f"{name}.json").write_text(json.dumps(v))
    return N.Data(folder)


class Projection(unittest.TestCase):
    def test_model_is_volume_times_efficiency_with_matchup(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            x = p["parts"]
            self.assertEqual(p["source"], "Mingus model")
            self.assertAlmostEqual(p["mean"], x["vol"] * x["eff"] * N.MEAN_ADJ["rec_yds"], delta=0.2)
            self.assertGreater(x["f_def_vol"], 1)                 # WAS gives TEs lots of targets...
            self.assertLessEqual(x["f_def_vol"], N.DEF_CAP[1])    # ...capped
            self.assertLess(x["f_imp"], 1)                        # PHI's 21 implied is below the week's average
            self.assertEqual(x["f_script"], 1)                    # game script tested as no help on 2021-2025
            self.assertEqual(p["opp_rank"]["rank"], 1)

    def test_injury_opening_boosts_volume(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            mate = {"id": "WR9", "name": "Out Receiver", "pos": "WR", "team": "PHI", "injury": {"status": "Out"},
                    "log": log(range(1, 9), "NYG", tgt=8, rec=5, rec_yds=60)}
            data.players.append(mate)
            data.by_id["WR9"] = mate
            boost, names = N.openings(data, data.by_id["TE1"], data.game["2026_09_PHI_WAS"], "tgt")
            self.assertGreater(boost, 1)
            self.assertLessEqual(boost, 1.25)
            self.assertEqual(names, ["Out Receiver"])

    def test_long_absence_doesnt_open_volume_again(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            # Out since Week 4: the others' recent games already happened without him.
            mate = {"id": "WR9", "name": "IR Receiver", "pos": "WR", "team": "PHI", "injury": {"status": "Out"},
                    "log": log(range(1, 4), "NYG", tgt=8, rec=5, rec_yds=60)}
            data.players.append(mate)
            data.by_id["WR9"] = mate
            self.assertEqual(N.openings(data, data.by_id["TE1"], data.game["2026_09_PHI_WAS"], "tgt"), (1.0, []))

    def test_sleeper_blended_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d, sleeper=61.0)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            self.assertEqual(p["source"], "Sleeper + Mingus model")
            self.assertAlmostEqual(p["mean"], (61.0 + p["parts"]["mingus"]) / 2, delta=0.1)

    def test_recent_games_count_more(self):
        w = N.decay_weights(5, 4)
        self.assertEqual(w[-1], 1.0)
        self.assertAlmostEqual(w[0], 0.5)                     # four games back counts half
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            te = data.by_id["TE1"]
            for e, t in zip(te["log"], [2, 2, 2, 2, 2, 9, 9, 9]):  # role grew lately
                e["tgt"] = t
            p = N.projection(data, te, "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            self.assertGreater(p["parts"]["vol_base"], (2 * 5 + 9 * 3) / 8)   # above his plain average

    def test_yardage_is_skewed_passing_is_not(self):
        # A line right at the projection: the skewed curve gives the over less than 50% (most games land below the
        # average), passing yards' bell curve gives exactly 50%.
        self.assertLess(N.chance_over({"mean": 50, "sd": 30, "stat": "rec_yds"}, 50), 0.45)
        self.assertAlmostEqual(N.chance_over({"mean": 240, "sd": 70, "stat": "pass_yds"}, 240), 0.5)
        self.assertEqual(N.chance_over({"mean": 3, "sd": 2, "stat": "rec"}, 0), 1.0)

    def test_not_enough_games(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            self.assertIsNone(N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 3))


def espn_fake(completed=True, goedert=(6, 52)):
    sb = {"events": [{"id": "e1", "competitions": [{"status": {"type": {"completed": completed}}, "competitors": [
        {"team": {"abbreviation": "WSH"}}, {"team": {"abbreviation": "PHI"}}]}]}]}
    athletes = [{"athlete": {"displayName": "Dallas Goedert"}, "stats": [str(goedert[0]), str(goedert[1]), "8.7", "0", "21", "8"]}] if goedert else []
    summ = {"boxscore": {"players": [{"team": {"abbreviation": "PHI"}, "statistics": [
        {"name": "receiving", "labels": ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"], "athletes": athletes},
        {"name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD", "LONG"], "athletes": [
            {"athlete": {"displayName": "Saquon Barkley"}, "stats": ["15", "1,04", "6.9", "1", "30"]}]}]}]}}
    return lambda url: sb if "scoreboard" in url else summ


class Touchdowns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.game = self.data.game["2026_09_PHI_WAS"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_more_red_zone_work_and_points_mean_more_tds(self):
        te = self.data.by_id["TE1"]
        base = N.td_chance(self.data, te, self.game)["p"]
        for e in te["log"]:
            e["rz_tgt"] = 2
        self.data._rz = None
        more = N.td_chance(self.data, te, self.game)["p"]
        self.assertGreater(more, base)
        self.game["away_implied"] = 30.0
        self.assertGreater(N.td_chance(self.data, te, self.game)["p"], more)

    def test_needs_three_games_and_counts_only_rush_rec(self):
        te = self.data.by_id["TE1"]
        self.assertIsNone(N.td_chance(self.data, te, {**self.game, "week": 3}))
        self.assertIsNone(N.td_chance(self.data, {**te, "pos": "K"}, self.game))
        p = N.td_chance(self.data, te, self.game)["p"]
        for e in te["log"]:
            e["pass_td"] = 3                                # passing TDs aren't anytime TDs
        self.assertEqual(N.td_chance(self.data, te, self.game)["p"], p)


if __name__ == "__main__":
    unittest.main()
