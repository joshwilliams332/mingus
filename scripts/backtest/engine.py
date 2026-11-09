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
TF_KEY = {"att": "tfa", "car": "tfc", "tgt": "tft"}   # team-first weight by opportunity type
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


_pfr = None
def snaps_for(season):
    """(gsis player_id, week) -> offensive snap share that game, from snaps_<season>.csv (nflverse snap_counts) matched
    through every roster_<season>.csv in H (pfr id -> gsis id). Empty if the files aren't there."""
    global _pfr
    if _pfr is None:
        _pfr = {}
        for f in sorted(os.listdir(H)):
            if f.startswith("roster_") and f.endswith(".csv"):
                for r in csv.DictReader(open(H + f)):
                    if r.get("pfr_id") and r.get("gsis_id"):
                        _pfr[r["pfr_id"]] = r["gsis_id"]
    out, f = {}, f"{H}snaps_{season}.csv"
    if os.path.exists(f):
        for r in csv.DictReader(open(f)):
            g = _pfr.get(r["pfr_player_id"])
            if g and r["game_type"] == "REG":
                out[(g, int(r["week"]))] = num(r["offense_pct"])
    return out


def features(season, path=None):
    snaps = snaps_for(season)
    rows = [r for r in csv.DictReader(open(path or f"{H}stats_{season}.csv"))
            if r["season_type"] == "REG" and r["position"] in POS]
    gl = games_for(season)
    players = defaultdict(list)
    dtot = defaultdict(lambda: defaultdict(float))      # (opp, pos, week) -> key totals
    for r in rows:
        wk, team, opp = int(r["week"]), FIX.get(r["team"], r["team"]), FIX.get(r["opponent_team"], r["opponent_team"])
        e = {"week": wk, "team": team, "opp": opp, "snap": snaps.get((r["player_id"], wk)),
             **{k: num(r[c]) for k, c in COLS.items()}}
        players[(r["player_id"], r["position"])].append(e)
        t = dtot[(opp, r["position"], wk)]
        for k in KEYS:
            t[k] += e[k]
    weeks = sorted({k[2] for k in dtot})
    teams = sorted({k[0] for k in dtot})
    # Team first (Nov 9, 2026): each team's volume per game (all its QB/RB/WR/TE) and each player's share of it. Who
    # plays this game is only what's known before kickoff: on the team's active roster that week
    # (roster_weekly_<season>.csv, status ACT; game-day inactives are INA from 2021) and not listed Out / Doubtful on
    # that week's injury report (injuries_<season>.csv). Without those files every teammate counts.
    ttot = defaultdict(lambda: defaultdict(float))
    by_team = defaultdict(set)
    for key, log in players.items():
        for e in log:
            for k in ("att", "car", "tgt"):
                ttot[(e["team"], e["week"])][k] += e[k]
            by_team[e["team"]].add(key)
    tweeks = defaultdict(list)
    for (team, wk) in sorted(ttot):
        tweeks[team].append(wk)
    act, ruled_out = defaultdict(set), set()
    if os.path.exists(f"{H}roster_weekly_{season}.csv"):
        for r in csv.DictReader(open(f"{H}roster_weekly_{season}.csv")):
            if r["status"] == "ACT" and r["game_type"] == "REG" and r["week"]:
                act[(FIX.get(r["team"], r["team"]), int(r["week"]))].add(r["gsis_id"])
    if os.path.exists(f"{H}injuries_{season}.csv"):
        for r in csv.DictReader(open(f"{H}injuries_{season}.csv")):
            if r["report_status"] in ("Out", "Doubtful") and r["game_type"] == "REG":
                ruled_out.add((r["gsis_id"], int(r["week"])))
    def shares(log, upto, ok):
        """His share of his team's opportunities in each game before `upto`."""
        return [e[ok] / ttot[(e["team"], e["week"])][ok] for e in log if e["week"] < upto and ttot[(e["team"], e["week"])][ok]]
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
                team_opps = [ttot[(e["team"], w)][ok] for w in tweeks[e["team"]] if w < e["week"]]
                my_sh = shares(prior, e["week"], ok)
                mates = []      # teammates who may play: (their shares here, team games they've missed since)
                tw = [w for w in tweeks[e["team"]] if w < e["week"]]
                listed = act.get((e["team"], e["week"]))
                for key in by_team[e["team"]]:
                    if key[0] == pid or (listed is not None and key[0] not in listed) or (key[0], e["week"]) in ruled_out:
                        continue
                    here = [x for x in players[key] if x["team"] == e["team"] and x["week"] < e["week"]]
                    sh = shares(here, e["week"], ok)
                    if sh:
                        mates.append((sh, sum(1 for w in tw if w > here[-1]["week"])))
                out.append({"team_opps": team_opps, "my_sh": my_sh, "mates": mates, "season": season, "week": e["week"], "pid": pid, "pos": pos, "st": st, "vals": vals, "opps": opps,
                            "snaps": [p["snap"] for p in prior],
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


def partial_games(opps, vals, snaps, mode, frac, cap=2.0, keep=3):
    """Games where he played well under his usual snap share (an early injury exit, a blowout) say little about his
    role. mode "drop": leave out games below frac x his median snap share (keeping at least `keep` games);
    "scale": count them as a full game (opportunities and stats x median / that game's share, at most x cap)."""
    known = sorted(s for s in snaps if s)
    if not mode or len(known) < 2:
        return opps, vals
    med = known[len(known) // 2] if len(known) % 2 else (known[len(known) // 2 - 1] + known[len(known) // 2]) / 2
    short = [bool(s is not None and s < frac * med) for s in snaps]
    if mode == "drop":
        if len(opps) - sum(short) < keep:
            return opps, vals
        return [o for o, x in zip(opps, short) if not x], [v for v, x in zip(vals, short) if not x]
    f = [min(cap, med / max(s, 0.01)) if x else 1.0 for s, x in zip(snaps, short)]
    return [o * k for o, k in zip(opps, f)], [v * k for v, k in zip(vals, f)]


def project(r, P):
    clamp = lambda x, lo, hi: min(hi, max(lo, x))
    opps, vals = r["opps"], r["vals"]
    if P.get("snap"):
        opps, vals = partial_games(opps, vals, r.get("snaps") or [None] * len(opps), *P["snap"])
    if P["vol"] == "half3":
        vol = (statistics.mean(opps) + statistics.mean(opps[-3:])) / 2
    else:
        vol = wmean(opps, P["hl"])
    tf = P.get(TF_KEY[OPP_OF[r["st"]]], 0)
    if tf and r.get("team_opps") and r.get("my_sh"):
        # Team first: the team's recent volume (half-life "thl" games), split among the players who may play this game
        # by their recent shares (re-scaled to add up to 1), blended with his own recent volume by tf.
        team_vol = wmean(r["team_opps"], P.get("thl") or P["hl"])
        mine = wmean(r["my_sh"], P["hl"])
        others = sum(wmean(sh, P["hl"]) for sh, gap in r["mates"] if gap <= P.get("tgap", 1))
        if mine + others:
            vol = tf * team_vol * mine / (mine + others) + (1 - tf) * vol
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
    K = P.get("Ks", {}).get(f'{r["st"]}:{r["pos"]}', P.get("Ks", {}).get(r["st"], P["K"]))   # per stat / position
    rate = (wv + K * lg_rate) / (wo + K)
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


SPREAD_LINES = (0.6, 0.8, 1.0, 1.2, 1.4)   # x his average so far, each rounded to a .5 line


def multi_lines(r):
    """Five lines around his average (Nov 9, 2026). One line at floor(average) + 0.5 mostly tests the shape of the
    range and rewards projecting high (the weekly tuner pushed the overall multiplier to 1.06 that way); scoring the
    over at several lines grades the whole projected range, like a CRPS."""
    a = statistics.mean(r["vals"])
    return sorted({math.floor(a * f) + 0.5 for f in SPREAD_LINES})


def evaluate_multi(rows, P):
    """Average Brier of the over at the multi_lines() lines, plus the projection's average miss (RMSE) and bias % by
    stat. Lower Brier / RMSE is better; bias 0 is unbiased."""
    b = wsum = 0.0
    per = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])        # n, brier sum, sq err, projected, actual
    for r in rows:
        w = r.get("w", 1.0)
        m, sd = project(r, P)
        lines = multi_lines(r)
        s = sum((min(max(prob_over(r["st"], m, sd, ln, P), 1e-4), 1 - 1e-4) - (1.0 if r["actual"] > ln else 0.0)) ** 2
                for ln in lines) / len(lines)
        b += w * s
        wsum += w
        x = per[r["st"]]; x[0] += 1; x[1] += s; x[2] += (m - r["actual"]) ** 2; x[3] += m; x[4] += r["actual"]
    if not rows:
        return {"n": 0, "brier": None, "by_stat": {}}
    return {"n": len(rows), "brier": b / wsum,
            "by_stat": {k: {"n": v[0], "brier": v[1] / v[0], "rmse": math.sqrt(v[2] / v[0]),
                            "bias_pct": 100 * (v[3] / v[4] - 1) if v[4] else 0.0} for k, v in per.items()}}


def evaluate(rows, P, detail=False):
    """Brier score (and log loss) of the chance of the over vs the typical line. Rows may carry a weight "w"
    (the weekly review counts this season's games more than past seasons')."""
    b = ll = wsum = 0.0
    per = defaultdict(lambda: [0, 0.0, 0.0])
    calib = defaultdict(lambda: [0, 0])
    leans = {"over": [0, 0], "under": [0, 0]}
    for r in rows:
        w = r.get("w", 1.0)
        m, sd = project(r, P)
        p = min(max(prob_over(r["st"], m, sd, r["line"], P), 1e-4), 1 - 1e-4)
        y = 1.0 if r["actual"] > r["line"] else 0.0
        b += w * (p - y) ** 2
        ll += w * -(y * math.log(p) + (1 - y) * math.log(1 - p))
        wsum += w
        s = per[r["st"]]; s[0] += 1; s[1] += (p - y) ** 2; s[2] += (0.5 - y) ** 2
        if detail:
            c = calib[min(int(p * 10), 9)]; c[0] += 1; c[1] += y
            if p >= 0.6: leans["over"][0] += 1; leans["over"][1] += y
            if p <= 0.4: leans["under"][0] += 1; leans["under"][1] += 1 - y
    n = len(rows)
    if not n:
        return {"n": 0, "brier": None, "logloss": None, "by_stat": {}}
    res = {"n": n, "brier": b / wsum, "logloss": ll / wsum,
           "by_stat": {k: {"n": v[0], "brier": v[1] / v[0], "coin": v[2] / v[0]} for k, v in per.items()}}
    if detail:
        res["calib"] = {k / 10: (v[0], v[1] / v[0]) for k, v in sorted(calib.items())}
        res["leans"] = {k: (v[0], v[1] / v[0] if v[0] else None) for k, v in leans.items()}
        res["over_rate"] = sum(1 for r in rows if r["actual"] > r["line"]) / n
    return res
