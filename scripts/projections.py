#!/usr/bin/env python3
"""Mingus Football's projection model: what each player should do this week, and how sure we are.

Used by the weekly accuracy check (scripts/model_review.py) and tested in tests/test_projections.py. For every regular
it projects passing, rushing and receiving yards and catches as opportunities x efficiency, with a game-to-game spread,
and each player's chance to score a touchdown. Settings are tuned on 2021-2025 and checked on 2026 (scripts/backtest/);
the weekly review only changes them when the change would have done better on games it hadn't seen.
"""

import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo is in every Python we run on
    ET = None

STAT = {"pass_yds": ("Passing yards", "pass yds"), "rush_yds": ("Rushing yards", "rush yds"),
        "rec_yds": ("Receiving yards", "rec yds"), "rec": ("Receptions", "catches")}
# Each stat = an opportunity (attempts, carries, targets) x what he does with it.
OPP_OF = {"pass_yds": "att", "rush_yds": "car", "rec_yds": "tgt", "rec": "tgt"}
OPP_WORD = {"att": "pass attempts", "car": "carries", "tgt": "targets"}
DVP_KEYS = list(STAT) + ["att", "car", "tgt"]
NIGHT_HOUR = 19            # kickoff at 7 PM ET or later = a night game
MIN_GAMES = 4              # games played this season before we project him

# Settings tuned Oct 31, 2026 on 2021-2025 (22,000 player-games, each projected only from earlier games that season,
# against a "typical" mark = floor(his average so far) + 0.5, i.e. does he beat his usual game), then tested
# untouched on 2026 Weeks 5-8: Brier 0.2444 (first calibration) -> 0.2398; the very first version scored 0.2594 and a
# coin 0.2500. Better than the first calibration in every season. What the data said:
#   - weight recent games more: opportunities decay with a 4-game half-life, efficiency with a 6-game half-life;
#   - lean less on matchups: the defense's opportunity effect at a quarter strength (capped ±10%), its per-play effect
#     dropped (no help), the team-total effect at a quarter strength, the game-script effect dropped;
#   - steady efficiency toward the league with 20 opportunities, not 40;
#   - wider typical spreads (PRIOR_CV, counted as 8 games), x1.15 overall; mean x1.03 (passing yards x0.93).
VOL_HALF_LIFE = 4          # games
RATE_HALF_LIFE = 6         # games
RATE_PAD = 20              # opportunities of league-average efficiency blended in
DEF_VOL_STRENGTH = 0.25
DEF_EFF_STRENGTH = 0.0
DEF_CAP = (0.9, 1.1)
IMP_STRENGTH = 0.25
SCRIPT_PER_POINT = 0.0     # tested 0.5-2% per point of spread: no help
PRIOR_CV = {"pass_yds": 0.70, "rush_yds": 0.50, "rec_yds": 0.70, "rec": 0.60}  # typical game-to-game spread / mean
PRIOR_WEIGHT = 8           # the spread estimate counts the typical spread as this many games
MEAN_ADJ = {"pass_yds": 1.03 * 0.9, "rush_yds": 1.03, "rec_yds": 1.03, "rec": 1.03}
SPREAD_ADJ = 1.15
SKEWED = {"rush_yds", "rec_yds", "rec"}


# ---------------------------------------------------------------- small helpers

def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))


def kickoff(game):
    """A game's kickoff as an aware datetime (games.json keeps ET date + 24h time)."""
    d = datetime.strptime(f"{game['date']} {game.get('time') or '13:00'}", "%Y-%m-%d %H:%M")
    return d.replace(tzinfo=ET)


def is_night(game):
    return int((game.get("time") or "13:00")[:2]) >= NIGHT_HOUR


def slot_label(game):
    """TNF / SNF / MNF / Saturday night for night games, else the weekday."""
    k = kickoff(game)
    if not is_night(game):
        return k.strftime("%A")
    return {3: "TNF", 6: "SNF", 0: "MNF", 5: "Saturday night"}.get(k.weekday(), k.strftime("%A night"))


def norm_name(name):
    """'Amon-Ra St. Brown' / 'Kenneth Walker III' -> comparable keys."""
    s = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", s.strip())
    return re.sub(r"\s+", " ", s)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------- the data

class Data:
    """players.json / games.json / teams.json / meta.json, indexed."""

    def __init__(self, folder):
        folder = Path(folder)
        self.meta = read(folder / "meta.json", {})
        self.players = read(folder / "players.json", [])
        self.games = read(folder / "games.json", [])
        self.teams = read(folder / "teams.json", {})
        self.by_id = {p["id"]: p for p in self.players}
        self.game = {g["id"]: g for g in self.games}
        self.full_name = {abbr: f"{t['city']} {t['nickname']}" for abbr, t in self.teams.items()}
        self._dvp = None

    def dvp(self):
        """Per game allowed by each defense to each position: {team: {pos: {stat: per game}}}, and league averages."""
        if self._dvp:
            return self._dvp
        tot, weeks = {}, {}
        for p in self.players:
            if p["pos"] not in ("QB", "RB", "WR", "TE"):
                continue
            for e in p["log"]:
                t = tot.setdefault(e["opp"], {}).setdefault(p["pos"], {})
                for k in DVP_KEYS:
                    t[k] = t.get(k, 0) + (e.get(k) or 0)
                weeks.setdefault(e["opp"], set()).add(e["week"])
        per = {team: {pos: {k: v / len(weeks[team]) for k, v in st.items()} for pos, st in byp.items()}
               for team, byp in tot.items()}
        league = {}
        for pos in ("QB", "RB", "WR", "TE"):
            league[pos] = {k: statistics.mean(per[t].get(pos, {}).get(k, 0) for t in per) for k in DVP_KEYS} if per else {}
        ranks = {}
        for pos in ("QB", "RB", "WR", "TE"):
            for k in DVP_KEYS:
                vals = sorted((per[t].get(pos, {}).get(k, 0) for t in per), reverse=True)
                for t in per:
                    v = per[t].get(pos, {}).get(k, 0)
                    ranks[(t, pos, k)] = (1 + sum(1 for x in vals if x > v), len(vals))
        self._dvp = (per, league, ranks)
        return self._dvp


# ---------------------------------------------------------------- the projection

def team_context(data, team, game):
    """This game's implied points for the team vs the week's average, and how many points it's favored by."""
    wk = [g for g in data.games if g["week"] == game["week"] and g.get("home_implied") is not None]
    imps = [g[k] for g in wk for k in ("home_implied", "away_implied")]
    home = game["home"] == team
    imp = game.get("home_implied" if home else "away_implied")
    spread = game.get("home_spread")
    fav_by = (-spread if home else spread) if spread is not None else 0
    rank = 1 + sum(1 for x in imps if imp is not None and x > imp) if imp is not None else None
    return {"implied": imp, "avg": statistics.mean(imps) if imps else None, "rank": rank, "of": len(imps), "fav_by": fav_by}


def openings(data, player, game, opp_key):
    """Volume freed up by teammates ruled out (Out / Doubtful) who've been getting the same kind of work.
    Returns (boost factor, [names]). Only 60% of their volume is assumed to move, spread over who's left by share.
    Only a new absence counts: the teammate must have played in his team's last game. Someone who's been out longer
    (e.g. on injured reserve) has already been missing from the games the others' recent averages come from, so
    counting him again would double his work (Nov 9, 2026)."""
    if opp_key == "att":
        return 1.0, []
    mates = [p for p in data.players if p["team"] == player["team"] and p["id"] != player["id"] and p["pos"] in ("RB", "WR", "TE", "QB")]
    def mine(p):
        return [e for e in p["log"] if e["week"] < game["week"] and (e.get("team") or p["team"]) == p["team"]]
    def recent(p):
        log = mine(p)[-3:]
        return statistics.mean(e.get(opp_key) or 0 for e in log) if log else 0
    team_last = max((e["week"] for p in mates + [player] for e in mine(p)), default=None)
    def new_absence(p):
        log = mine(p)
        return bool(log) and log[-1]["week"] == team_last
    out = [p for p in mates if (p.get("injury") or {}).get("status") in ("Out", "Doubtful") and new_absence(p)
           and recent(p) >= (4 if opp_key == "tgt" else 6)]
    if not out:
        return 1.0, []
    missing = sum(recent(p) for p in out)
    active = recent(player) + sum(recent(p) for p in mates if p not in out)
    return (min(1.25, 1 + 0.6 * missing / active) if active else 1.0), [p["name"] for p in out]


def model_settings():
    """The current settings in the backtest engine's format (scripts/backtest/engine.py), for saving and comparing."""
    return {"vol": "exp", "hl": VOL_HALF_LIFE, "rate_hl": RATE_HALF_LIFE, "K": RATE_PAD, "ds": DEF_VOL_STRENGTH,
            "de": DEF_EFF_STRENGTH, "cap": round(DEF_CAP[1] - 1, 4), "is": IMP_STRENGTH, "sc": SCRIPT_PER_POINT,
            "c": round(MEAN_ADJ["rec_yds"], 4), "cs": {k: round(v / MEAN_ADJ["rec_yds"], 4) for k, v in MEAN_ADJ.items() if abs(v - MEAN_ADJ["rec_yds"]) > 1e-9},
            "k": SPREAD_ADJ, "cv": dict(PRIOR_CV), "pw": PRIOR_WEIGHT, "skew": sorted(SKEWED)}


def apply_settings(store):
    """Use the settings the weekly model review adopted (store/model/settings.json on the data branch), if any.
    The file holds the engine's format plus a note of when and why it was adopted; anything missing keeps the default."""
    global VOL_HALF_LIFE, RATE_HALF_LIFE, RATE_PAD, DEF_VOL_STRENGTH, DEF_EFF_STRENGTH, DEF_CAP, IMP_STRENGTH
    global SCRIPT_PER_POINT, MEAN_ADJ, SPREAD_ADJ, PRIOR_CV, PRIOR_WEIGHT, SKEWED
    doc = read(Path(store) / "model" / "settings.json")
    P = (doc or {}).get("settings")
    if not P:
        return None
    VOL_HALF_LIFE = P.get("hl", VOL_HALF_LIFE)
    RATE_HALF_LIFE = P.get("rate_hl", RATE_HALF_LIFE)
    RATE_PAD = P.get("K", RATE_PAD)
    DEF_VOL_STRENGTH = P.get("ds", DEF_VOL_STRENGTH)
    DEF_EFF_STRENGTH = P.get("de", DEF_EFF_STRENGTH)
    if "cap" in P:
        DEF_CAP = (1 - P["cap"], 1 + P["cap"])
    IMP_STRENGTH = P.get("is", IMP_STRENGTH)
    SCRIPT_PER_POINT = P.get("sc", SCRIPT_PER_POINT)
    if "c" in P:
        MEAN_ADJ = {st: P["c"] * (P.get("cs") or {}).get(st, 1.0) for st in STAT}
    SPREAD_ADJ = P.get("k", SPREAD_ADJ)
    PRIOR_CV = {**PRIOR_CV, **(P.get("cv") or {})}
    PRIOR_WEIGHT = P.get("pw", PRIOR_WEIGHT)
    if "skew" in P:
        SKEWED = set(P["skew"])
    return doc


def decay_weights(n, half_life):
    """Weights for n games, oldest first: the latest counts 1, a game half_life games earlier counts 1/2."""
    return [0.5 ** ((n - 1 - i) / half_life) for i in range(n)]


def projection(data, player, stat, game, week):
    """Our expected value and spread for a player's stat in this game, or None without enough history.

    The Mingus model: opportunities x efficiency, with the settings tuned on 2021-2025 (see VOL_HALF_LIFE).
      Opportunities (his pass attempts, carries or targets): a recency-weighted average (4-game half-life), then
        x the defense: how many of those it allows to his position vs the league (quarter strength, 0.9-1.1)
        x the game: the team's implied points vs the week's average (quarter strength, 0.9-1.1)
        x injury openings: a share of the work teammates ruled out leave behind (see openings(); not backtested,
          since past injury reports aren't in the data).
      Efficiency (yards per attempt / carry / target, or catch rate): his recency-weighted rate (6-game half-life)
        steadied toward the position's league rate (counted as 20 opportunities).
    Times MEAN_ADJ (calibration). When the site has Sleeper's projection for the stat, the mean is half Sleeper, half
    ours (Sleeper sees news and depth charts). Spread: his game-to-game spread steadied with a typical one."""
    log = [e for e in player["log"] if e["week"] < week]
    if len(log) < MIN_GAMES:
        return None
    pos, ok = player["pos"], OPP_OF[stat]
    vals = [e.get(stat) or 0 for e in log]
    opps = [e.get(ok) or 0 for e in log]
    opp = game["home"] if player["team"] == game["away"] else game["away"]
    per, league, ranks = data.dvp()
    adj = lambda x, strength: min(DEF_CAP[1], max(DEF_CAP[0], 1 + strength * (x - 1)))

    wv = decay_weights(len(opps), VOL_HALF_LIFE)
    vol_base = sum(w * o for w, o in zip(wv, opps)) / sum(wv)
    d_al, d_lg = per.get(opp, {}).get(pos, {}), league.get(pos, {})
    f_def_vol = adj(d_al.get(ok, 0) / d_lg[ok], DEF_VOL_STRENGTH) if d_lg.get(ok) else 1.0
    ctx = team_context(data, player["team"], game)
    f_imp = adj(ctx["implied"] / ctx["avg"], IMP_STRENGTH) if ctx["implied"] and ctx["avg"] else 1.0
    lean = max(-0.06, min(0.06, SCRIPT_PER_POINT * ctx["fav_by"]))
    f_script = 1 + lean if ok == "car" else 1 - lean if ok in ("att", "tgt") else 1.0
    f_inj, out_names = openings(data, player, game, ok)
    vol = vol_base * f_def_vol * f_imp * f_script * f_inj

    wr = decay_weights(len(vals), RATE_HALF_LIFE)
    w_val, w_opp = sum(w * v for w, v in zip(wr, vals)), sum(w * o for w, o in zip(wr, opps))
    lg_rate = (d_lg.get(stat, 0) / d_lg[ok]) if d_lg.get(ok) else (w_val / w_opp if w_opp else 0)
    rate = (w_val + RATE_PAD * lg_rate) / (w_opp + RATE_PAD)
    def_rate = (d_al.get(stat, 0) / d_al[ok]) if d_al.get(ok) else lg_rate
    f_def_eff = adj(def_rate / lg_rate, DEF_EFF_STRENGTH) if lg_rate else 1.0
    eff = rate * f_def_eff
    mingus = vol * eff * MEAN_ADJ[stat]

    sleeper = (((player.get("proj") or {}).get("sleeper") or {}).get(str(week)) or {}).get("line", {}).get(stat)
    mean = (sleeper + mingus) / 2 if sleeper is not None else mingus
    sd_obs = statistics.pstdev(vals) if len(vals) > 1 else 0
    prior = PRIOR_CV[stat] * max(mean, 1)
    sd = SPREAD_ADJ * math.sqrt((len(vals) * sd_obs ** 2 + PRIOR_WEIGHT * prior ** 2) / (len(vals) + PRIOR_WEIGHT))
    rank = ranks.get((opp, pos, stat))
    vol_rank = ranks.get((opp, pos, ok))
    shares = [e.get("tgt_sh") if ok == "tgt" else e.get("car_sh") for e in log[-3:]]
    shares = [x for x in shares if x is not None]
    return {"mean": round(mean, 1), "sd": round(max(sd, 0.5), 1),
            "source": "Sleeper + Mingus model" if sleeper is not None else "Mingus model", "stat": stat,
            "season": round(statistics.mean(vals), 1), "last3": round(statistics.mean(vals[-3:]), 1), "vals": vals, "opp": opp,
            "opp_rank": {"rank": rank[0], "of": rank[1]} if rank else None,
            "vol_rank": {"rank": vol_rank[0], "of": vol_rank[1]} if vol_rank else None,
            "parts": {"opp_key": ok, "vol_base": round(vol_base, 1), "vol": round(vol, 1), "eff": round(eff, 3 if stat == "rec" else 2),
                      "rate": round(rate, 3 if stat == "rec" else 2), "f_def_vol": round(f_def_vol, 3), "f_imp": round(f_imp, 3),
                      "f_script": round(f_script, 3), "f_inj": round(f_inj, 3), "f_def_eff": round(f_def_eff, 3),
                      "mean_adj": MEAN_ADJ[stat], "mingus": round(mingus, 1), "sleeper": sleeper, "out": out_names,
                      "share3": round(statistics.mean(shares), 3) if shares else None},
            "ctx": ctx}


def chance_over(proj, line):
    """Chance he beats a given number (e.g. his season average): log-normal (skewed like real yardage) for rushing / receiving / catches,
    a bell curve for passing yards (tuned on 2021-2025, see VOL_HALF_LIFE)."""
    m, sd = max(proj["mean"], 0.1), proj["sd"]
    if proj.get("stat") in SKEWED:
        if line <= 0:
            return 1.0
        s2 = math.log(1 + (sd / m) ** 2)
        return 1 - ncdf((math.log(line) - (math.log(m) - s2 / 2)) / math.sqrt(s2))
    return 1 - ncdf((line - m) / sd)


# ---------------------------------------------------------------- anytime touchdown

# Anytime-TD model (Nov 1, 2026; Josh asked for tested TD numbers instead of rough reads). Logistic regression on
# 2021-2025 nflverse player games (week 4+, at least 3 earlier games that season; 13,235 games), each game described
# only by earlier games: recency-weighted (4-game half-life) carries, targets, red-zone carries and targets, TDs per
# game, his share of the team's red-zone carries and targets, and the team's implied points vs the week average.
# Calibrated out of season (Platt); chances above 50% pulled in 20% (TD_TOP_SHRINK, it ran hot up there).
# Brier, lower = better: 2021-25 held out by season 0.1674 (his own TD rate alone 0.1738, everyone the same 0.1814);
# untouched 2026 weeks 4-7 0.1790 (0.1919 / 0.1934). The defense's TDs allowed to the position had no predictive
# value (weight ~0) and is left out. Scripts: scripts/backtest/td/.
TD_MODEL = {
    "names": ["car", "tgt", "rz_car", "rz_tgt", "td_rate", "rz_car_share", "rz_tgt_share", "log_implied", "QB", "RB", "WR", "TE"],
    "weights": [0.082626, 0.136538, 0.021174, 0.022308, 0.464942, 0.293399, 0.262097, 1.174721, 0.063443, -0.164981, 0.040517, 0.130508],
    "intercept": -2.254231,
}
TD_HALF_LIFE = 4
TD_TOP_SHRINK = 0.8
TD_MIN_GAMES = 3


def team_redzone(data):
    """{(team, week): (red-zone carries, red-zone targets)} summed over every player's game log."""
    if getattr(data, "_rz", None) is None:
        tot = {}
        for p in data.players:
            for e in p.get("log", []):
                k = (e.get("team") or p["team"], e["week"])
                c, t = tot.get(k, (0, 0))
                tot[k] = (c + (e.get("rz_car") or 0), t + (e.get("rz_tgt") or 0))
        data._rz = tot
    return data._rz


def td_chance(data, player, game):
    """Chance he scores a rushing or receiving TD in this game (passing TDs don't count; it's his own touchdown).
    None if he has fewer than TD_MIN_GAMES earlier games, little volume, or the game has no implied total."""
    if player["pos"] not in ("QB", "RB", "WR", "TE"):
        return None
    log = sorted((e for e in player.get("log", []) if e["week"] < game["week"]), key=lambda e: e["week"])
    if len(log) < TD_MIN_GAMES:
        return None
    ctx = team_context(data, player["team"], game)
    if not ctx["implied"] or not ctx["avg"]:
        return None
    w = decay_weights(len(log), TD_HALF_LIFE)
    avg = lambda f: sum(a * f(e) for a, e in zip(w, log)) / sum(w)
    rz = team_redzone(data)
    team_rz = lambda e, i: rz.get((e.get("team") or player["team"], e["week"]), (0, 0))[i]
    f = {"car": avg(lambda e: e.get("car") or 0), "tgt": avg(lambda e: e.get("tgt") or 0),
         "rz_car": avg(lambda e: e.get("rz_car") or 0), "rz_tgt": avg(lambda e: e.get("rz_tgt") or 0),
         "td_rate": avg(lambda e: (e.get("rush_td") or 0) + (e.get("rec_td") or 0))}
    if f["car"] + f["tgt"] < 2:
        return None
    t_car, t_tgt = avg(lambda e: team_rz(e, 0)), avg(lambda e: team_rz(e, 1))
    f["rz_car_share"] = f["rz_car"] / t_car if t_car else 0
    f["rz_tgt_share"] = f["rz_tgt"] / t_tgt if t_tgt else 0
    f["log_implied"] = math.log(ctx["implied"] / ctx["avg"])
    for pos in ("QB", "RB", "WR", "TE"):
        f[pos] = 1.0 if player["pos"] == pos else 0.0
    z = TD_MODEL["intercept"] + sum(wt * f[n] for n, wt in zip(TD_MODEL["names"], TD_MODEL["weights"]))
    p = 1 / (1 + math.exp(-z))
    if p > 0.5:
        p = 0.5 + TD_TOP_SHRINK * (p - 0.5)
    return {"p": round(p, 4), "parts": {k: round(v, 3) for k, v in f.items() if k not in ("QB", "RB", "WR", "TE")},
            "implied": ctx["implied"], "opp": game["away"] if game["home"] == player["team"] else game["home"]}
