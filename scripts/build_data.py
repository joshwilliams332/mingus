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
    teams.json    abbreviation -> city, nickname and color

Sleeper projections (api.sleeper.app) are added to each player as "proj" when
Sleeper can be reached; if it can't, the site falls back to Mingus projections.

Fantasy points are NOT stored. Each game-log entry keeps the raw stats, and the
site scores them in the browser so visitors can switch between PPR, half-PPR,
standard and 4/6-point passing touchdowns.
"""

import argparse
import csv
import gzip
import io
import json
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
SKILL = {"QB", "RB", "WR", "TE"}
OUT_DIR = Path(__file__).resolve().parent.parent / "site" / "data"

# abbreviation: (city, nickname, primary color, stadium latitude, longitude)
TEAMS = {
    "ARI": ("Arizona", "Cardinals", "#97233F", 33.5276, -112.2626),
    "ATL": ("Atlanta", "Falcons", "#A71930", 33.7554, -84.4008),
    "BAL": ("Baltimore", "Ravens", "#241773", 39.2780, -76.6227),
    "BUF": ("Buffalo", "Bills", "#00338D", 42.7738, -78.7870),
    "CAR": ("Carolina", "Panthers", "#0085CA", 35.2258, -80.8528),
    "CHI": ("Chicago", "Bears", "#C83803", 41.8623, -87.6167),
    "CIN": ("Cincinnati", "Bengals", "#FB4F14", 39.0955, -84.5161),
    "CLE": ("Cleveland", "Browns", "#FF3C00", 41.5061, -81.6995),
    "DAL": ("Dallas", "Cowboys", "#003594", 32.7473, -97.0945),
    "DEN": ("Denver", "Broncos", "#FB4F14", 39.7439, -105.0201),
    "DET": ("Detroit", "Lions", "#0076B6", 42.3400, -83.0456),
    "GB": ("Green Bay", "Packers", "#203731", 44.5013, -88.0622),
    "HOU": ("Houston", "Texans", "#A71930", 29.6847, -95.4107),
    "IND": ("Indianapolis", "Colts", "#002C5F", 39.7601, -86.1639),
    "JAX": ("Jacksonville", "Jaguars", "#006778", 30.3239, -81.6373),
    "KC": ("Kansas City", "Chiefs", "#E31837", 39.0489, -94.4839),
    "LA": ("Los Angeles", "Rams", "#003594", 33.9535, -118.3392),
    "LAC": ("Los Angeles", "Chargers", "#0080C6", 33.9535, -118.3392),
    "LV": ("Las Vegas", "Raiders", "#555F66", 36.0909, -115.1833),
    "MIA": ("Miami", "Dolphins", "#008E97", 25.9580, -80.2389),
    "MIN": ("Minnesota", "Vikings", "#4F2683", 44.9737, -93.2581),
    "NE": ("New England", "Patriots", "#002244", 42.0909, -71.2643),
    "NO": ("New Orleans", "Saints", "#A08A58", 29.9511, -90.0812),
    "NYG": ("New York", "Giants", "#0B2265", 40.8135, -74.0745),
    "NYJ": ("New York", "Jets", "#125740", 40.8135, -74.0745),
    "PHI": ("Philadelphia", "Eagles", "#004C54", 39.9008, -75.1675),
    "PIT": ("Pittsburgh", "Steelers", "#C99A00", 40.4468, -80.0158),
    "SEA": ("Seattle", "Seahawks", "#002244", 47.5952, -122.3316),
    "SF": ("San Francisco", "49ers", "#AA0000", 37.4030, -121.9700),
    "TB": ("Tampa Bay", "Buccaneers", "#D50A0A", 27.9759, -82.5033),
    "TEN": ("Tennessee", "Titans", "#4B92DB", 36.1665, -86.7713),
    "WAS": ("Washington", "Commanders", "#5A1414", 38.9078, -76.8645),
}
# Team logos are linked from ESPN's image server (the same source nflverse uses), not stored in the repo.
# ESPN's abbreviations differ from nflverse's for two teams.
ESPN_LOGO = "https://a.espncdn.com/i/teamlogos/nfl/500/{}.png"
ESPN_CODE = {"LA": "LAR", "WAS": "WSH"}
# Neutral-site stadiums (international games): name fragment -> (latitude, longitude).
NEUTRAL_SITES = {
    "Wembley": (51.5560, -0.2796), "Tottenham": (51.6043, -0.0664), "Allianz": (48.2188, 11.6247),
    "Deutsche Bank": (50.0686, 8.6455), "Olympiastadion": (52.5147, 13.2395), "Bernab": (40.4531, -3.6883),
    "Croke": (53.3609, -6.2511), "Corinthians": (-23.5453, -46.4742), "Maracan": (-22.9122, -43.2302),
    "Azteca": (19.3029, -99.1505), "Melbourne": (-37.8200, 144.9834),
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
    # Advanced stats for the Analytics page's chart builder.
    "pass_air": ["passing_air_yards"], "pass_epa": ["passing_epa"], "pass_fd": ["passing_first_downs"],
    "cpoe": ["passing_cpoe"], "sk": ["sacks_suffered"],
    "rush_epa": ["rushing_epa"], "rush_fd": ["rushing_first_downs"],
    "rec_air": ["receiving_air_yards"], "yac": ["receiving_yards_after_catch"],
    "rec_fd": ["receiving_first_downs"], "rec_epa": ["receiving_epa"],
    "tgt_sh": ["target_share"], "ay_sh": ["air_yards_share"],
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


def stadium_coords(g):
    """Lat/lon of the venue, for weather forecasts. Neutral sites are matched by stadium name."""
    for frag, ll in NEUTRAL_SITES.items():
        if frag.lower() in (g["stadium"] or "").lower():
            return list(ll)
    if g["location"] == "Neutral":
        return None
    t = TEAMS.get(g["home_team"])
    return [t[3], t[4]] if t else None


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
            "away_ml": num(g["away_moneyline"]),
            "home_ml": num(g["home_moneyline"]),
            "stadium": g["stadium"],
            "roof": g["roof"] or None,
            "surface": g["surface"] or None,
            "temp": num(g["temp"]),
            "wind": num(g["wind"]),
            "div": g["div_game"] == "1",
            "coords": stadium_coords(g),
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


SLEEPER_TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mingus-build"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_sleeper(season, last_week, roster):
    """Sleeper's weekly projections for weeks 1..last_week, keyed by our player ids.

    Returns {player_id: {week: {"ppr", "half", "std", "ptd"}}}. Past weeks are kept so the
    site can compare Sleeper's accuracy with Mingus projections.
    """
    to_gsis = {r["sleeper_id"]: pid for pid, r in roster.items() if r.get("sleeper_id")}
    out = defaultdict(dict)
    positions = "".join(f"&position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
    for week in range(1, last_week + 1):
        url = f"https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular{positions}"
        print(f"  downloading {url}")
        for item in fetch_json(url):
            st = item.get("stats") or {}
            if st.get("pts_ppr") is None and st.get("pts_std") is None:
                continue
            if (item.get("player") or {}).get("position") == "DEF" or item.get("position") == "DEF":
                team = item.get("team") or item.get("player_id")
                pid = f"DST-{SLEEPER_TEAM_FIX.get(team, team)}"
            else:
                pid = to_gsis.get(str(item.get("player_id")))
            if not pid:
                continue
            out[pid][week] = {
                "ppr": round(st.get("pts_ppr") or st.get("pts_std") or 0, 2),
                "half": round(st.get("pts_half_ppr") or st.get("pts_std") or 0, 2),
                "std": round(st.get("pts_std") or 0, 2),
                "ptd": st.get("pass_td") or 0,
            }
    return out


def short_name(full):
    """'Kenneth Walker III' -> 'K. Walker III'."""
    parts = full.split(" ", 1)
    return f"{parts[0][0]}. {parts[1]}" if len(parts) == 2 else full


def build_usage(season, roster):
    """Per player and week: offensive snaps (snap counts file) and red-zone looks (play-by-play).

    Returns {(player_id, week): {"snaps", "snap_pct", "rz_tgt", "rz_car"}}. Either source can fail
    without stopping the build; the Trends page then shows what it has.
    """
    usage = defaultdict(dict)
    try:
        to_gsis = {r["pfr_id"]: pid for pid, r in roster.items() if r.get("pfr_id")}
        for r in fetch_csv(f"snap_counts/snap_counts_{season}.csv"):
            pid = to_gsis.get(r["pfr_player_id"])
            snaps = num(r["offense_snaps"])
            if r["game_type"] != "REG" or not pid or not snaps:
                continue
            usage[(pid, int(r["week"]))].update(snaps=snaps, snap_pct=round(num(r["offense_pct"]) or 0, 3))
    except Exception as e:
        print(f"  WARNING: couldn't load snap counts ({e}); continuing without them")
    try:
        url = f"{BASE}/pbp/play_by_play_{season}.csv.gz"
        print(f"  downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "mingus-build"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            rows = csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(resp.read())), encoding="utf-8"))
            for r in rows:
                # Red zone = snapped at the opponent's 20 or closer. Penalties, kneels and two-point tries don't count.
                yl = num(r["yardline_100"])
                if (r["season_type"] != "REG" or yl is None or yl > 20 or r["play_type"] == "no_play"
                        or r["qb_kneel"] == "1" or r["two_point_attempt"] == "1"):
                    continue
                week = int(r["week"])
                if r["play_type"] == "pass" and r["receiver_player_id"] not in ("", "NA"):
                    u = usage[(r["receiver_player_id"], week)]
                    u["rz_tgt"] = u.get("rz_tgt", 0) + 1
                elif r["play_type"] == "run" and r["rusher_player_id"] not in ("", "NA"):
                    u = usage[(r["rusher_player_id"], week)]
                    u["rz_car"] = u.get("rz_car", 0) + 1
    except Exception as e:
        print(f"  WARNING: couldn't load play-by-play ({e}); continuing without red-zone stats")
    return usage


def build_players(season, games, roster, injuries, today, usage):
    home_of = {(g["week"], g["home"]): True for g in games}
    home_of.update({(g["week"], g["away"]): False for g in games})

    rows = [r for r in fetch_csv(f"stats_player/stats_player_week_{season}.csv") if r["season_type"] == "REG"]
    # Team carries and targets per game, for each player's share of them.
    team_car, team_tgt = defaultdict(float), defaultdict(float)
    for r in rows:
        key = (int(r["week"]), r["team"])
        team_car[key] += num(r["carries"]) or 0
        team_tgt[key] += num(r["targets"]) or 0

    people = {}
    for r in rows:
        pos = r["position"]
        if pos not in SKILL and pos != "K":
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
        if pos != "K":
            tc, tt = team_car[(week, r["team"])], team_tgt[(week, r["team"])]
            if tc and entry.get("car"):
                entry["car_sh"] = round(entry["car"] / tc, 3)
            # Opportunity share: the player's carries + targets out of the team's.
            if tc + tt and (entry.get("car") or entry.get("tgt")):
                entry["opp_sh"] = round((entry.get("car", 0) + entry.get("tgt", 0)) / (tc + tt), 3)
            entry.update(usage.get((pid, week), {}))
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
            city, nick = TEAMS.get(team, (team, ""))[:2]
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
    usage = build_usage(season, roster)
    players = build_players(season, games, roster, injuries, today, usage) + build_defenses(season, games)

    played = [g["week"] for g in games if g["type"] == "REG" and g["home_score"] is not None]
    upcoming = [g["week"] for g in games if g["home_score"] is None]
    # Every week up to and including the next one to be played.
    sleeper_weeks = min(upcoming) if upcoming else (max(played) if played else 0)
    try:
        sleeper = build_sleeper(season, sleeper_weeks, roster)
        for p in players:
            if p["id"] in sleeper:
                p["proj"] = {"sleeper": sleeper[p["id"]]}
        print(f"  Sleeper projections for {len(sleeper)} players")
    except Exception as e:  # network blocked, API changed, etc. The site still works without it.
        sleeper = {}
        print(f"  WARNING: couldn't load Sleeper projections ({e}); continuing without them")

    meta = {
        "projections": {"sleeper": bool(sleeper)},
        "season": season,
        "last_week": max(played) if played else 0,
        "next_week": min(upcoming) if upcoming else None,
        "injury_week": injury_week,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "source": "nflverse (github.com/nflverse/nflverse-data)",
    }
    teams = {abbr: {"city": c, "nickname": n, "color": col, "logo": ESPN_LOGO.format(ESPN_CODE.get(abbr, abbr).lower())}
             for abbr, (c, n, col, _, _) in TEAMS.items()}

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
