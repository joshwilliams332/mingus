"""Per (season, week, team, player): red-zone / inside-10 / inside-5 carries and targets from nflverse pbp,
plus team totals of the same, so shares can be computed. Output: td/rz_<season>.pkl"""
import csv, gzip, sys, pickle
from collections import defaultdict
S = sys.argv[1]; season = int(sys.argv[2])
f = gzip.open(f"{S}/pbp/pbp_{season}.csv.gz", "rt")
r = csv.DictReader(f)
pl = defaultdict(lambda: defaultdict(int)); tm = defaultdict(lambda: defaultdict(int))
def num(x):
    try: return float(x)
    except: return None
for row in r:
    if row["season_type"] != "REG": continue
    y = num(row["yardline_100"])
    if y is None or y > 20: continue
    wk = int(row["week"]); team = row["posteam"]
    if not team: continue
    kinds = []
    if row["rush_attempt"] == "1" and row["rusher_player_id"] not in ("", "NA"):
        kinds.append(("car", row["rusher_player_id"]))
    if row["pass_attempt"] == "1" and row["receiver_player_id"] not in ("", "NA") and row.get("sack") != "1":
        kinds.append(("tgt", row["receiver_player_id"]))
    for k, pid in kinds:
        for zone, lim in (("rz", 20), ("i10", 10), ("i5", 5)):
            if y <= lim:
                pl[(wk, team, pid)][f"{zone}_{k}"] += 1
                tm[(wk, team)][f"{zone}_{k}"] += 1
pickle.dump({"pl": {k: dict(v) for k, v in pl.items()}, "tm": {k: dict(v) for k, v in tm.items()}},
            open(f"{S}/td/rz_{season}.pkl", "wb"))
print(season, len(pl), len(tm))
