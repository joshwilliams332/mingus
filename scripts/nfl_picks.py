#!/usr/bin/env python3
"""Mingus Football night-game best bets: locked before kickoff, graded after, emailed to Josh.

Runs in .github/workflows/nfl-picks.yml (never in the site deploy). It reads the site's data (players.json,
games.json, teams.json, meta.json from the live site, or a local folder), pulls player props from The Odds API for
night games only (kickoff 7 PM ET or later: TNF, SNF, MNF, late-season Saturdays), picks the best few, and writes
them to the store, which the workflow keeps on the `data` branch. Nothing here posts anywhere: a scheduled Claude
task emails the ready-to-post text to Josh, who posts it himself.

    store/picks/YYYY-MM-DD.json          that ET date's night-game picks, locked once (never rewritten)
    store/picks/week-NN-recap.json       a week's night picks graded, + season record (written once)
    store/picks/status.json              what the last run did (read by the email tasks)
    store/odds/props/<game id>.json      the props snapshot each pick was made from (one pull per game)
    store/odds/usage.json                Odds API credits left (from the response headers)

Credits: 1 per market per game (every player's line comes back in that one call), so 4 per night game. Listing
the week's events is free. The free key's 500 credits/month are shared with Hoop Lab (basketball), which spends what
it sees left over the rest of the month; we never pull when fewer than CREDIT_RESERVE would be left.

Usage: python3 scripts/nfl_picks.py --data DIR --store DIR [--now ISO] [--force-lock] [--no-odds] [--stats CSV]
"""

import argparse
import csv
import io
import json
import math
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo is in every Python we run on
    ET = None

API = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
STATS_CSV = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
SITE = "https://joshwilliams332.github.io/mingus"
BRAND = "Mingus Football"

# Odds API market -> (our game-log key, label, short label, positions it applies to)
MARKETS = {
    "player_pass_yds": ("pass_yds", "Passing yards", "pass yds", {"QB"}),
    "player_rush_yds": ("rush_yds", "Rushing yards", "rush yds", {"QB", "RB", "WR"}),
    "player_reception_yds": ("rec_yds", "Receiving yards", "rec yds", {"RB", "WR", "TE"}),
    "player_receptions": ("rec", "Receptions", "catches", {"RB", "WR", "TE"}),
}
STAT = {k: (lab, short) for k, lab, short, _ in MARKETS.values()}
CREDIT_RESERVE = 10        # never pull if fewer than this would be left
NIGHT_HOUR = 19            # kickoff at 7 PM ET or later = a night game
LOCK_BEFORE_MIN = 240      # picks lock on the first run within 4 hours of kickoff
RECORD_START_WEEK = 9      # Week 8 night games are a test run, emailed but not counted (Josh, Oct 29, 2026)

PICK = {
    "per_game": 2,         # at most this many picks from one game (one per player)
    # Same rule as Hoop Lab: the chance blends our projection with the books' no-vig price, because books price in
    # news we can't see. A pick needs our projection to lean past a fair market, not shout over it.
    "model_weight": 0.3,
    "max_gap": 0.20,       # skip when our chance and the market's differ by more than this (we're missing something)
    "min_prob": 0.54,      # blended chance of the side
    "min_edge": 0.03,      # blended chance x payout - 1 at the best posted price
    "min_games": 4,        # games played this season
    "price_range": (-200, 180),
    "skip_status": ("Out", "Doubtful", "Questionable", "DNP"),  # injury report (game status, or practice midweek)
}
DEF_STRENGTH = 0.5         # the defense adjustment is applied at half strength...
DEF_CAP = (0.85, 1.15)     # ...and capped, since 8 games of defense allowed is a small sample
PRIOR_CV = {"pass_yds": 0.30, "rush_yds": 0.50, "rec_yds": 0.55, "rec": 0.45}  # typical game-to-game spread / mean
PRIOR_WEIGHT = 4           # the spread estimate counts the typical spread as this many games


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


def et_date(dt):
    return dt.astimezone(ET).date().isoformat()


def time_label(dt):
    t = dt.astimezone(ET)
    return f"{(t.hour - 1) % 12 + 1}:{t.minute:02d} {'PM' if t.hour >= 12 else 'AM'} ET".replace(":00 ", " ")


def slot_label(game):
    k = kickoff(game)
    return {3: "TNF", 6: "SNF", 0: "MNF", 5: "Saturday night"}.get(k.weekday(), k.strftime("%A night"))


def day_label(iso):
    d = date.fromisoformat(iso)
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def price_txt(n):
    return f"+{n}" if n > 0 else str(n)


def units(u):
    return f"{'+' if u >= 0 else '-'}{abs(u):.1f}u"


def implied(price):
    """American odds -> the book's implied chance (with its vig)."""
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def payout(price):
    """Profit on a 1-unit bet that wins."""
    return price / 100 if price > 0 else 100 / -price


def norm_name(name):
    """'Amon-Ra St. Brown' / 'Kenneth Walker III' -> comparable keys."""
    s = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", s.strip())
    return re.sub(r"\s+", " ", s)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def post_length(text):
    """X counts most emoji/symbols as 2 characters; close enough for staying under 280."""
    return sum(2 if ord(ch) > 0x2000 else 1 for ch in text)


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
                for k in STAT:
                    t[k] = t.get(k, 0) + (e.get(k) or 0)
                weeks.setdefault(e["opp"], set()).add(e["week"])
        per = {team: {pos: {k: v / len(weeks[team]) for k, v in st.items()} for pos, st in byp.items()}
               for team, byp in tot.items()}
        league = {}
        for pos in ("QB", "RB", "WR", "TE"):
            league[pos] = {k: statistics.mean(per[t].get(pos, {}).get(k, 0) for t in per) for k in STAT} if per else {}
        ranks = {}
        for pos in ("QB", "RB", "WR", "TE"):
            for k in STAT:
                vals = sorted((per[t].get(pos, {}).get(k, 0) for t in per), reverse=True)
                for t in per:
                    v = per[t].get(pos, {}).get(k, 0)
                    ranks[(t, pos, k)] = (1 + sum(1 for x in vals if x > v), len(vals))
        self._dvp = (per, league, ranks)
        return self._dvp


# ---------------------------------------------------------------- the sportsbooks

class OddsAPI:
    """The Odds API, keeping the account's credit usage (from the response headers) in store/odds/usage.json."""

    def __init__(self, key, store):
        self.key, self.usage_file = key, Path(store) / "odds" / "usage.json"
        self.usage = read(self.usage_file, {})

    def get(self, path, params):
        q = urllib.parse.urlencode({"apiKey": self.key, **params})
        req = urllib.request.Request(f"{API}{path}?{q}", headers={"User-Agent": "mingus-picks"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            h = resp.headers
        if h.get("x-requests-remaining") is not None:
            self.usage = {"remaining": int(float(h["x-requests-remaining"])), "used": int(float(h.get("x-requests-used") or 0)),
                          "last_cost": int(float(h.get("x-requests-last") or 0)),
                          "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            write(self.usage_file, self.usage)
        return body

    def events(self):
        return self.get("/events", {})  # free

    def props(self, event_id):
        return self.get(f"/events/{event_id}/odds", {"regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american"})


def match_event(data, game, events):
    """The Odds API event for one of our games: same home and away team, kickoff within a day."""
    home, away = data.full_name.get(game["home"]), data.full_name.get(game["away"])
    k = kickoff(game)
    for ev in events:
        if ev.get("home_team") == home and ev.get("away_team") == away:
            t = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            if abs((t - k).total_seconds()) < 36 * 3600:
                return ev
    return None


def parse_props(event_odds, data, game):
    """Raw event odds -> one row per player and stat at the most-posted line:
    {pid, name, team, stat, line, over, under (best prices at that line), book_o, book_u, fair_o, fair_u, books}."""
    roster = {}
    for p in data.players:
        if p["team"] in (game["home"], game["away"]) and p["pos"] in ("QB", "RB", "WR", "TE"):
            roster.setdefault(norm_name(p["name"]), p)
    quotes = {}  # (pid, stat) -> {line: {book: {"Over": price, "Under": price}}}
    for bk in event_odds.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("key") not in MARKETS:
                continue
            stat = MARKETS[mk["key"]][0]
            for o in mk.get("outcomes") or []:
                p = roster.get(norm_name(o.get("description")))
                if not p or o.get("point") is None or o.get("name") not in ("Over", "Under"):
                    continue
                side = quotes.setdefault((p["id"], stat), {}).setdefault(o["point"], {}).setdefault(bk.get("title") or bk.get("key"), {})
                side[o["name"]] = o["price"]
    rows = []
    for (pid, stat), by_line in quotes.items():
        # The line most books post (ties: the one with more two-sided quotes), so the no-vig price is a consensus.
        line, books = max(by_line.items(), key=lambda kv: (len(kv[1]), sum(1 for q in kv[1].values() if len(q) == 2)))
        two = {b: q for b, q in books.items() if "Over" in q and "Under" in q}
        if not two:
            continue
        fair = []
        for q in two.values():
            io_, iu = implied(q["Over"]), implied(q["Under"])
            fair.append(io_ / (io_ + iu))
        best_o = max(two.items(), key=lambda kv: payout(kv[1]["Over"]))
        best_u = max(two.items(), key=lambda kv: payout(kv[1]["Under"]))
        p = data.by_id[pid]
        rows.append({"pid": pid, "name": p["name"], "team": p["team"], "pos": p["pos"], "stat": stat, "line": line,
                     "over": best_o[1]["Over"], "book_o": best_o[0], "under": best_u[1]["Under"], "book_u": best_u[0],
                     "fair_o": round(statistics.mean(fair), 4), "fair_u": round(1 - statistics.mean(fair), 4),
                     "books": len(two)})
    return sorted(rows, key=lambda r: (r["team"], r["name"], r["stat"]))


# ---------------------------------------------------------------- our projection

def projection(data, player, stat, game, week):
    """Our expected value and spread for a player's stat in this game, or None without enough history.

    Mean: Sleeper's projection for the week when the site has it (it accounts for news and roles), otherwise the
    Mingus estimate: the average of his season per-game and last-3 numbers, times how much this defense allows to his
    position vs the league (at half strength, capped 0.85-1.15). Spread: his own game-to-game spread, steadied with a
    typical spread for the stat (counted as PRIOR_WEIGHT games), since 6-8 games is a small sample.
    """
    log = [e for e in player["log"] if e["week"] < week]
    if len(log) < PICK["min_games"]:
        return None
    vals = [e.get(stat) or 0 for e in log]
    season, last3 = statistics.mean(vals), statistics.mean(vals[-3:])
    opp = game["home"] if player["team"] == game["away"] else game["away"]
    per, league, ranks = data.dvp()
    allowed = per.get(opp, {}).get(player["pos"], {}).get(stat)
    lg = league.get(player["pos"], {}).get(stat)
    factor = 1.0
    if allowed is not None and lg:
        factor = min(DEF_CAP[1], max(DEF_CAP[0], 1 + DEF_STRENGTH * (allowed / lg - 1)))
    mingus = (season + last3) / 2 * factor
    sleeper = (((player.get("proj") or {}).get("sleeper") or {}).get(str(week)) or {}).get("line", {}).get(stat)
    mean = sleeper if sleeper is not None else mingus
    sd_obs = statistics.pstdev(vals) if len(vals) > 1 else 0
    prior = PRIOR_CV[stat] * max(mean, 1)
    sd = math.sqrt((len(vals) * sd_obs ** 2 + PRIOR_WEIGHT * prior ** 2) / (len(vals) + PRIOR_WEIGHT))
    rank = ranks.get((opp, player["pos"], stat))
    return {"mean": round(mean, 1), "sd": round(max(sd, 0.5), 1), "source": "Sleeper" if sleeper is not None else "Mingus estimate",
            "season": round(season, 1), "last3": round(last3, 1), "vals": vals, "opp": opp, "factor": round(factor, 3),
            "opp_rank": {"rank": rank[0], "of": rank[1]} if rank else None}


def chance_over(proj, line):
    return 1 - ncdf((line - proj["mean"]) / proj["sd"])


# ---------------------------------------------------------------- choosing picks

def injured(player):
    inj = player.get("injury") or {}
    return (inj.get("status") or "") in PICK["skip_status"]


def candidates(data, game, rows):
    """Every side of every prop in this game, with our chance and the edge at the best posted price."""
    out = []
    for r in rows:
        p = data.by_id.get(r["pid"])
        pos_ok = next((pos for _, (k, _, _, pos) in MARKETS.items() if k == r["stat"]), set())
        if not p or p["pos"] not in pos_ok or injured(p):
            continue
        proj = projection(data, p, r["stat"], game, game["week"])
        if not proj:
            continue
        for side in ("o", "u"):
            price = r["over"] if side == "o" else r["under"]
            if price is None or not (PICK["price_range"][0] <= price <= PICK["price_range"][1]):
                continue
            model = chance_over(proj, r["line"]) if side == "o" else 1 - chance_over(proj, r["line"])
            market = r["fair_o"] if side == "o" else r["fair_u"]
            if abs(model - market) > PICK["max_gap"]:
                continue
            prob = PICK["model_weight"] * model + (1 - PICK["model_weight"]) * market
            edge = prob * (1 + payout(price)) - 1
            out.append({"row": r, "player": p, "proj": proj, "side": side, "price": price, "model": model,
                        "market": market, "prob": prob, "edge": edge})
    return out


def choose(cands):
    chosen, players = [], set()
    for c in sorted((c for c in cands if c["prob"] >= PICK["min_prob"] and c["edge"] >= PICK["min_edge"]), key=lambda c: -c["edge"]):
        if len(chosen) >= PICK["per_game"] or c["player"]["id"] in players:
            continue
        chosen.append(c)
        players.add(c["player"]["id"])
    return chosen


def why_line(c):
    """One sentence of why: projection vs the line, recent games vs the line, and the matchup when it helps."""
    r, proj, short = c["row"], c["proj"], STAT[c["row"]["stat"]][1]
    last5 = proj["vals"][-5:]
    hits = sum(1 for v in last5 if (v > r["line"] if c["side"] == "o" else v < r["line"]))
    parts = [f"projected {proj['mean']:g} ({proj['source']}) vs the {r['line']:g} line",
             f"{'cleared' if c['side'] == 'o' else 'stayed under'} it in {hits} of his last {len(last5)}"]
    rk = proj.get("opp_rank")
    if rk:
        pos = c["player"]["pos"] + "s"
        if c["side"] == "o" and rk["rank"] <= 8:
            parts.append(f"{proj['opp']} allows the {'' if rk['rank'] == 1 else ordinal(rk['rank']) + ' '}most {short} to {pos}")
        if c["side"] == "u" and rk["rank"] > rk["of"] - 8:
            n = rk["of"] - rk["rank"] + 1
            parts.append(f"{proj['opp']} allows the {'' if n == 1 else ordinal(n) + ' '}fewest {short} to {pos}")
    s = ", ".join(parts)
    return s[0].upper() + s[1:] + "."


def to_pick(c, game):
    r = c["row"]
    return {
        "id": f"{game['id']}-{r['pid']}-{r['stat']}", "gid": game["id"], "week": game["week"], "pid": r["pid"],
        "name": r["name"], "team": r["team"], "opp": c["proj"]["opp"], "pos": c["player"]["pos"],
        "stat": r["stat"], "side": c["side"], "line": r["line"], "price": c["price"],
        "book": r["book_o"] if c["side"] == "o" else r["book_u"], "books": r["books"],
        "proj": c["proj"]["mean"], "source": c["proj"]["source"],
        "prob": round(c["prob"], 3), "model": round(c["model"], 3), "market": round(c["market"], 3), "edge": round(c["edge"], 3),
        "kickoff": kickoff(game).isoformat(), "why": why_line(c),
    }


def short(pick):
    return f"{pick['name']} {'O' if pick['side'] == 'o' else 'U'} {pick['line']:g} {STAT[pick['stat']][1]}"


# ---------------------------------------------------------------- grading and the record

def grade(pick, stats_rows):
    """{status: win/loss/push/void/open, actual, profit}. stats_rows: nflverse weekly rows for the season.
    Void (like the books) when the game's stats are out but he has no row (didn't play)."""
    key = MARKETS_BY_STAT[pick["stat"]]
    game_rows = [r for r in stats_rows if int(r["week"]) == pick["week"] and r["team"] in (pick["team"], pick["opp"])]
    if not game_rows:
        return {"status": "open", "actual": None, "profit": 0}
    mine = next((r for r in game_rows if r["player_id"] == pick["pid"]), None)
    if not mine:
        return {"status": "void", "actual": None, "profit": 0}
    actual = float(mine.get(key) or 0)
    actual = int(actual) if actual.is_integer() else actual
    if actual == pick["line"]:
        return {"status": "push", "actual": actual, "profit": 0}
    won = actual > pick["line"] if pick["side"] == "o" else actual < pick["line"]
    return {"status": "win" if won else "loss", "actual": actual, "profit": round(payout(pick["price"]) if won else -1, 3)}


MARKETS_BY_STAT = {"pass_yds": "passing_yards", "rush_yds": "rushing_yards", "rec_yds": "receiving_yards", "rec": "receptions"}


def summarize(results):
    s = {"w": 0, "l": 0, "p": 0, "v": 0, "profit": 0.0}
    for g in results:
        k = {"win": "w", "loss": "l", "push": "p", "void": "v"}.get(g["status"])
        if k:
            s[k] += 1
            s["profit"] = round(s["profit"] + g["profit"], 3)
    return s


def record_txt(s):
    return f"{s['w']}-{s['l']}{'-' + str(s['p']) if s['p'] else ''} ({units(s['profit'])})"


def locked_days(dir_):
    return sorted(f.stem for f in Path(dir_).glob("????-??-??.json"))


def season_record(dir_, stats_rows, season, through_week=None):
    """Every counted pick (week >= RECORD_START_WEEK) through `through_week`, graded."""
    res = []
    for day in locked_days(dir_):
        doc = read(Path(dir_) / f"{day}.json", {})
        if doc.get("season") != season or doc.get("test"):
            continue
        for pick in doc.get("picks", []):
            if through_week is None or pick["week"] <= through_week:
                res.append(grade(pick, stats_rows))
    return summarize(res)


# ---------------------------------------------------------------- post text and email

FOOT = "For entertainment. 21+ · Gamble responsibly · 1-800-GAMBLER"


def slate_post(games, picks, season, test):
    g0 = games[0]
    head = f"🏈 {BRAND} best bets · {slot_label(g0)} · " + " · ".join(f"{g['away']} @ {g['home']}" for g in games)
    rec = season and season["w"] + season["l"]
    if not picks:
        main = f"{head}\n\nNothing cleared our bar at tonight's prices. No plays is a play.\n\n{('Season: ' + record_txt(season) + chr(10)) if rec else ''}{FOOT}"
        return {"main": main, "replies": []}

    def build(with_prices):
        return "\n".join([head, "", f"Our top {len(picks)}:" if len(picks) > 1 else "Our pick:", "",
                          *[short(p) + (f" ({price_txt(p['price'])})" if with_prices else "") for p in picks], "",
                          f"Season: {record_txt(season)} · why 👇" if rec else "Graded after the game, wins and losses. Why 👇",
                          "", FOOT])
    main = build(True)
    if post_length(main) > 280:
        main = build(False)
    return {"main": main, "replies": [f"{short(p)}: {p['why']}"[:280] for p in picks]}


def email_html(title, post, notes, test):
    box = lambda t: (f'<pre style="white-space:pre-wrap;font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:#f4f5f7;'
                     f'border:1px solid #dde0e5;border-radius:10px;padding:12px 14px;margin:0 0 12px">{escape(t)}</pre>')
    banner = ('<p style="background:#fff4d6;border:1px solid #f0d58a;border-radius:8px;padding:8px 12px;margin:0 0 14px">'
              '<b>Test run.</b> Week 8 is a dry run: these picks are graded but not counted in the record, and not for posting.</p>') if test else ""
    replies = f'<h3 style="margin:0 0 6px">Thread replies</h3>{"".join(box(r) for r in post["replies"])}' if post["replies"] else ""
    note_html = (f'<h3 style="margin:16px 0 6px">For you, not for posting</h3><ul style="color:#444;padding-left:18px;margin:0">'
                 f'{"".join(f"<li>{escape(n)}</li>" for n in notes)}</ul>') if notes else ""
    return (f'<div style="font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;max-width:620px">'
            f'<h2 style="margin:0 0 4px">{escape(title)}</h2>{banner}'
            f'<p style="color:#555;margin:0 0 16px">Copy, paste, post. Long-press a box to copy it.</p>'
            f'<h3 style="margin:0 0 6px">Post</h3>{box(post["main"])}{replies}{note_html}'
            f'<p style="color:#888;font-size:13px;margin-top:18px">From {BRAND}\'s picks job. '
            f'<a href="{SITE}/games.html">This week\'s games</a></p></div>')


def email_text(post, notes, test):
    return "\n".join([*(["TEST RUN: not counted, not for posting.", ""] if test else []), post["main"], "",
                      *[x for r in post["replies"] for x in (r, "")], *[f"Note: {n}" for n in notes]])


# ---------------------------------------------------------------- lock

def night_games_on(data, day):
    return sorted((g for g in data.games if g["date"] == day and is_night(g)), key=kickoff)


def lock(data, store, now, api, force=False):
    """Lock tonight's night-game picks once (first run within LOCK_BEFORE_MIN of the first night kickoff)."""
    dir_ = Path(store) / "picks"
    day = et_date(now)
    file = dir_ / f"{day}.json"
    games = night_games_on(data, day)
    if file.exists():
        return {"day": day, "state": "locked", "why": "already locked"}
    if not games:
        return {"day": day, "state": "no-games", "why": "no night games today"}
    pre = [g for g in games if kickoff(g) > now]
    if not pre:
        return {"day": day, "state": "missed", "why": "every night game had started before picks locked"}
    mins = (kickoff(pre[0]) - now).total_seconds() / 60
    if not force and mins > LOCK_BEFORE_MIN:
        return {"day": day, "state": "waiting", "why": f"locks within {LOCK_BEFORE_MIN // 60} hours of the {time_label(kickoff(pre[0]))} kickoff"}
    if api is None:
        return {"day": day, "state": "no-props", "why": "no Odds API key in this run"}

    snaps = {}
    try:
        events = api.events()
    except Exception as e:  # network / key problem: say so, try again next run
        return {"day": day, "state": "no-props", "why": f"couldn't reach The Odds API ({e})"}
    for g in pre:
        snap_file = Path(store) / "odds" / "props" / f"{g['id']}.json"
        snap = read(snap_file)
        if snap is None:
            ev = match_event(data, g, events)
            if not ev:
                continue
            left = (api.usage or {}).get("remaining")
            if left is not None and left - len(MARKETS) < CREDIT_RESERVE:
                return {"day": day, "state": "no-credits", "why": f"only {left} Odds API credits left this month"}
            try:
                raw = api.props(ev["id"])
            except Exception as e:
                return {"day": day, "state": "no-props", "why": f"props pull failed ({e})"}
            snap = {"game": g["id"], "event": ev["id"], "pulled": now.isoformat(), "rows": parse_props(raw, data, g)}
            write(snap_file, snap)
        snaps[g["id"]] = snap
    if not any(s["rows"] for s in snaps.values()):
        return {"day": day, "state": "no-props", "why": "the books haven't posted player props for tonight yet"}

    test = pre[0]["week"] < RECORD_START_WEEK
    picks, n_cands = [], 0
    for g in pre:
        cands = candidates(data, g, (snaps.get(g["id"]) or {}).get("rows", []))
        n_cands += len(cands)
        picks += [to_pick(c, g) for c in choose(cands)]
    season = read(dir_ / "record.json", {}).get("season") if not test else None
    post = slate_post(pre, picks, season, test)
    notes = [
        f"Locked {time_label(now)} from {n_cands} prop sides across {sum(s['rows'] and 1 or 0 for s in snaps.values())} game(s); "
        "prices are from that moment, so check your book before posting.",
        "Our chance = 30% our projection + 70% the books' no-vig price. Props where the two disagree by 20+ points were skipped "
        "(usually news we can't see).",
        "Projection = Sleeper's when available, otherwise the Mingus estimate (season + last-3 average, adjusted for the defense).",
        "Anyone listed questionable, doubtful, out or DNP was skipped. If a pick's player is inactive, it's graded as a void.",
        "This football model has no backtest against real lines yet; the public record is the test.",
    ]
    title = f"{'TEST · ' if test else ''}{slot_label(pre[0])} post · {day_label(day)} · " + (
        f"{len(picks)} pick{'s' if len(picks) != 1 else ''}" if picks else "no plays")
    write(file, {"date": day, "season": data.meta.get("season"), "week": pre[0]["week"], "test": test,
                 "games": [g["id"] for g in pre], "locked_at": now.isoformat(), "settings": PICK, "picks": picks,
                 "post": post, "email": {"subject": f"🏈 {title}", "html": email_html(title, post, notes, test),
                                         "text": email_text(post, notes, test)}})
    return {"day": day, "state": "locked", "why": f"{len(picks)} pick(s) locked", "new": True}


# ---------------------------------------------------------------- grade + weekly recap

def recap(data, store, stats_rows, now):
    """Grade every locked night; write record.json, and each finished week's recap once (all its night games graded)."""
    dir_ = Path(store) / "picks"
    season = data.meta.get("season")
    by_week = {}
    for day in locked_days(dir_):
        doc = read(dir_ / f"{day}.json", {})
        if doc.get("season") == season:
            by_week.setdefault(doc["week"], []).append(doc)
    write(dir_ / "record.json", {"season": season_record(dir_, stats_rows, season)})
    out = {"state": "none"}
    for week in sorted(by_week):
        file = dir_ / f"week-{week:02d}-recap.json"
        if file.exists():
            out = {"week": week, "state": "done"}
            continue
        nights = [g for g in data.games if g["week"] == week and is_night(g)]
        if any(kickoff(g) > now for g in nights):
            return {"week": week, "state": "waiting", "why": "the week's night games aren't all played yet"}
        docs = by_week[week]
        rows = [(p, grade(p, stats_rows)) for d in docs for p in d["picks"]]
        if any(g["status"] == "open" for _, g in rows):
            return {"week": week, "state": "pending", "why": "nflverse hasn't published every game's player stats yet"}
        test = all(d.get("test") for d in docs)
        s = summarize([g for _, g in rows])
        season_s = season_record(dir_, stats_rows, season, through_week=week)
        mark = {"win": "✅", "loss": "❌"}
        lines = [f"{mark.get(g['status'], '➖')} {short(p)}" + (" (inactive, void)" if g["status"] == "void" else f" ({g['actual']:g})")
                 for p, g in rows]
        n = s["w"] + s["l"]
        opener = (f"Week {week} night games: no picks (nothing cleared our bar)." if not rows else
                  f"Week {week} night games: every pick voided." if not n else
                  f"{'✅ ' if s['profit'] > 0 else '❌ ' if s['profit'] < 0 else ''}Week {week} night games: {s['w']}-{s['l']} ({units(s['profit'])}).")
        tail = [] if test else [f"Season: {record_txt(season_s)}", "Every pick posted before kickoff, wins and losses."]
        main = "\n".join([f"🏈 {BRAND} · {opener}", "", *lines, "", *tail, *([""] if tail else []), FOOT]).strip()
        post = {"main": main, "replies": []}
        notes = ["Graded from nflverse box scores. A player who didn't play is a void, like the sportsbooks do it."]
        title = f"{'TEST · ' if test else ''}Week {week} recap · {s['w']}-{s['l']}{'-' + str(s['p']) if s['p'] else ''} ({units(s['profit'])})"
        write(file, {"week": week, "season": season, "test": test, "graded_at": now.isoformat(), "record": s,
                     "season_record": None if test else season_s,
                     "results": [{"id": p["id"], **g} for p, g in rows], "post": post,
                     "email": {"subject": f"🏈 {title}", "html": email_html(title, post, notes, test), "text": email_text(post, notes, test)}})
        out = {"week": week, "state": "done", "new": True, "record": record_txt(s)}
    return out


def load_stats(season, path=None):
    """nflverse weekly player stats (regular season) for grading; [] if it can't be loaded."""
    try:
        if path:
            text = Path(path).read_text()
        else:
            req = urllib.request.Request(STATS_CSV.format(season=season), headers={"User-Agent": "mingus-picks"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8")
        return [r for r in csv.DictReader(io.StringIO(text)) if r.get("season_type", "REG") == "REG"]
    except Exception as e:
        print(f"  WARNING: couldn't load nflverse stats for grading ({e})")
        return []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder with players/games/teams/meta.json")
    ap.add_argument("--store", required=True, help="the data-branch checkout")
    ap.add_argument("--now", default=None, help="ISO time to run as (testing)")
    ap.add_argument("--force-lock", action="store_true")
    ap.add_argument("--no-odds", action="store_true")
    ap.add_argument("--stats", default=None, help="local stats_player_week CSV (testing)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    data = Data(a.data)
    key = os.environ.get("ODDS_API_KEY")
    api = OddsAPI(key, a.store) if key and not a.no_odds else None
    stats_rows = load_stats(data.meta.get("season"), a.stats)
    rc = recap(data, a.store, stats_rows, now)       # first, so tonight's email can show the latest record
    lk = lock(data, a.store, now, api, a.force_lock)
    status = {"checked": now.isoformat(), "today": et_date(now), "lock": lk, "recap": rc,
              "credits": (api.usage if api else read(Path(a.store) / "odds" / "usage.json", {}))}
    write(Path(a.store) / "picks" / "status.json", status)
    print(f"Picks: {lk['day']} {lk['state']} ({lk.get('why', '')}); recap week {rc.get('week', '-')} {rc['state']}"
          f"{' ' + rc['record'] if rc.get('record') else ''}; credits left {status['credits'].get('remaining', '?')}")


if __name__ == "__main__":
    main()
