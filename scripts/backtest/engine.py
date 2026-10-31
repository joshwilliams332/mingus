"""Multi-season backtest of the Mingus Football projection model.

features(season) -> one row per (player game, stat) from week 5 on, with only what was known before that game:
  his earlier games this season (values + opportunities), the opponent's per-game allowed to his position before that
  week, league averages before that week, the game's implied team total vs that week's average, and the spread.
project(row, P) -> (mean, sd) under settings P;  prob_over(...) -> chance of the over;  evaluate(rows, P) -> scores.
The line is the "typical" line Hoop Lab uses when no book line exists: floor(his average so far) + 0.5.
"""
import csv, math, os, statistics
from collections import defaultdict

H = os.environ.get("MINGUS_HIST", "hist/")  # folder with stats_<season>.csv and games.csv (see README.md)
POS = ("QB", "RB", "WR", "TE")
STATS = {"pass_yds": ("QB",), "rush_yds": ("QB", "RB"), "rec_yds": ("RB", "WR", "TE"), "rec": ("RB", "WR", "TE")}
OPP_OF = {"pass_yds": "att", "rush_yds": "car", "rec_yds": "tgt", "rec": "tgt"}
COLS = {"att": "attempts", "pass_yds": "passing_yards", "car": "carries", "rush_yds": "rushing_yards",
        "tgt": "targets", "rec": "receptions", "rec_yds": "receiving_yards"}
KEYS = list(COLS)
MINV = {"att": 20, "car": 5, "tgt": 3}
MIN_GAMES = 4
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}


def num(v):
    try:
        return float(v) if v not in ("", "NA") else 0.0
    except ValueError:
        return 0.0


_games = None
def games_for(season):
    global _games
    if _games is None:
        _games = list(csv.DictReader(open(H + "games.csv")))
    out = {}
    for g in _games:
        if int(g["season"]) != season or g["game_type"] != "REG":
            continue
        sp, tot = num(g["spread_line"]), num(g["total_line"])
        home, away = FIX.get(g["home_team"], g["home_team"]), FIX.get(g["away_team"], g["away_team"])
        out[(int(g["week"]), home)] = {"imp": (tot + sp) / 2, "fav": sp, "tot": tot}   # spread_line > 0: home favored
        out[(int(g["week"]), away)] = {"imp": (tot - sp) / 2, "fav": -sp, "tot": tot}
    return out


def features(season, path=None):
    rows = [r for r in csv.DictReader(open(path or f"{H}stats_{season}.csv"))
            if r["season_type"] == "REG" and r["position"] in POS]
    gl = games_for(season)
    players = defaultdict(list)
    dtot = defaultdict(lambda: defaultdict(float))      # (opp, pos, week) -> key totals
    for r in rows:
        wk, team, opp = int(r["week"]), FIX.get(r["team"], r["team"]), FIX.get(r["opponent_team"], r["opponent_team"])
        e = {"week": wk, "team": team, "opp": opp, **{k: num(r[c]) for k, c in COLS.items()}}
        players[(r["player_id"], r["position"])].append(e)
        t = dtot[(opp, r["position"], wk)]
        for k in KEYS:
            t[k] += e[k]
    weeks = sorted({k[2] for k in dtot})
    teams = sorted({k[0] for k in dtot})
    # Defense per game before each week: cum[(team, pos)][week] = (games, {key: total}) over weeks < week.
    played = defaultdict(set)
    for (opp, pos, wk) in dtot:
        played[opp].add(wk)
    before = {}
    for team in teams:
        for pos in POS:
            g, acc = 0, defaultdict(float)
            for wk in weeks:
                before[(team, pos, wk)] = (g, dict(acc))
                if wk in played[team]:
                    g += 1
                    for k in KEYS:
                        acc[k] += dtot.get((team, pos, wk), {}).get(k, 0.0)
    league = {}
    for wk in weeks:
        for pos in POS:
            per = [{k: v / g for k, v in tot.items()} for t in teams for (g, tot) in [before[(t, pos, wk)]] if g]
            league[(pos, wk)] = {k: statistics.mean(x.get(k, 0) for x in per) for k in KEYS} if per else None
    imp_avg = defaultdict(list)
    for (wk, team), v in gl.items():
        imp_avg[wk].append(v["imp"])
    out = []
    for (pid, pos), log in players.items():
        log.sort(key=lambda e: e["week"])
        for i, e in enumerate(log):
            if e["week"] < 5 or i < MIN_GAMES:
                continue
            prior = log[:i]
            lg = league.get((pos, e["week"]))
            g, dt = before[(e["opp"], pos, e["week"])]
            ctx = gl.get((e["week"], e["team"]))
            if not lg or not g or not ctx:
                continue
            dpg = {k: v / g for k, v in dt.items()}
            for st, poss in STATS.items():
                if pos not in poss:
                    continue
                ok = OPP_OF[st]
                opps = [p[ok] for p in prior]
                if (statistics.mean(opps) + statistics.mean(opps[-3:])) / 2 < MINV[ok]:
                    continue
                vals = [p[st] for p in prior]
                out.append({"season": season, "week": e["week"], "pid": pid, "pos": pos, "st": st, "vals": vals, "opps": opps,
                            "d_opp": dpg.get(ok, 0), "d_val": dpg.get(st, 0), "l_opp": lg[ok], "l_val": lg[st],
                            "imp": ctx["imp"], "imp_avg": statistics.mean(imp_avg[e["week"]]), "fav": ctx["fav"],
                            "actual": e[st], "line": math.floor(statistics.mean(vals)) + 0.5})
    return out


CURRENT = {"vol": "half3", "hl": None, "rate_hl": None, "K": 40, "ds": 0.5, "cap": 0.15, "de": 0.5, "is": 0.5, "sc": 0.01,
           "c": 0.97, "k": 1.3, "cv": {"pass_yds": 0.30, "rush_yds": 0.50, "rec_yds": 0.55, "rec": 0.45}, "pw": 4,
           "skew": {"rush_yds", "rec_yds", "rec"}, "cs": {}}


def wmean(xs, hl):
    if not hl:
        return statistics.mean(xs)
    n = len(xs)
    w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]
    return sum(a * b for a, b in zip(w, xs)) / sum(w)


def project(r, P):
    clamp = lambda x, lo, hi: min(hi, max(lo, x))
    opps, vals = r["opps"], r["vals"]
    if P["vol"] == "half3":
        vol = (statistics.mean(opps) + statistics.mean(opps[-3:])) / 2
    else:
        vol = wmean(opps, P["hl"])
    f_dv = clamp(1 + P["ds"] * (r["d_opp"] / r["l_opp"] - 1), 1 - P["cap"], 1 + P["cap"]) if r["l_opp"] else 1
    f_imp = clamp(1 + P["is"] * (r["imp"] / r["imp_avg"] - 1), 0.9, 1.1) if r["imp_avg"] else 1
    lean = clamp(P["sc"] * r["fav"], -0.06, 0.06)
    ok = OPP_OF[r["st"]]
    f_sc = 1 + lean if ok == "car" else 1 - lean
    lg_rate = r["l_val"] / r["l_opp"] if r["l_opp"] else 0
    hl = P["rate_hl"]
    n = len(vals)
    w = [0.5 ** ((n - 1 - i) / hl) for i in range(n)] if hl else [1.0] * n
    wv, wo = sum(a * b for a, b in zip(w, vals)), sum(a * b for a, b in zip(w, opps))
    rate = (wv + P["K"] * lg_rate) / (wo + P["K"])
    d_rate = r["d_val"] / r["d_opp"] if r["d_opp"] else lg_rate
    f_de = clamp(1 + P["de"] * (d_rate / lg_rate - 1), 1 - P["cap"], 1 + P["cap"]) if lg_rate else 1
    mean = vol * f_dv * f_imp * f_sc * rate * f_de * P["c"] * P["cs"].get(r["st"], 1.0)
    sd_obs = statistics.pstdev(vals)
    prior = P["cv"][r["st"]] * max(mean, 1)
    sd = P["k"] * math.sqrt((n * sd_obs ** 2 + P["pw"] * prior ** 2) / (n + P["pw"]))
    return mean, max(sd, 0.5)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_over(st, mean, sd, line, P):
    m = max(mean, 0.1)
    if st in P["skew"]:
        if line <= 0:
            return 1.0
        s2 = math.log(1 + (sd / m) ** 2)
        return 1 - ncdf((math.log(line) - (math.log(m) - s2 / 2)) / math.sqrt(s2))
    return 1 - ncdf((line - m) / sd)


def evaluate(rows, P, detail=False):
    b = ll = 0.0
    per = defaultdict(lambda: [0, 0.0, 0.0])
    calib = defaultdict(lambda: [0, 0])
    leans = {"over": [0, 0], "under": [0, 0]}
    for r in rows:
        m, sd = project(r, P)
        p = min(max(prob_over(r["st"], m, sd, r["line"], P), 1e-4), 1 - 1e-4)
        y = 1.0 if r["actual"] > r["line"] else 0.0
        b += (p - y) ** 2
        ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        s = per[r["st"]]; s[0] += 1; s[1] += (p - y) ** 2; s[2] += (0.5 - y) ** 2
        if detail:
            c = calib[min(int(p * 10), 9)]; c[0] += 1; c[1] += y
            if p >= 0.6: leans["over"][0] += 1; leans["over"][1] += y
            if p <= 0.4: leans["under"][0] += 1; leans["under"][1] += 1 - y
    n = len(rows)
    res = {"n": n, "brier": b / n, "logloss": ll / n,
           "by_stat": {k: {"n": v[0], "brier": v[1] / v[0], "coin": v[2] / v[0]} for k, v in per.items()}}
    if detail:
        res["calib"] = {k / 10: (v[0], v[1] / v[0]) for k, v in sorted(calib.items())}
        res["leans"] = {k: (v[0], v[1] / v[0] if v[0] else None) for k, v in leans.items()}
        res["over_rate"] = sum(1 for r in rows if r["actual"] > r["line"]) / n
    return res
