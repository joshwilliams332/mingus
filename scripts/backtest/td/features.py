"""Anytime-TD backtest features: one row per (player game) from week 4 on, using only earlier games that season."""
import csv, pickle, sys, math, statistics
from collections import defaultdict
S = sys.argv[1]
H = f"{S}/hist/"
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}
POS = ("QB", "RB", "WR", "TE")
def num(v):
    try: return float(v) if v not in ("", "NA") else 0.0
    except ValueError: return 0.0
games = list(csv.DictReader(open(H + "games.csv")))
def lines(season):
    out = {}
    for g in games:
        if int(g["season"]) != season or g["game_type"] != "REG": continue
        sp, tot = num(g["spread_line"]), num(g["total_line"])
        h, a = FIX.get(g["home_team"], g["home_team"]), FIX.get(g["away_team"], g["away_team"])
        out[(int(g["week"]), h)] = (tot + sp) / 2; out[(int(g["week"]), a)] = (tot - sp) / 2
    return out
KEYS = ("car", "tgt", "rz_car", "i10_car", "i5_car", "rz_tgt", "i10_tgt", "td", "t_i10_car", "t_rz_tgt", "t_rz_car", "t_i5_car")
def wavg(xs, hl=4):
    n = len(xs); w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]
    return sum(a * b for a, b in zip(w, xs)) / sum(w)
rows_out = []
for season in range(2021, 2027):
    rz = pickle.load(open(f"{S}/td/rz_{season}.pkl", "rb")); pl, tm = rz["pl"], rz["tm"]
    imp = lines(season)
    wk_imp = defaultdict(list)
    for (w, t), v in imp.items(): wk_imp[w].append(v)
    stats = [r for r in csv.DictReader(open(f"{H}stats_{season}.csv")) if r["season_type"] == "REG" and r["position"] in POS]
    logs = defaultdict(list); dtd = defaultdict(float); dgames = defaultdict(set)
    for r in stats:
        wk, team, opp = int(r["week"]), FIX.get(r["team"], r["team"]), FIX.get(r["opponent_team"], r["opponent_team"])
        td = num(r["rushing_tds"]) + num(r["receiving_tds"])
        u = pl.get((wk, r["team"], r["player_id"])) or pl.get((wk, team, r["player_id"])) or {}
        t = tm.get((wk, r["team"])) or tm.get((wk, team)) or {}
        e = {"week": wk, "team": team, "opp": opp, "car": num(r["carries"]), "tgt": num(r["targets"]), "td": td,
             **{k: u.get(k, 0) for k in ("rz_car", "i10_car", "i5_car", "rz_tgt", "i10_tgt")},
             "t_i10_car": t.get("i10_car", 0), "t_rz_tgt": t.get("rz_tgt", 0), "t_rz_car": t.get("rz_car", 0), "t_i5_car": t.get("i5_car", 0)}
        logs[(r["player_id"], r["position"], r["player_display_name"])].append(e)
        dtd[(opp, r["position"], wk)] += td; dgames[opp].add(wk)
    weeks = sorted({w for (_, _, w) in dtd})
    # defense TDs allowed per game to a position, before week w; league average of that
    def d_before(team, pos, w):
        g = [x for x in dgames[team] if x < w]
        return (sum(dtd.get((team, pos, x), 0) for x in g) / len(g)) if g else None
    lg = {}
    for w in weeks:
        for pos in POS:
            vals = [v for t in dgames for v in [d_before(t, pos, w)] if v is not None]
            lg[(pos, w)] = statistics.mean(vals) if vals else None
    for (pid, pos, name), log in logs.items():
        log.sort(key=lambda e: e["week"])
        for i, e in enumerate(log):
            if i < 3 or e["week"] < 4: continue
            prior = log[:i]
            f = {k: wavg([p[k] for p in prior]) for k in KEYS}
            if f["car"] + f["tgt"] < 2: continue
            d, l = d_before(e["opp"], pos, e["week"]), lg.get((pos, e["week"]))
            im = imp.get((e["week"], e["team"]))
            if d is None or not l or im is None: continue
            rows_out.append({"season": season, "week": e["week"], "pid": pid, "name": name, "pos": pos, "team": e["team"], "opp": e["opp"],
                             **f, "n": i, "imp": im, "imp_avg": statistics.mean(wk_imp[e["week"]]),
                             "def_td": d, "lg_td": l, "y": 1 if e["td"] > 0 else 0, "tds": e["td"]})
pickle.dump(rows_out, open(f"{S}/td/rows.pkl", "wb"))
from collections import Counter
print(len(rows_out), Counter(r["season"] for r in rows_out), "TD rate %.3f" % (sum(r["y"] for r in rows_out) / len(rows_out)))
