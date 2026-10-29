"""Tests for scripts/nfl_picks.py: python3 -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import nfl_picks as N  # noqa: E402

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


def event_odds(over=-110, under=-110, line=45.5):
    books = []
    for title, o, u in (("DraftKings", over, under), ("FanDuel", over + 5, under - 5), ("BetMGM", over, under)):
        books.append({"key": title.lower(), "title": title, "markets": [
            {"key": "player_reception_yds", "outcomes": [
                {"name": "Over", "description": "Dallas Goedert", "price": o, "point": line},
                {"name": "Under", "description": "Dallas Goedert", "price": u, "point": line}]},
            {"key": "player_pass_yds", "outcomes": [
                {"name": "Over", "description": "Jayden Daniels", "price": -112, "point": 238.5},
                {"name": "Under", "description": "Jayden Daniels", "price": -108, "point": 238.5}]},
        ]})
    return {"bookmakers": books}


class FakeAPI:
    def __init__(self, odds, remaining=300):
        self.odds, self.usage, self.calls = odds, {"remaining": remaining}, []

    def events(self):
        self.calls.append("events")
        return [{"id": "ev1", "home_team": "Washington Commanders", "away_team": "Philadelphia Eagles",
                 "commence_time": "2026-11-09T01:20:00Z"}]

    def props(self, event_id):
        self.calls.append(event_id)
        self.usage["remaining"] -= 4
        return self.odds


def stats_rows(week, rows):
    return [{"week": str(week), "team": t, "player_id": pid, **{k: str(v) for k, v in st.items()}} for pid, t, st in rows]


class Helpers(unittest.TestCase):
    def test_implied_and_payout(self):
        self.assertAlmostEqual(N.implied(-110), 0.5238, places=3)
        self.assertAlmostEqual(N.implied(150), 0.4)
        self.assertAlmostEqual(N.payout(-200), 0.5)
        self.assertAlmostEqual(N.payout(150), 1.5)

    def test_names_match_across_sources(self):
        self.assertEqual(N.norm_name("Amon-Ra St. Brown"), N.norm_name("Amon Ra St Brown"))
        self.assertEqual(N.norm_name("Kenneth Walker III"), "kenneth walker")

    def test_night_games_only(self):
        self.assertTrue(N.is_night({"time": "20:15"}))
        self.assertFalse(N.is_night({"time": "16:25"}))

    def test_slot_label(self):
        self.assertEqual(N.slot_label({"date": "2026-11-08", "time": "20:20"}), "SNF")
        self.assertEqual(N.slot_label({"date": "2026-11-05", "time": "20:15"}), "TNF")
        self.assertEqual(N.slot_label({"date": "2026-11-09", "time": "20:15"}), "MNF")


class Props(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(self.tmp.name)
        self.game = self.data.game["2026_09_PHI_WAS"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_consensus_and_no_vig(self):
        rows = {r["stat"]: r for r in N.parse_props(event_odds(), self.data, self.game)}
        r = rows["rec_yds"]
        self.assertEqual((r["line"], r["books"]), (45.5, 3))
        self.assertEqual((r["over"], r["book_o"]), (-105, "FanDuel"))   # best over price
        self.assertAlmostEqual(r["fair_o"] + r["fair_u"], 1)
        self.assertAlmostEqual(rows["pass_yds"]["fair_o"], 0.5047, places=3)

    def test_ignores_players_not_in_the_game(self):
        odds = {"bookmakers": [{"title": "DK", "markets": [{"key": "player_receptions", "outcomes": [
            {"name": "Over", "description": "Some TE", "price": -110, "point": 3.5},
            {"name": "Under", "description": "Some TE", "price": -110, "point": 3.5}]}]}]}
        self.assertEqual(N.parse_props(odds, self.data, self.game), [])

    def test_event_match(self):
        ev = N.match_event(self.data, self.game, FakeAPI(None).events())
        self.assertEqual(ev["id"], "ev1")


class Projection(unittest.TestCase):
    def test_model_is_volume_times_efficiency_with_matchup(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            x = p["parts"]
            self.assertEqual(p["source"], "Mingus model")
            self.assertAlmostEqual(p["mean"], x["vol"] * x["eff"], delta=0.2)
            self.assertGreater(x["f_def_vol"], 1)                 # WAS gives TEs lots of targets...
            self.assertLessEqual(x["f_def_vol"], 1.15)            # ...capped
            self.assertLess(x["f_imp"], 1)                        # PHI's 21 implied is below the week's average
            self.assertGreater(x["f_script"], 1)                  # 3-point underdogs throw a bit more
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

    def test_sleeper_blended_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d, sleeper=61.0)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            self.assertEqual(p["source"], "Sleeper + Mingus model")
            self.assertAlmostEqual(p["mean"], (61.0 + p["parts"]["mingus"]) / 2, delta=0.1)

    def test_not_enough_games(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            self.assertIsNone(N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 3))


class LockAndGrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, hhmm, day="2026-11-08"):
        return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=ET)

    def test_waits_until_four_hours_before_kickoff(self):
        api = FakeAPI(event_odds())
        self.assertEqual(N.lock(self.data, self.store, self.at("15:00"), api)["state"], "waiting")
        self.assertEqual(api.calls, [])                         # no credits spent while waiting

    def test_no_night_games(self):
        self.assertEqual(N.lock(self.data, self.store, self.at("17:00", "2026-11-10"), FakeAPI(None))["state"], "no-games")

    def test_locks_once_and_pulls_once(self):
        api = FakeAPI(event_odds(over=110, under=-140, line=45.5))   # over is a plus price; we project well above 45.5
        r = N.lock(self.data, self.store, self.at("17:00"), api)
        self.assertEqual(r["state"], "locked")
        doc = json.loads((self.store / "picks" / "2026-11-08.json").read_text())
        self.assertFalse(doc["test"])
        self.assertTrue(all(p["gid"] == "2026_09_PHI_WAS" for p in doc["picks"]))
        self.assertLessEqual(len(doc["picks"]), N.PICK["per_game"])
        self.assertIn("1-800-GAMBLER", doc["post"]["main"])
        self.assertLessEqual(N.post_length(doc["post"]["main"]), 280)
        self.assertTrue(doc["email"]["subject"].startswith("🏈 SNF post"))
        if doc["picks"]:
            self.assertIn("Deep dive", doc["email"]["html"])
            self.assertTrue(all(len(f"{N.short(p)}: {p['why']}") <= 280 for p in doc["picks"]))
        before = list(api.calls)
        again = N.lock(self.data, self.store, self.at("17:30"), api)
        self.assertEqual(again["why"], "already locked")
        self.assertEqual(api.calls, before)                       # never re-pulled or rewritten

    def test_injured_player_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d, injury={"status": "Questionable"})
            rows = N.parse_props(event_odds(over=110, under=-140), data, data.game["2026_09_PHI_WAS"])
            self.assertFalse(any(c["player"]["id"] == "TE1" for c in N.candidates(data, data.game["2026_09_PHI_WAS"], rows)))

    def test_far_from_market_is_skipped(self):
        game = self.data.game["2026_09_PHI_WAS"]
        rows = N.parse_props(event_odds(line=150.5), self.data, game)   # a line we'd call a near-certain under
        self.assertFalse([c for c in N.candidates(self.data, game, rows) if c["row"]["stat"] == "rec_yds"])

    def test_keeps_credit_reserve(self):
        r = N.lock(self.data, self.store, self.at("17:00"), FakeAPI(event_odds(), remaining=12))
        self.assertEqual(r["state"], "no-credits")

    def test_grade(self):
        pick = {"pid": "TE1", "team": "PHI", "opp": "WAS", "week": 9, "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        rows = stats_rows(9, [("TE1", "PHI", {"receiving_yards": 52}), ("QB1", "WAS", {"passing_yards": 240})])
        self.assertEqual(N.grade(pick, rows)["status"], "win")
        self.assertAlmostEqual(N.grade(pick, rows)["profit"], 0.909, places=3)
        self.assertEqual(N.grade({**pick, "side": "u"}, rows)["profit"], -1)
        self.assertEqual(N.grade(pick, stats_rows(9, [("QB1", "WAS", {"passing_yards": 240})]))["status"], "void")
        self.assertEqual(N.grade(pick, [])["status"], "open")

    def test_recap_written_once_and_test_week_not_counted(self):
        dir_ = self.store / "picks"
        pick = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS", "week": 9,
                "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        N.write(dir_ / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "picks": [pick]})
        N.write(dir_ / "2026-11-01.json", {"season": 2026, "week": 8, "test": True, "picks": [{**pick, "week": 8, "id": "t"}]})
        rows = stats_rows(9, [("TE1", "PHI", {"receiving_yards": 60})]) + stats_rows(8, [("TE1", "PHI", {"receiving_yards": 10})])
        # Before the week's night games are over, nothing is written.
        self.assertEqual(N.recap(self.data, self.store, rows, self.at("19:00"))["state"], "waiting")
        r = N.recap(self.data, self.store, rows, self.at("12:00", "2026-11-10"))
        self.assertEqual(r["state"], "done")
        doc = json.loads((dir_ / "week-09-recap.json").read_text())
        self.assertEqual(doc["season_record"]["w"], 1)
        self.assertEqual(doc["season_record"]["l"], 0)       # the week-8 test loss isn't counted
        self.assertIn("Season: 1-0", doc["post"]["main"])
        test_doc = json.loads((dir_ / "week-08-recap.json").read_text())
        self.assertTrue(test_doc["test"])
        self.assertNotIn("Season:", test_doc["post"]["main"])
        mtime = (dir_ / "week-09-recap.json").stat().st_mtime_ns
        N.recap(self.data, self.store, rows, self.at("13:00", "2026-11-10"))
        self.assertEqual((dir_ / "week-09-recap.json").stat().st_mtime_ns, mtime)


if __name__ == "__main__":
    unittest.main()
