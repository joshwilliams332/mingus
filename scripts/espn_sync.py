#!/usr/bin/env python3
"""Pull an ESPN fantasy football league into site/data/league.json.

Uses ESPN's unofficial fantasy API (the one fantasy.espn.com itself uses), so it
may change without notice. Settings come from scripts/espn_config.json (never
committed; see espn_config.example.json) or from environment variables:

    ESPN_LEAGUE_ID   the leagueId=... number in your league's URL
    ESPN_TEAM_ID     your teamId=... number (optional; picks "My team")
    ESPN_S2, ESPN_SWID   login cookies, only needed for private leagues

Run it on its own:            python scripts/espn_sync.py
or let build_data.py run it at the end of each data update.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "scripts" / "espn_config.json"
OUT = ROOT / "site" / "data" / "league.json"
API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"

# ESPN pro team ids -> nflverse team abbreviations.
PRO_TEAMS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN",
    11: "IND", 12: "KC", 13: "LV", 14: "LA", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX",
    33: "BAL", 34: "HOU",
}
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "Bench", 21: "IR", 23: "FLEX"}
STARTER_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "D/ST", "K", "Bench", "IR"]


def load_config():
    cfg = {}
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
    env = {"league_id": "ESPN_LEAGUE_ID", "team_id": "ESPN_TEAM_ID", "espn_s2": "ESPN_S2", "swid": "ESPN_SWID"}
    for key, var in env.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    return cfg


def fetch_league(cfg, season):
    url = API.format(season=season, league=cfg["league_id"]) + \
        "?view=mTeam&view=mRoster&view=mMatchup&view=mSettings&view=mStatus"
    headers = {"User-Agent": "mingus-build", "Accept": "application/json"}
    if cfg.get("espn_s2") and cfg.get("swid"):
        headers["Cookie"] = f"espn_s2={cfg['espn_s2']}; SWID={cfg['swid']}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                "ESPN says this league is private. Add espn_s2 and swid to scripts/espn_config.json "
                "(see espn_config.example.json for how to find them)."
            ) from e
        raise


def scoring_from_settings(settings):
    """Map ESPN scoring items to the site's formats: points per reception and per passing TD."""
    items = {i.get("statId"): i.get("points", 0) for i in (settings.get("scoringSettings") or {}).get("scoringItems", [])}
    rec = items.get(53, 0)
    fmt = "ppr" if rec >= 1 else "half" if rec >= 0.5 else "std"
    return {"fmt": fmt, "passTd": 6 if items.get(4, 4) >= 6 else 4, "rec_points": rec}


def team_name(t):
    return t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {t.get('id')}"


def parse_league(data, cfg, espn_to_gsis):
    """Turn ESPN's league JSON into the small shape the site uses."""
    settings = data.get("settings") or {}
    status = data.get("status") or {}
    teams = []
    for t in data.get("teams", []):
        roster = []
        for entry in (t.get("roster") or {}).get("entries", []):
            player = (entry.get("playerPoolEntry") or {}).get("player") or {}
            pos = POSITIONS.get(player.get("defaultPositionId"), "?")
            pro = PRO_TEAMS.get(player.get("proTeamId"))
            espn_id = entry.get("playerId") or player.get("id")
            # D/ST entries have negative ids; match them to our DST-<team> ids instead.
            pid = f"DST-{pro}" if pos == "DST" and pro else espn_to_gsis.get(str(espn_id))
            roster.append({
                "id": pid, "espn_id": espn_id, "name": player.get("fullName", "Unknown"),
                "pos": pos, "team": pro, "slot": SLOTS.get(entry.get("lineupSlotId"), "Bench"),
            })
        roster.sort(key=lambda r: STARTER_ORDER.index(r["slot"]) if r["slot"] in STARTER_ORDER else 99)
        rec = (t.get("record") or {}).get("overall") or {}
        teams.append({
            "id": t.get("id"), "name": team_name(t), "abbrev": t.get("abbrev"),
            "wins": rec.get("wins", 0), "losses": rec.get("losses", 0), "ties": rec.get("ties", 0),
            "pf": round(rec.get("pointsFor", 0), 2), "pa": round(rec.get("pointsAgainst", 0), 2),
            "roster": roster,
        })

    schedule = []
    for m in data.get("schedule", []):
        side = lambda s: {"team": (m.get(s) or {}).get("teamId"), "pts": round((m.get(s) or {}).get("totalPoints", 0), 2)} if m.get(s) else None
        schedule.append({"week": m.get("matchupPeriodId"), "home": side("home"), "away": side("away"), "winner": m.get("winner")})

    return {
        "league": {
            "id": cfg["league_id"], "name": settings.get("name", "My League"), "season": data.get("seasonId"),
            "week": status.get("currentMatchupPeriod") or data.get("scoringPeriodId"),
            "scoring": scoring_from_settings(settings),
            "size": len(teams),
        },
        "my_team": int(cfg["team_id"]) if cfg.get("team_id") else None,
        "teams": teams,
        "schedule": schedule,
    }


def espn_ids_from_roster(roster_rows):
    """nflverse roster rows carry ESPN ids, which is how ESPN players are matched to ours."""
    return {r["espn_id"]: pid for pid, r in roster_rows.items() if r.get("espn_id")}


def sync(season, roster_rows):
    """Write league.json if a league is configured. Returns True when it wrote the file."""
    cfg = load_config()
    if not cfg.get("league_id"):
        print("  ESPN sync skipped (no league configured; see scripts/espn_config.example.json)")
        return False
    data = fetch_league(cfg, season)
    league = parse_league(data, cfg, espn_ids_from_roster(roster_rows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(league, separators=(",", ":")))
    matched = sum(1 for t in league["teams"] for r in t["roster"] if r["id"])
    total = sum(len(t["roster"]) for t in league["teams"])
    print(f"  ESPN league '{league['league']['name']}': {len(league['teams'])} teams, "
          f"{matched}/{total} rostered players matched to nflverse")
    return True


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_data
    from datetime import date
    today = date.today()
    season = int(sys.argv[1]) if len(sys.argv) > 1 else (today.year if today.month >= 3 else today.year - 1)
    sync(season, build_data.build_roster(season))
