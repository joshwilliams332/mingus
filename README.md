# Mingus Football

Fantasy football rankings, NFL stats and Vegas lines, built from [nflverse](https://github.com/nflverse/nflverse-data) data.

## Pages
- **Home** (`index.html`): Game of the Week banner, injury report, your articles, this week's games, a Top 5 by position and the week's best matchups.
- **Player Database** (`players.html?pos=…`): full season stat lines (passing, rushing, receiving, kicking, defense) plus total and per-game fantasy points, filterable by position and team.
- **Player page** (`player.html?id=…`): this week (projection, opponent, lines), season stats ranked within the position, NFL Next Gen Stats (QB passing, RB rushing, WR/TE receiving; ranked among qualifying players), bio, fantasy points by week and the game log.
- **Next Gen Stats** (`ngs.html?stat=<kind>.<key>&pos=…&hl=<id>`): leaderboards for every NFL Next Gen Stat (passing, receiving, rushing), filterable by position and sortable by any column. Under the Analytics menu; every stat on a player page links here with that player highlighted.
- **Start/Sit** (`startsit.html?p=<id>,<id>`): compare 2-4 players for this week. A verdict at the top (Start / Lean / Toss-up by projected points: Sleeper's projection, or a Mingus estimate from recent scoring, the defense vs the position and the Vegas team total), then a side-by-side table with a check on the best player in each category (projection, matchup, implied total, FPTS/G, last 3, floor, ceiling, snap %, target/opportunity share) and plain-English reasons. Players whose game is already final show their score and are left out of the call. Player pages link to it.
- **Weekly Rankings** (`rankings.html?pos=QB|RB|WR|TE|FLX|K|DST`): fantasy-only view: this week's opponent, the opponent's rank against the position, Sleeper projection, fantasy points per game, season total and last-3 average.
- **NFL Games** (`games.html?week=N`): any week's slate with lines, scores, covers and over/unders. Every game card opens its matchup page.
- **Matchup** (`game.html?id=…`): head-to-head with lines and moneylines, venue and weather, each team's last five games against the spread, over/under and implied points, and matchup edges (which positions each defense gives up the most to, with the players who benefit).
- **Teams** (`teams.html`): all 32 teams by division with records and this week's opponent, plus a Position breakdown table: what every defense gives up (or every offense produces) to QBs, RBs, WRs and TEs per game (fantasy points, targets, catches, yards, TDs, carries, yards per catch/carry, sacks, INTs), ranked and sortable.
- **Team** (`team.html?team=SEA`): record, a preview of this week's game (lines, and where each offense can attack the other defense: soft and tough spots by position, plus the players they help), defense by position with league ranks, an Offense box (points, EPA per play, yards, plays, pass/run split, attempts, carries, turnovers... per game, ranked), a season box score for the team's players (passing, rushing, receiving, kicking with fantasy points per game), and the full schedule with results and lines.
- **Player** (`player.html?id=…`): season so far, this week's matchup, injury note, bio, weekly points and game log.
- **Usage Trends** (`trends.html?pos=WR|TE|RB`): whose role is growing or shrinking. Biggest risers and fallers by target share (WR/TE) or opportunity share (RB: carries plus targets out of the team's), then a table of snap share by week, target/opportunity/carry share and red-zone looks over each player's last 3 games, with the change from his earlier games.
- **Analytics** (`analytics.html?pos=WR&x=tgt&y=rec_yds`): a chart builder. Pick a position and any two stats (volume, efficiency, air yards, YAC, EPA, target share, WOPR, CPOE, fantasy points and more) and it plots every qualifying player, with the correlation (r) explained in plain words, the trend line, quadrants and the players furthest above and below the trend. Choose the weeks, a minimum volume, and season totals or per game; the URL keeps the chosen axes so a chart can be shared.

## Projections
Weekly Rankings are ordered by **Sleeper's** projection for the week, pulled from `api.sleeper.app` by `build_data.py` and shown in your chosen scoring format. The rankings page also shows how far off Sleeper's projections have been on weeks already played, and the player page game log shows Sleeper's projection next to the actual score.

If Sleeper can't be reached during a data update, the build keeps going without projections and the rankings fall back to fantasy points per game.

## Your notes and articles
Edit the files in `site/content/` (the data script never touches them):
- `notes.json`: notes for games, players and teams (shown on their pages), plus `featured_game` to pick the home page's Game of the Week.
- `articles.json`: the "From Mingus" posts on the home page.

Weather forecasts for upcoming outdoor games come from [Open-Meteo](https://open-meteo.com) in the visitor's browser, about two weeks out.

## Night-game best bets
`scripts/nfl_picks.py` (run by `.github/workflows/nfl-picks.yml`, separate from the site deploy) picks player props for night games (Thursday, Sunday and Monday night, plus late-season Saturdays):

1. **Lock.** On the first run within 4 hours of kickoff, it pulls player props from [The Odds API](https://the-odds-api.com) for that game (passing, rushing and receiving yards, and receptions: 4 credits per game), compares each line with our projection (Sleeper's when available, otherwise a Mingus estimate from recent games and the defense), and locks up to 2 picks per game. A pick's chance blends our projection (30%) with the books' no-vig price (70%); it needs at least a 54% chance and a 3% edge at the best posted price. Players on the injury report are skipped.
2. **Save.** Picks, the props snapshot they came from, and a ready-to-post email go to the `data` branch (`picks/`, `odds/`). Locked picks are never rewritten.
3. **Grade.** The morning after, picks are graded from nflverse box scores (a player who didn't play is a void, like at the sportsbooks) into that night's results. Each week's recap and the season record are written once the week's night games are graded.

Scheduled Claude tasks email the picks to Josh at 6:00 PM ET on game nights, the results the next morning at 8:41 AM ET, and the weekly recap on Tuesday; Josh posts them himself. It needs the `ODDS_API_KEY` repository secret.

```sh
python3 -m unittest discover -s tests                       # tests
python3 scripts/nfl_picks.py --data site/data --store store --no-odds   # local run without spending credits
```

## Model review
`scripts/model_review.py` (run by `.github/workflows/model-review.yml`) keeps the projection model honest and improving:
it saves every regular's projection before kickoff, scores them once the box scores are out (`model/scorecard.json` on
the `data` branch), and after each finished week tries new settings, keeping them only if they would have beaten the
current ones on that week. `scripts/backtest/` holds the multi-season backtest it builds on, and `scripts/prop_tool/`
builds the weekly over/under tool page (a private page outside the site).

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
| `stats_team/stats_team_week_<season>.csv` | weekly team defense stats for D/ST, and team offense (`teamstats.json`) for team pages |
| `snap_counts/snap_counts_<season>.csv` | offensive snap share per game (Usage Trends, player game logs) |
| `pbp/play_by_play_<season>.csv.gz` | red-zone targets and carries (Usage Trends) |
| `nextgen_stats/ngs_{passing,receiving,rushing}.csv.gz` | NFL Next Gen Stats season numbers (player pages) |
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
`.github/workflows/update-and-deploy.yml` rebuilds the data and deploys the site to GitHub Pages every evening (23:17 UTC, so the day's injury reports are included), a few hours after each game window (Sunday early and late games, Sunday, Monday and Thursday night games) so finals and stats show up the same night, on every push to `main`, and whenever you click **Run workflow** in the Actions tab.

One-time setup: in the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.
