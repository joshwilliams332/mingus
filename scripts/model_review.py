#!/usr/bin/env python3
"""The football model's feedback loop: save projections before every game, score them after, retune weekly.

Runs in .github/workflows/model-review.yml. Every step is idempotent, so the workflow can run as often as it likes.

1. Snapshot. For every game that hasn't kicked off, the projection for every regular (pass / rush / rec yards,
   catches) is (re)saved to store/model/projections/<season>-wNN.json. Once a game starts its entry is frozen, so we
   always judge what the model said before kickoff.
2. Score. Every saved game whose box score nflverse has published is scored: average miss, bias (running high or low),
   Brier score of the chance of the over at the typical line (his average so far, as in the backtest), and, for night
   games where we pulled sportsbook lines, our chance vs the books' no-vig chance at the real line.
   -> store/model/scorecard.json (by week, by game day, by stat; plus the biggest misses).
3. Retune, once per finished week W (every game final with stats). Candidate settings are searched starting from the
   current ones (a step either way on each setting, twice over) on 2021-2025 plus this season's weeks before W, with
   this season counted THIS_SEASON_WEIGHT times as much. The candidate is adopted only if it also beats the current
   settings on week W itself, which it never saw (by at least ADOPT_MARGIN). Decision -> store/model/tuning/wNN.json;
   adopted settings -> store/model/settings.json (read by nfl_picks.apply_settings) and settings-history.json.
4. Report. After the retune, store/model/report-wNN.json (+ report-latest.json) with a ready-to-send email.

Usage: python3 scripts/model_review.py --data DIR --store DIR --hist DIR [--now ISO] [--no-tune]
  --hist: stats_<season>.csv for past seasons and this one, and games.csv (see scripts/backtest/README.md).
"""
import argparse
import copy
import csv
import json
import math
import os
import pickle
import statistics
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "backtest"))
import nfl_picks as N  # noqa: E402

PAST_SEASONS = (2021, 2022, 2023, 2024, 2025)
THIS_SEASON_WEIGHT = 4.0
ADOPT_MARGIN = 0.0005
MIN_VOL = {"att": 20, "car": 5, "tgt": 3}
STATS = {"pass_yds": ("QB",), "rush_yds": ("QB", "RB"), "rec_yds": ("RB", "WR", "TE"), "rec": ("RB", "WR", "TE")}
CSV_COL = {"pass_yds": "passing_yards", "rush_yds": "rushing_yards", "rec_yds": "receiving_yards", "rec": "receptions"}
GRID = {
    "hl": [1.5, 2, 3, 4, 6, 8, 12], "rate_hl": [3, 6, 10, 16, None], "K": [10, 20, 40, 80],
    "ds": [0, 0.125, 0.25, 0.375, 0.5, 0.75], "de": [0, 0.125, 0.25, 0.5], "cap": [0.05, 0.1, 0.15, 0.25],
    "is": [0, 0.125, 0.25, 0.5], "sc": [0, 0.005, 0.01], "c": [0.94, 0.97, 1.0, 1.03, 1.06, 1.09],
    "k": [1.0, 1.075, 1.15, 1.225, 1.3, 1.45], "pw": [2, 4, 8, 12],
}
CV_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
CS_GRID = [0.85, 0.9, 0.95, 1.0, 1.05]
LABEL = {"pass_yds": "passing yards", "rush_yds": "rushing yards", "rec_yds": "receiving yards", "rec": "catches"}


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 1. snapshot

def week_projections(data, games, week):
    """Projection rows for every regular in these games (both QBs if two have played a lot: only who actually plays
    gets scored, so a backup's row simply goes unscored)."""
    out = {}
    for g in games:
        rows = []
        for p in data.players:
            if p["team"] not in (g["home"], g["away"]) or not p["log"]:
                continue
            for st, poss in STATS.items():
                if p["pos"] not in poss:
                    continue
                pr = N.projection(data, p, st, g, week)
                if not pr or pr["parts"]["vol_base"] < MIN_VOL[pr["parts"]["opp_key"]]:
                    continue
                line = math.floor(statistics.mean(pr["vals"])) + 0.5
                rows.append({"pid": p["id"], "name": p["name"], "pos": p["pos"], "team": p["team"], "opp": pr["opp"],
                             "st": st, "mean": pr["mean"], "sd": pr["sd"], "mingus": pr["parts"]["mingus"],
                             "sleeper": pr["parts"]["sleeper"], "line": line,
                             "p_over": round(N.chance_over(pr, line), 4), "inj": (p.get("injury") or {}).get("status")})
        out[g["id"]] = rows
    return out


def snapshot(data, store, now):
    season = data.meta.get("season")
    upcoming = [g for g in data.games if g.get("home_score") is None and g.get("type", "REG") == "REG"]
    if not upcoming:
        return {"state": "none"}
    week = min(g["week"] for g in upcoming)
    file = Path(store) / "model" / "projections" / f"{season}-w{week:02d}.json"
    doc = N.read(file, {"season": season, "week": week, "games": {}})
    pre = [g for g in data.games if g["week"] == week and N.kickoff(g) > now]
    if not pre:
        return {"week": week, "state": "all started"}
    settings = (N.read(Path(store) / "model" / "settings.json") or {}).get("adopted_at", "default (Oct 31 tuning)")
    for gid, rows in week_projections(data, pre, week).items():
        doc["games"][gid] = {"saved": now.isoformat(timespec="minutes"), "settings": settings, "rows": rows}
    N.write(file, doc)
    return {"week": week, "state": "saved", "games": len(pre), "rows": sum(len(doc["games"][g["id"]]["rows"]) for g in pre)}


# ---------------------------------------------------------------- 2. score

def load_week_stats(path):
    out = {}
    if not path or not Path(path).exists():
        return out
    with open(path) as f:
        for r in csv.DictReader(f):
            if r.get("season_type", "REG") != "REG":
                continue
            out.setdefault(int(r["week"]), {})[r["player_id"]] = r
    return out


def brier(pairs):
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def summarize_rows(rs):
    """rs: scored rows. Averages per stat, bias in percent of the projection, and the Brier scores."""
    by = {}
    for st in STATS:
        x = [r for r in rs if r["st"] == st]
        if not x:
            continue
        by[st] = {"n": len(x), "mae": round(statistics.mean(abs(r["err"]) for r in x), 2),
                  "bias_pct": round(100 * sum(r["err"] for r in x) / max(sum(r["mean"] for r in x), 1e-9), 1),
                  "brier": round(brier([(r["p_over"], r["hit"]) for r in x]), 4),
                  "coin": round(brier([(0.5, r["hit"]) for r in x]), 4)}
    bk = [r for r in rs if r.get("book")]
    books = None
    if bk:
        books = {"n": len(bk), "ours": round(brier([(r["book"]["ours"], r["book"]["hit"]) for r in bk]), 4),
                 "books": round(brier([(r["book"]["market"], r["book"]["hit"]) for r in bk]), 4),
                 "blend": round(brier([(0.3 * r["book"]["ours"] + 0.7 * r["book"]["market"], r["book"]["hit"]) for r in bk]), 4)}
    return {"n": len(rs), "brier": round(brier([(r["p_over"], r["hit"]) for r in rs]), 4) if rs else None,
            "coin": round(brier([(0.5, r["hit"]) for r in rs]), 4) if rs else None, "by_stat": by, "books": books}


def score(data, store, stats_by_week):
    """Score every saved projection whose game has a published box score. Returns the scorecard."""
    dir_ = Path(store) / "model" / "projections"
    season = data.meta.get("season")
    weeks = {}
    for f in sorted(dir_.glob(f"{season}-w*.json")):
        doc = N.read(f, {})
        wk = doc.get("week")
        played = stats_by_week.get(wk, {})
        scored, days = [], {}
        for gid, entry in doc.get("games", {}).items():
            g = data.game.get(gid)
            if not g:
                continue
            teams = {g["home"], g["away"]}
            if not any(r.get("team") in teams for r in played.values()):
                continue                      # box score not published yet
            props = {(r["pid"], r["stat"]): r for r in (N.read(Path(store) / "odds" / "props" / f"{gid}.json", {}) or {}).get("rows", [])}
            for row in entry["rows"]:
                a = played.get(row["pid"])
                if not a:
                    continue                  # didn't play (inactive, backup QB): not scored, like a void
                actual = float(a.get(CSV_COL[row["st"]]) or 0)
                s = {**row, "gid": gid, "actual": actual, "err": round(row["mean"] - actual, 2), "hit": 1.0 if actual > row["line"] else 0.0,
                     "z": round((actual - row["mean"]) / row["sd"], 2) if row["sd"] else 0}
                bk = props.get((row["pid"], row["st"]))
                if bk:
                    proj = {"mean": row["mean"], "sd": row["sd"], "stat": row["st"]}
                    s["book"] = {"line": bk["line"], "ours": round(N.chance_over(proj, bk["line"]), 4), "market": bk["fair_o"],
                                 "hit": 1.0 if actual > bk["line"] else 0.0}
                scored.append(s)
                days.setdefault(g["date"], []).append(s)
        if not scored:
            continue
        misses = sorted(scored, key=lambda r: -abs(r["z"]))[:6]
        weeks[wk] = {**summarize_rows(scored),
                     "days": {d: {**summarize_rows(rs), "slot": day_slot(data, d), "games": len({r["gid"] for r in rs})} for d, rs in sorted(days.items())},
                     "complete": week_complete(data, wk, stats_by_week),
                     "misses": [{"name": r["name"], "st": r["st"], "mean": r["mean"], "actual": r["actual"], "opp": r["opp"]} for r in misses]}
    card = {"season": season, "weeks": {str(k): v for k, v in sorted(weeks.items())}}
    N.write(Path(store) / "model" / "scorecard.json", card)
    return card


def day_slot(data, day):
    gs = [g for g in data.games if g["date"] == day]
    if not gs:
        return day
    return N.slot_label(gs[0]) if all(N.is_night(g) for g in gs) else N.kickoff(gs[0]).strftime("%A")


def week_complete(data, week, stats_by_week):
    played = stats_by_week.get(week, {})
    teams = {r.get("team") for r in played.values()}
    gs = [g for g in data.games if g["week"] == week]
    return bool(gs) and all(g["home"] in teams and g["away"] in teams for g in gs)


# ---------------------------------------------------------------- 3. retune

def past_features(hist):
    import engine as E
    cache = Path(hist) / "features_past.pkl"
    if cache.exists():
        return pickle.load(open(cache, "rb"))
    rows = [r for s in PAST_SEASONS if (Path(hist) / f"stats_{s}.csv").exists() for r in E.features(s)]
    pickle.dump(rows, open(cache, "wb"))
    return rows


def neighbors(grid, v):
    g = list(grid)
    if v not in g:
        g = sorted(set(x for x in g if x is not None) | {v}) + ([None] if None in grid else [])
    i = g.index(v)
    return [g[j] for j in (i - 1, i + 1) if 0 <= j < len(g)]


def search(rows, P, rounds=2):
    """Local search from P: one step either way on each setting, kept when the weighted Brier improves."""
    import engine as E
    best_p, best = copy.deepcopy(P), E.evaluate(rows, P)["brier"]
    for _ in range(rounds):
        moved = False
        for name, grid in GRID.items():
            for v in neighbors(grid, best_p.get(name)):
                Q = copy.deepcopy(best_p)
                Q[name] = v
                s = E.evaluate(rows, Q)["brier"]
                if s < best - 1e-6:
                    best_p, best, moved = Q, s, True
        for st in STATS:
            for v in neighbors(CV_GRID, round(best_p["cv"][st], 2)):
                Q = copy.deepcopy(best_p); Q["cv"][st] = v
                s = E.evaluate(rows, Q)["brier"]
                if s < best - 1e-6:
                    best_p, best, moved = Q, s, True
            for v in neighbors(CS_GRID, round((best_p.get("cs") or {}).get(st, 1.0), 2)):
                Q = copy.deepcopy(best_p); Q.setdefault("cs", {})[st] = v
                s = E.evaluate(rows, Q)["brier"]
                if s < best - 1e-6:
                    best_p, best, moved = Q, s, True
        if not moved:
            break
    return best_p, best


def should_adopt(changes, valid_current, valid_candidate):
    """Adopt only real changes that beat the current settings on the week the search never saw."""
    return bool(changes) and valid_candidate is not None and valid_current is not None and valid_candidate < valid_current - ADOPT_MARGIN


def engine_p(P):
    Q = copy.deepcopy(P)
    Q["skew"] = set(Q.get("skew") or [])
    Q.setdefault("vol", "exp")
    Q.setdefault("cs", {})
    return Q


def diff(old, new):
    out = []
    for k in list(GRID) + ["cv", "cs"]:
        if old.get(k) != new.get(k):
            out.append({"setting": k, "from": old.get(k), "to": new.get(k)})
    return out


def retune(data, store, hist, stats_by_week, now, season_csv):
    """Once per finished week: search, validate on that week, adopt only if it wins there too."""
    import engine as E
    season = data.meta.get("season")
    done = [w for w in sorted(stats_by_week) if week_complete(data, w, stats_by_week)]
    if not done:
        return {"state": "no finished week"}
    week = done[-1]
    log_file = Path(store) / "model" / "tuning" / f"w{week:02d}.json"
    if log_file.exists():
        return {"week": week, "state": "done", "decision": N.read(log_file, {}).get("decision")}
    if week < 6:
        return {"week": week, "state": "too early"}
    cur = engine_p(N.model_settings())
    now_rows = [r for r in E.features(season, season_csv)]
    for r in now_rows:
        r["w"] = THIS_SEASON_WEIGHT
    train = past_features(hist) + [r for r in now_rows if r["week"] < week]
    valid = [r for r in now_rows if r["week"] == week]
    cand, train_score = search(train, cur)
    cur_train = E.evaluate(train, cur)["brier"]
    v_cur, v_cand = E.evaluate(valid, cur)["brier"], E.evaluate(valid, cand)["brier"]
    changes = diff(cur, cand)
    adopt = should_adopt(changes, v_cur, v_cand)
    why = ("no setting change improved the training seasons" if not changes else
           f"adopted: better on week {week} ({v_cand:.4f} vs {v_cur:.4f}), which it never saw" if adopt else
           f"kept the current settings: the candidate wasn't better on week {week} ({v_cand:.4f} vs {v_cur:.4f})")
    out_cand = {**cand, "skew": sorted(cand["skew"])}
    log = {"week": week, "tuned_at": now.isoformat(timespec="minutes"), "train_rows": len(train), "valid_rows": len(valid),
           "this_season_weight": THIS_SEASON_WEIGHT, "train": {"current": round(cur_train, 5), "candidate": round(train_score, 5)},
           "valid": {"current": round(v_cur, 5) if v_cur else None, "candidate": round(v_cand, 5) if v_cand else None,
                     "coin": round(sum((0.5 - (r["actual"] > r["line"])) ** 2 for r in valid) / len(valid), 5) if valid else None},
           "changes": changes, "decision": "adopted" if adopt else "kept", "why": why, "candidate": out_cand}
    N.write(log_file, log)
    if adopt:
        doc = {"settings": out_cand, "adopted_at": now.isoformat(timespec="minutes"), "week": week, "why": why}
        N.write(Path(store) / "model" / "settings.json", doc)
        hist_file = Path(store) / "model" / "settings-history.json"
        h = N.read(hist_file, [])
        h.append({k: doc[k] for k in ("adopted_at", "week", "why")} | {"changes": changes})
        N.write(hist_file, h)
    return {"week": week, "state": "done", "decision": log["decision"], "new": True}


# ---------------------------------------------------------------- 4. report

def fmt_change(c):
    names = {"hl": "volume recency half-life (games)", "rate_hl": "efficiency recency half-life (games)",
             "K": "league padding (opportunities)", "ds": "defense volume strength", "de": "defense per-play strength",
             "cap": "defense cap (±)", "is": "team-total strength", "sc": "game script per point", "c": "overall calibration",
             "k": "spread width", "pw": "typical-spread weight (games)", "cv": "typical spread by stat", "cs": "calibration by stat"}
    return f"{names.get(c['setting'], c['setting'])}: {c['from']} → {c['to']}"


def report(data, store, card, tuning, now):
    week = tuning.get("week")
    if not week or tuning.get("state") != "done":
        return {"state": "waiting"}
    file = Path(store) / "model" / f"report-w{week:02d}.json"
    if file.exists():
        return {"week": week, "state": "done"}
    wk = card["weeks"].get(str(week))
    log = N.read(Path(store) / "model" / "tuning" / f"w{week:02d}.json", {})
    if not wk:
        return {"week": week, "state": "no scored projections"}
    lines, html = [], []
    head = f"Week {week}: {wk['n']} projections scored. Brier {wk['brier']:.3f} vs a coin's {wk['coin']:.3f} ({'better' if wk['brier'] < wk['coin'] else 'worse'})."
    lines.append(head)
    for st, s in wk["by_stat"].items():
        lines.append(f"- {LABEL[st].capitalize()}: off by {s['mae']:g} on average, running {abs(s['bias_pct']):g}% {'high' if s['bias_pct'] > 0 else 'low'}; "
                     f"Brier {s['brier']:.3f} (coin {s['coin']:.3f}), {s['n']} projections.")
    lines.append("")
    lines.append("By game day:")
    for d, s in wk["days"].items():
        lines.append(f"- {s['slot']} ({s['games']} game{'s' if s['games'] != 1 else ''}): Brier {s['brier']:.3f} vs coin {s['coin']:.3f}, {s['n']} projections.")
    if wk.get("books"):
        b = wk["books"]
        lines += ["", f"Against real sportsbook lines (night games, {b['n']} props): ours {b['ours']:.3f}, the books' {b['books']:.3f}, "
                      f"our 30/70 blend {b['blend']:.3f} (lower is better)."]
    lines += ["", "Biggest misses: " + "; ".join(f"{m['name']} {LABEL[m['st']]} {m['mean']:g} projected, {m['actual']:g} actual (vs {m['opp']})" for m in wk["misses"])]
    lines += ["", f"Tuning: {log.get('why', '')}."]
    if log.get("changes"):
        lines.append(("Changed: " if log.get("decision") == "adopted" else "Tried: ") + "; ".join(fmt_change(c) for c in log["changes"]) + ".")
    trend = [(int(k), v["brier"], v["coin"]) for k, v in card["weeks"].items()]
    lines += ["", "Season so far (Brier, coin 0.250): " + ", ".join(f"W{k} {b:.3f}" for k, b, c in trend)]
    text = "\n".join(lines)
    html = (f'<div style="font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;max-width:620px">'
            f'<h2 style="margin:0 0 8px">Model report · Week {week}</h2>'
            + "".join(f'<p style="margin:0 0 6px">{escape(x)}</p>' if x else "" for x in lines)
            + '<p style="color:#888;font-size:13px;margin-top:14px">From the Mingus Football model review. Projections are '
              'saved before kickoff and scored against the box score; the typical line is his average so far.</p></div>')
    adopted = log.get("decision") == "adopted"
    subj = f"🏈 Model report · Week {week} · {'settings updated' if adopted else 'settings kept'} · Brier {wk['brier']:.3f}"
    doc = {"week": week, "written": now.isoformat(timespec="minutes"), "email": {"subject": subj, "html": html, "text": text}}
    N.write(file, doc)
    N.write(Path(store) / "model" / "report-latest.json", doc)
    return {"week": week, "state": "done", "new": True}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--hist", required=True)
    ap.add_argument("--now", default=None)
    ap.add_argument("--no-tune", action="store_true")
    a = ap.parse_args(argv)
    os.environ["MINGUS_HIST"] = str(Path(a.hist)) + "/"
    now = datetime.fromisoformat(a.now) if a.now else now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=N.ET)
    N.apply_settings(a.store)
    data = N.Data(a.data)
    season = data.meta.get("season")
    season_csv = Path(a.hist) / f"stats_{season}.csv"
    stats_by_week = load_week_stats(season_csv)
    snap = snapshot(data, a.store, now)
    card = score(data, a.store, stats_by_week)
    tuning = {"state": "skipped"} if a.no_tune else retune(data, a.store, a.hist, stats_by_week, now, str(season_csv))
    rep = report(data, a.store, card, tuning, now) if tuning.get("state") == "done" else {"state": "waiting"}
    status = {"checked": now.isoformat(timespec="minutes"), "snapshot": snap, "scored_weeks": list(card["weeks"]),
              "tuning": tuning, "report": rep}
    N.write(Path(a.store) / "model" / "status.json", status)
    print(f"Model review: snapshot {snap}; scored weeks {list(card['weeks'])}; tuning {tuning}; report {rep}")


if __name__ == "__main__":
    main()
