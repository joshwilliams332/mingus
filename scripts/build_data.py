#!/usr/bin/env python3
"""Download nflverse data and write the JSON files the Mingus site reads.

nflverse publishes its data as GitHub release assets and refreshes them through
the week during the season. This script only uses the standard library, so it
runs anywhere with Python 3.9+:

    python3 scripts/build_data.py            # current season
    python3 scripts/build_data.py --season 2025

Output (in site/data/):
    meta.json     season, latest completed week, next week, build time
    players.json  QB/RB/WR/TE with season totals, weekly log, bio and injury
    games.json    the full season schedule with Vegas lines and scores
"""

import argparse
import csv
import io
import json
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
POSITIONS = {"QB", "RB", "WR", "TE"}
OUT_DIR = Path(__file__).resolve().parent.parent / "site" / "data"

# Season totals kept for each player (nflverse column -> short key).
SEASON_COLS = {
    "games": "g",
    "completions": "cmp", "attempts": "att", "passing_yards": "pass_yds",
    "passing_tds": "pass_td", "passing_interceptions": "int",
    "carries": "car", "rushing_yards": "rush_yds", "rushing_tds": "rush_td",
    "targets": "tgt", "receptions": "rec", "receiving_yards": "rec_yds",
    "receiving_tds": "rec_td", "target_share": "tgt_share",
    "fantasy_points": "fpts", "fantasy_points_ppr": "ppr",
}
# Per-game columns kept for the game log.
WEEK_COLS = {
    "passing_yards": "pass_yds", "passing_tds": "pass_td", "passing_interceptions": "int",
    "carries": "car", "rushing_yards": "rush_yds", "rushing_tds": "rush_td",
    "targets": "tgt", "receptions": "rec", "receiving_yards": "rec_yds", "receiving_tds": "rec_td",
    "fantasy_points_ppr": "ppr",
}


def fetch_csv(path):
    url = f"{BASE}/{path}"
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mingus-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def num(v):
    """CSV string -> int/float, or None when blank/NA."""
    if v in ("", "NA", None):
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def height_str(inches):
    n = num(inches)
    return f"{n // 12}'{n % 12}\"" if isinstance(n, int) else None


def age_on(birth, today):
    try:
        b = date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def build_games(season):
    games = []
    for g in fetch_csv("schedules/games.csv"):
        if g["season"] != str(season):
            continue
        spread = num(g["spread_line"])  # nflverse: positive = home team favored
        total = num(g["total_line"])
        games.append({
            "id": g["game_id"],
            "week": int(g["week"]),
            "type": g["game_type"],
            "date": g["gameday"],
            "time": g["gametime"],
            "away": g["away_team"],
            "home": g["home_team"],
            "away_score": num(g["away_score"]),
            "home_score": num(g["home_score"]),
            # Stored as the HOME team's line in betting notation (negative = favored).
            "home_spread": -spread if spread is not None else None,
            "total": total,
            "home_implied": round(total / 2 + spread / 2, 1) if spread is not None and total is not None else None,
            "away_implied": round(total / 2 - spread / 2, 1) if spread is not None and total is not None else None,
            "stadium": g["stadium"],
            "roof": g["roof"],
        })
    return games


def build_injuries(season):
    """Latest injury-report entry per player, from the most recent week's report."""
    rows = fetch_csv(f"injuries/injuries_{season}.csv")
    if not rows:
        return {}, None
    latest = max(int(r["week"]) for r in rows)
    out = {}
    for r in rows:
        if int(r["week"]) != latest or r["position"] not in POSITIONS:
            continue
        # Game designations (Questionable/Out) arrive late in the week; until then,
        # fall back to practice participation so injuries still show up midweek.
        status = r["report_status"] or None
        injury = r["report_primary_injury"] or r["practice_primary_injury"] or ""
        if not status:
            practice = r["practice_status"]
            if "Not injury related" in injury or not practice or practice.startswith("Full"):
                continue
            status = "DNP" if practice.startswith("Did Not") else "Limited"
        out[r["gsis_id"]] = {
            "status": status,
            "injury": r["report_primary_injury"] or r["practice_primary_injury"] or None,
            "practice": r["practice_status"] or None,
            "week": latest,
        }
    return out, latest


def build_roster(season):
    """One row per player: the latest week's roster entry."""
    best = {}
    for r in fetch_csv(f"rosters/roster_{season}.csv"):
        pid = r["gsis_id"]
        if not pid:
            continue
        wk = num(r["week"]) or 0
        if pid not in best or wk >= (num(best[pid]["week"]) or 0):
            best[pid] = r
    return best


def build_players(season, games, roster, injuries, today):
    season_rows = fetch_csv(f"stats_player/stats_player_reg_{season}.csv")
    week_rows = fetch_csv(f"stats_player/stats_player_week_{season}.csv")

    # Game log per player, regular season only.
    logs = defaultdict(list)
    for r in week_rows:
        if r["season_type"] != "REG" or r["position"] not in POSITIONS:
            continue
        entry = {"week": int(r["week"]), "team": r["team"], "opp": r["opponent_team"]}
        entry.update({short: num(r[col]) or 0 for col, short in WEEK_COLS.items()})
        logs[r["player_id"]].append(entry)

    # Home/away for each log entry comes from the schedule.
    home_of = {(g["week"], g["home"]): True for g in games}
    home_of.update({(g["week"], g["away"]): False for g in games})

    players = []
    for r in season_rows:
        if r["position"] not in POSITIONS:
            continue
        pid = r["player_id"]
        ros = roster.get(pid, {})
        stats = {short: num(r[col]) or 0 for col, short in SEASON_COLS.items()}
        log = sorted(logs.get(pid, []), key=lambda e: e["week"])
        for e in log:
            e["home"] = home_of.get((e["week"], e["team"]))
        players.append({
            "id": pid,
            "name": r["player_display_name"],
            "pos": r["position"],
            "team": ros.get("team") or r["recent_team"],
            "number": num(ros.get("jersey_number")),
            "headshot": r["headshot_url"] or ros.get("headshot_url") or None,
            "age": age_on(ros.get("birth_date"), today),
            "height": height_str(ros.get("height")),
            "weight": num(ros.get("weight")),
            "college": ros.get("college") or None,
            "exp": num(ros.get("years_exp")),
            "roster_status": ros.get("status") or None,
            "injury": injuries.get(pid),
            "stats": stats,
            "ppg": round(stats["ppr"] / stats["g"], 1) if stats["g"] else 0,
            "log": log,
        })

    # Overall and positional ranks by total PPR points.
    players.sort(key=lambda p: p["stats"]["ppr"], reverse=True)
    pos_count = defaultdict(int)
    for i, p in enumerate(players, 1):
        pos_count[p["pos"]] += 1
        p["rank"] = i
        p["pos_rank"] = pos_count[p["pos"]]
    return players


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None, help="defaults to the current NFL season")
    args = ap.parse_args()
    today = date.today()
    # The NFL season runs Sep-Feb, so Jan/Feb still belong to last year's season.
    season = args.season or (today.year if today.month >= 3 else today.year - 1)

    print(f"Building Mingus data for {season}")
    games = build_games(season)
    roster = build_roster(season)
    injuries, injury_week = build_injuries(season)
    players = build_players(season, games, roster, injuries, today)

    played = [g["week"] for g in games if g["type"] == "REG" and g["home_score"] is not None]
    upcoming = [g["week"] for g in games if g["home_score"] is None]
    meta = {
        "season": season,
        "last_week": max(played) if played else 0,
        "next_week": min(upcoming) if upcoming else None,
        "injury_week": injury_week,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "source": "nflverse (github.com/nflverse/nflverse-data)",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in (("meta", meta), ("players", players), ("games", games)):
        path = OUT_DIR / f"{name}.json"
        path.write_text(json.dumps(data, separators=(",", ":")))
        print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)} ({path.stat().st_size // 1024} KB)")
    print(f"Done: {len(players)} players, {len(games)} games, last completed week {meta['last_week']}")


if __name__ == "__main__":
    main()
