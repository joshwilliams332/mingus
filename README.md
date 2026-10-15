# Mingus Sports

Fantasy football rankings, NFL stats and Vegas lines, built from [nflverse](https://github.com/nflverse/nflverse-data) data.

## Pages
- **Home** (`index.html`): Game of the Week banner, injury report, your articles, this week's games, a Top 5 by position and the week's best matchups.
- **Player Database** (`players.html?pos=…`): full season stat lines (passing, rushing, receiving, kicking, defense) plus total and per-game fantasy points, filterable by position and team.
- **Weekly Rankings** (`rankings.html?pos=QB|RB|WR|TE|FLX|K|DST`): fantasy-only view: this week's opponent, the opponent's rank against the position, Sleeper projection, fantasy points per game, season total and last-3 average.
- **NFL Games** (`games.html?week=N`): any week's slate with lines, scores, covers and over/unders. Every game card opens its matchup page.
- **Matchup** (`game.html?id=…`): head-to-head with lines and moneylines, venue and weather, each team's last five games against the spread, over/under and implied points, and matchup edges (which positions each defense gives up the most to, with the players who benefit).
- **Team** (`team.html?team=SEA`): record, ATS and O/U record, full schedule with results, fantasy players and defense vs position.
- **Player** (`player.html?id=…`): season so far, this week's matchup, injury note, bio, weekly points and game log.

## Projections
Weekly Rankings are ordered by **Sleeper's** projection for the week, pulled from `api.sleeper.app` by `build_data.py` and shown in your chosen scoring format. The rankings page also shows how far off Sleeper's projections have been on weeks already played, and the player page game log shows Sleeper's projection next to the actual score.

If Sleeper can't be reached during a data update, the build keeps going without projections and the rankings fall back to fantasy points per game.

## ESPN league sync (My League)
`scripts/espn_sync.py` pulls an ESPN fantasy league (rosters, lineups, standings, schedule and scoring settings) into `site/data/league.json`, and a **My League** page appears in the header once that file exists.

1. Copy `scripts/espn_config.example.json` to `scripts/espn_config.json` and fill in `league_id` and `team_id` (from your ESPN team page URL).
2. Private league: also fill in `espn_s2` and `swid` (instructions are in the example file). Treat them like a password.
3. Run `python scripts/build_data.py` (or just `python scripts/espn_sync.py`). Look for a line like `ESPN league 'Your League': 10 teams, 140/140 rostered players matched`.

`espn_config.json` and `league.json` are git-ignored, so your league stays on your computer and isn't published. ESPN's API is unofficial and may change.

## Your notes and articles
Edit the files in `site/content/` (the data script never touches them):
- `notes.json`: notes for games, players and teams (shown on their pages), plus `featured_game` to pick the home page's Game of the Week.
- `articles.json`: the "From Mingus" posts on the home page.

Weather forecasts for upcoming outdoor games come from [Open-Meteo](https://open-meteo.com) in the visitor's browser, about two weeks out.

## Scoring
Pick **PPR**, **Half PPR** or **Standard**, and **4 or 6 points per passing TD**. The choice is saved in the browser and shared by every page.
- Offense: 1 pt per 25 pass yds, 4/6 per pass TD, -2 per INT, 1 per 10 rush/rec yds, 6 per rush/rec TD, 0/0.5/1 per catch, -2 per fumble lost, 2 per two-point conversion.
- Kickers: 3 pts for FGs of 0-39 yards, 4 for 40-49, 5 for 50+, 1 per extra point, -1 per miss.
- D/ST: 1 per sack, 2 per INT, fumble recovery, safety or blocked kick, 6 per TD, plus 10/7/4/1/0/-1/-4 for allowing 0/1-6/7-13/14-20/21-27/28-34/35+ points.

Players are ranked by points per game; anyone who has played fewer than half their team's games is listed last.

## Data
`scripts/build_data.py` downloads these nflverse files and writes `site/data/*.json`:

| File | Used for |
| --- | --- |
| `stats_player/stats_player_week_<season>.csv` | weekly game logs for QB/RB/WR/TE/K |
| `stats_team/stats_team_week_<season>.csv` | weekly team defense stats for D/ST |
| `rosters/roster_<season>.csv` | team, number, bio |
| `injuries/injuries_<season>.csv` | injury tags (game status, or practice status midweek) |
| `schedules/games.csv` | schedule, scores, spreads, totals, moneylines, roof and surface |

## Run locally
```sh
python3 scripts/build_data.py        # fetch the latest data
python3 -m http.server -d site 8000  # then open http://localhost:8000
```
The pages load JSON with `fetch`, so they need a local server; opening the HTML file directly won't work.

## Automatic updates
`.github/workflows/update-and-deploy.yml` rebuilds the data and deploys the site to GitHub Pages every Tuesday, on every push to `main`, and whenever you click **Run workflow** in the Actions tab.

One-time setup: in the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.
