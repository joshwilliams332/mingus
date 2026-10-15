#!/usr/bin/env python3
"""Download nflverse data and write the JSON files the Mingus Sports site reads.

nflverse publishes its data as GitHub release assets and refreshes them through
the week during the season. This script only uses the standard library, so it
runs anywhere with Python 3.9+:

    python3 scripts/build_data.py            # current season
    python3 scripts/build_data.py --season 2025

Output (in site/data/):
    meta.json     season, latest completed week, next week, build time
    players.json  QB/RB/WR/TE/K and team defenses, each with a weekly game log
    games.json    the full season schedule with Vegas lines and scores
    teams.json    abbreviation -> city and nickname (for search and D/ST names)

Fantasy points are NOT stored. Each game-log entry keeps the raw stats, and the
site scores them in the browser so visitors can switch between PPR, half-PPR,
standard and 4/6-point passing touchdowns.
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
SKILL = {"QB", "RB", "WR", "TE"}
OUT_DIR = Path(__file__).resolve().parent.parent / "site" / "data"

TEAMS = {
    "ARI": ("Arizona", "Cardinals"), "ATL": ("Atlanta", "Falcons"), "BAL": ("Baltimore", "Ravens"),
    "BUF": ("Buffalo", "Bills"), "CAR": ("Carolina", "Panthers"), "CHI": ("Chicago", "Bears"),
    "CIN": ("Cincinnati", "Bengals"), "CLE": ("Cleveland", "Browns"), "DAL": ("Dallas", "Cowboys"),
    "DEN": ("Denver", "Broncos"), "DET": ("Detroit", "Lions"), "GB": ("Green Bay", "Packers"),
    "HOU": ("Houston", "Texans"), "IND": ("Indianapolis", "Colts"), "JAX": ("Jacksonville", "Jaguars"),
    "KC": ("Kansas City", "Chiefs"), "LA": ("Los Angeles", "Rams"), "LAC": ("Los Angeles", "Chargers"),
    "LV": ("Las Vegas", "Raiders"), "MIA": ("Miami", "Dolphins"), "MIN": ("Minnesota", "Vikings"),
    "NE": ("New England", "Patriots"), "NO": ("New Orleans", "Saints"), "NYG": ("New York", "Giants"),
    "NYJ": ("New York", "Jets"), "PHI": ("Philadelphia", "Eagles"), "PIT": ("Pittsburgh", "Steelers"),
    "SEA": ("Seattle", "Seahawks"), "SF": ("San Francisco", "49ers"), "TB": ("Tampa Bay", "Buccaneers"),
    "TEN": ("Tennessee", "Titans"), "WAS": ("Washington", "Commanders"),
}

# Raw per-game stats kept for QB/RB/WR/TE (short key -> nflverse columns summed).
SKILL_STATS = {
    "cmp": ["completions"], "att": ["attempts"],
    "pass_yds": ["passing_yards"], "pass_td": ["passing_tds"], "int": ["passing_interceptions"],
    "car": ["carries"], "rush_yds": ["rushing_yards"], "rush_td": ["rushing_tds"],
    "tgt": ["targets"], "rec": ["receptions"], "rec_yds": ["receiving_yards"], "rec_td": ["receiving_tds"],
    "fl": ["rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"],
    "two_pt": ["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"],
    "st_td": ["special_teams_tds"],
}
KICK_STATS = {
    "fg_0_39": ["fg_made_0_19", "fg_made_20_29", "fg_made_30_39"],
    "fg_40_49": ["fg_made_40_49"],
    "fg_50": ["fg_made_50_59", "fg_made_60_"],
    "fg_miss": ["fg_missed"], "fg_att": ["fg_att"], "fg_long": ["fg_long"],
    "xp": ["pat_made"], "xp_att": ["pat_att"], "xp_miss": ["pat_missed"],
}
DST_STATS = {
    "sacks": ["def_sacks"], "int": ["def_interceptions"], "fr": ["fumble_recovery_opp"],
    "td": ["def_tds", "special_teams_tds"], "safety": ["def_safeties"],
    "blk": ["def_punt_blocks", "def_fg_blocks"],
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


def pick(row, mapping):
    """Sum the nflverse columns for each short key; drop zeros to keep the JSON small."""
    out = {}
    for key, cols in mapping.items():
        total = sum(num(row.get(c)) or 0 for c in cols)
        if total:
            out[key] = round(total, 2) if isinstance(total, float) else total
    return out


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
        if int(r["week"]) != latest or r["position"] not in SKILL | {"K"}:
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
            "injury": injury or None,
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


def short_name(full):
    """'Kenneth Walker III' -> 'K. Walker III'."""
    parts = full.split(" ", 1)
    return f"{parts[0][0]}. {parts[1]}" if len(parts) == 2 else full


def build_players(season, games, roster, injuries, today):
    home_of = {(g["week"], g["home"]): True for g in games}
    home_of.update({(g["week"], g["away"]): False for g in games})

    people = {}
    for r in fetch_csv(f"stats_player/stats_player_week_{season}.csv"):
        pos = r["position"]
        if r["season_type"] != "REG" or (pos not in SKILL and pos != "K"):
            continue
        pid = r["player_id"]
        if pid not in people:
            ros = roster.get(pid, {})
            people[pid] = {
                "id": pid,
                "name": r["player_display_name"],
                "short": short_name(r["player_display_name"]),
                "pos": pos,
                "team": ros.get("team") or r["team"],
                "number": num(ros.get("jersey_number")),
                "headshot": r["headshot_url"] or ros.get("headshot_url") or None,
                "age": age_on(ros.get("birth_date"), today),
                "height": height_str(ros.get("height")),
                "weight": num(ros.get("weight")),
                "college": ros.get("college") or None,
                "exp": num(ros.get("years_exp")),
                "injury": injuries.get(pid),
                "log": [],
            }
        week = int(r["week"])
        entry = {"week": week, "team": r["team"], "opp": r["opponent_team"], "home": home_of.get((week, r["team"]))}
        entry.update(pick(r, KICK_STATS if pos == "K" else SKILL_STATS))
        people[pid]["log"].append(entry)

    for p in people.values():
        p["log"].sort(key=lambda e: e["week"])
    return list(people.values())


def build_defenses(season, games):
    """One D/ST entry per team, with points allowed taken from the schedule."""
    allowed = {}
    for g in games:
        if g["home_score"] is not None:
            allowed[(g["week"], g["home"])] = g["away_score"]
            allowed[(g["week"], g["away"])] = g["home_score"]
    home_of = {(g["week"], g["home"]): True for g in games}
    home_of.update({(g["week"], g["away"]): False for g in games})

    teams = {}
    for r in fetch_csv(f"stats_team/stats_team_week_{season}.csv"):
        if r["season_type"] != "REG":
            continue
        team, week = r["team"], int(r["week"])
        if team not in teams:
            city, nick = TEAMS.get(team, (team, ""))
            teams[team] = {
                "id": f"DST-{team}", "name": f"{nick} D/ST", "short": f"{nick} D/ST",
                "pos": "DST", "team": team, "number": None, "headshot": None, "injury": None, "log": [],
            }
        entry = {"week": week, "team": team, "opp": r["opponent_team"], "home": home_of.get((week, team)),
                 "pa": allowed.get((week, team), 0)}
        entry.update(pick(r, DST_STATS))
        teams[team]["log"].append(entry)

    for t in teams.values():
        t["log"].sort(key=lambda e: e["week"])
    return list(teams.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None, help="defaults to the current NFL season")
    args = ap.parse_args()
    today = date.today()
    # The NFL season runs Sep-Feb, so Jan/Feb still belong to last year's season.
    season = args.season or (today.year if today.month >= 3 else today.year - 1)

    print(f"Building Mingus Sports data for {season}")
    games = build_games(season)
    roster = build_roster(season)
    injuries, injury_week = build_injuries(season)
    players = build_players(season, games, roster, injuries, today) + build_defenses(season, games)

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
    teams = {abbr: {"city": c, "nickname": n} for abbr, (c, n) in TEAMS.items()}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in (("meta", meta), ("players", players), ("games", games), ("teams", teams)):
        path = OUT_DIR / f"{name}.json"
        path.write_text(json.dumps(data, separators=(",", ":")))
        print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)} ({path.stat().st_size // 1024} KB)")
    counts = defaultdict(int)
    for p in players:
        counts[p["pos"]] += 1
    print(f"Done: {dict(counts)}, {len(games)} games, last completed week {meta['last_week']}")


if __name__ == "__main__":
    main()
