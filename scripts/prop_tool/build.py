#!/usr/bin/env python3
"""Build the "Mingus Prop Model" page (a private claude.ai artifact, not part of the site) for the upcoming week.

Data: the site's JSON (players / games / teams / meta), and from the data branch the model's own records (the weekly
scorecard, settings changes). Output: one self-contained HTML file (template.html with the data embedded), saved to
the data branch at model/prop-tool.html; the weekly Claude task republishes it to the artifact.

Usage: python3 scripts/prop_tool/build.py --data DIR --store DIR [--out FILE]
"""
import argparse
import copy
import json
import math
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nfl_picks as N  # noqa: E402

STATS = {"pass_yds": ("QB",), "rush_yds": ("QB", "RB"), "rec_yds": ("RB", "WR", "TE"), "rec": ("RB", "WR", "TE")}
MINV = {"att": 20, "car": 5, "tgt": 3}
X_KEYS = ("opp_key", "vol_base", "vol", "eff", "rate", "f_def_vol", "f_imp", "f_script", "f_inj", "f_def_eff", "out", "share3", "mean_adj")


def data_before(base, week):
    """The same data with only games before `week` (and no injury info), for replaying past weeks honestly."""
    d = copy.copy(base)
    d.players = [dict(p, log=[e for e in p["log"] if e["week"] < week], injury=None) for p in base.players]
    d.by_id = {p["id"]: p for p in d.players}
    d._dvp = None
    return d


def season_replay(base, last_week):
    """This season's Weeks 5..last_week replayed (earlier games only) against the typical line."""
    rows = []
    for wk in range(5, last_week + 1):
        d = data_before(base, wk)
        actual = {p["id"]: {e["week"]: e for e in p["log"]} for p in base.players}
        for g in (g for g in base.games if g["week"] == wk):
            for p in d.players:
                e = actual[p["id"]].get(wk)
                if p["team"] not in (g["home"], g["away"]) or not e or e.get("team") not in (g["home"], g["away"]):
                    continue
                for st, poss in STATS.items():
                    if p["pos"] not in poss:
                        continue
                    pr = N.projection(d, p, st, g, wk)
                    if not pr or pr["parts"]["vol_base"] < MINV[pr["parts"]["opp_key"]]:
                        continue
                    line = math.floor(statistics.mean(pr["vals"])) + 0.5
                    rows.append({"st": st, "p": N.chance_over(pr, line), "hit": (e.get(st) or 0) > line})
    if not rows:
        return None
    n = len(rows)
    b = lambda rs, f: sum((f(r) - r["hit"]) ** 2 for r in rs) / len(rs)
    leans = {}
    for side, cond in (("over", lambda r: r["p"] >= 0.6), ("under", lambda r: r["p"] <= 0.4)):
        x = [r for r in rows if cond(r)]
        leans[side] = {"n": len(x), "hit": round(sum((r["hit"] if side == "over" else not r["hit"]) for r in x) / len(x), 3) if x else None}
    by_stat = {st: {"n": len(x), "brier": round(b(x, lambda r: r["p"]), 4), "brier_coin": round(b(x, lambda r: 0.5), 4)}
               for st in STATS for x in [[r for r in rows if r["st"] == st]] if x}
    return {"n": n, "weeks": [5, last_week], "brier": round(b(rows, lambda r: r["p"]), 4), "brier_coin": round(b(rows, lambda r: 0.5), 4),
            "leans": leans, "by_stat": by_stat, "over_rate": round(sum(r["hit"] for r in rows) / n, 3)}


def payload(data, store):
    upcoming = [g for g in data.games if g.get("home_score") is None and g.get("type", "REG") == "REG"]
    week = min(g["week"] for g in upcoming) if upcoming else max(g["week"] for g in data.games)
    games = sorted((g for g in upcoming if g["week"] == week), key=N.kickoff)
    # Who started each team's last game at QB (a returning starter or a backup gets a "check starter" tag instead).
    last_qb = {}
    for p in data.players:
        if p["pos"] == "QB":
            for e in p["log"]:
                if (e.get("att") or 0) >= 10 and e["week"] >= last_qb.get(e["team"], (0, None))[0]:
                    last_qb[e["team"]] = (e["week"], p["id"])
    proj = []
    for g in games:
        for p in data.players:
            if p["team"] not in (g["home"], g["away"]) or not p["log"]:
                continue
            for st, poss in STATS.items():
                if p["pos"] not in poss:
                    continue
                pr = N.projection(data, p, st, g, week)
                if not pr or pr["parts"]["vol_base"] < MINV[pr["parts"]["opp_key"]]:
                    continue
                x = pr["parts"]
                proj.append({"gid": g["id"], "pid": p["id"], "name": p["name"], "pos": p["pos"], "team": p["team"], "opp": pr["opp"],
                             "st": st, "mean": pr["mean"], "sd": pr["sd"], "vals": pr["vals"][-8:],
                             "weeks": [e["week"] for e in p["log"] if e["week"] < week][-8:],
                             "inj": (p.get("injury") or {}).get("status"), "rank": pr["opp_rank"], "vrank": pr["vol_rank"],
                             "check_qb": p["pos"] == "QB" and last_qb.get(p["team"], (0, None))[1] != p["id"],
                             "x": {k: x[k] for k in X_KEYS}, "ctx": pr["ctx"], "source": pr["source"]})
    played = [g["week"] for g in data.games if g.get("home_score") is not None]
    card = N.read(Path(store) / "model" / "scorecard.json", {}) or {}
    return {"week": week, "built": data.meta.get("built_at"),
            "games": [{"id": g["id"], "away": g["away"], "home": g["home"], "date": g["date"], "time": g["time"],
                       "spread": g.get("home_spread"), "total": g.get("total"), "imp": [g.get("away_implied"), g.get("home_implied")]} for g in games],
            "proj": proj, "backtest": season_replay(data, max(played) if played else 4),
            "history": json.loads((HERE / "backtest_2021_2025.json").read_text()),
            "scorecard": card.get("weeks", {}), "changes": N.read(Path(store) / "model" / "settings-history.json", []) or [],
            "settings_note": (N.read(Path(store) / "model" / "settings.json") or {}).get("why")}


def render(p):
    t = (HERE / "template.html").read_text()
    return t.replace("__DATA__", json.dumps(p, separators=(",", ":")).replace("</", "<\\/"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    N.apply_settings(a.store)
    p = payload(N.Data(a.data), a.store)
    out = Path(a.out or Path(a.store) / "model" / "prop-tool.html")
    # Rebuild only when something a reader would notice changed (new week, newly scored week, new settings), so the
    # data branch doesn't collect a 200 KB copy on every run.
    stamp = {"week": p["week"], "scored": sorted(p["scorecard"]), "changes": len(p["changes"]), "props": len(p["proj"])}
    info_file = Path(a.store) / "model" / "prop-tool.json"
    old = N.read(info_file, {}) or {}
    if not a.out and out.exists() and old.get("stamp") == stamp:
        print(f"Prop tool: week {p['week']} unchanged, not rebuilt")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(p))
    N.write(info_file, {"week": p["week"], "built": p["built"], "props": len(p["proj"]), "games": len(p["games"]), "stamp": stamp})
    print(f"Prop tool: week {p['week']}, {len(p['proj'])} props in {len(p['games'])} games -> {out}")


if __name__ == "__main__":
    main()
