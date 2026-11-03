# Mingus Football

An all-in-one fantasy football site: who's been producing, who's projected to produce, and who to start this week.
Rankings, projections, usage trends and matchup help in one place, built from [nflverse](https://github.com/nflverse/nflverse-data)
data and Sleeper projections.

**This is a fantasy site** We use Vegas lines, because the market knows a lot: a team expected
to score 28 points gives its players more chances than a team expected to score 17. So implied team totals feed the
projections, start/sit calls and matchup notes.

## What it helps you answer

### Who's been good?
- **Player Database** (`players.html?pos=…`): full season stat lines (passing, rushing, receiving, kicking, defense) plus total and per-game fantasy points, filterable by position and team.
- **Player page** (`player.html?id=…`): season stats ranked within the position, fantasy points by week, the game log (with snap share, opportunity share and target share), NFL Next Gen Stats (ranked among qualifying players), injury note and bio.
- **Usage Trends** (`trends.html?pos=WR|TE|RB`): whose role is growing or shrinking. Biggest risers and fallers by target share (WR/TE) or opportunity share (RB: carries plus targets out of the team's), then snap share by week, target/opportunity/carry share and red-zone looks over each player's last 3 games, with the change from his earlier games. Usage moves before fantasy points do.
- **Next Gen Stats** (`ngs.html?stat=<kind>.<key>&pos=…&hl=<id>`): leaderboards for every NFL Next Gen Stat (passing, receiving, rushing), filterable by position and sortable by any column, including "Separation vs. depth" so screen-heavy receivers don't top the list. Every stat on a player page links here with that player highlighted.
- **Analytics** (`analytics.html?pos=WR&x=tgt&y=rec_yds`): a chart builder. Pick a position and any two stats (volume, efficiency, air yards, YAC, EPA, target share, WOPR, CPOE, fantasy points and more) and it plots every qualifying player, with the correlation explained in plain words, the trend line, quadrants and the players furthest above and below it. Choose the weeks, a minimum volume, and season totals or per game; the URL keeps the chart so it can be shared.

### Who's projected to be good?
- **Weekly Rankings** (`rankings.html?pos=QB|RB|WR|TE|FLX|K|DST`): this week's projection, opponent and how that defense ranks against the position, fantasy points per game, season total and last-3 average. It also shows how close past projections came on weeks already played.
- **Player page:** this week's projection, opponent and team total, next to how he's actually been scoring.

### Who should I start?
- **Start/Sit** (`startsit.html?p=<id>,<id>`): compare 2-4 players for this week. A verdict at the top (Start / Lean / Toss-up), then a side-by-side table with a check on the best player in each category (projection, matchup, team total, FPTS/G, last 3, floor, ceiling, snap %, target/opportunity share) and plain-English reasons. Players whose game is already final show their score and are left out of the call. Player pages link to it.

### Which matchups help?
- **Teams** (`teams.html`): all 32 teams by division with this week's opponent, plus a Position breakdown: what every defense gives up (or every offense produces) to QBs, RBs, WRs and TEs per game (fantasy points, targets, catches, yards, TDs, carries, yards per catch/carry, sacks, INTs), ranked and sortable.
- **Team** (`team.html?team=SEA`): defense by position with league ranks, an Offense box (points, EPA per play, yards, plays, pass/run split, turnovers... per game, ranked), a season box score for the team's players with fantasy points per game, a Next game card and the schedule.
- **Matchup** (`game.html?id=…`): before kickoff, where each offense can attack (each defense's soft and tough spots by position, and the players who benefit) and the matchup edges; after the game, the box score with each player's projection next to what he scored. Also venue, weather and each team's expected points.
- **NFL Games** (`games.html?week=N`): any week's slate with scores and the Vegas lines (useful context for which games should be high scoring). Every game opens its matchup page.
- **Home** (`index.html`): Game of the Week, injury report, articles, this week's games, a Top 5 by position and the week's best matchups.

## How the projections work
- **Sleeper's projection** for the week is the starting point (pulled from `api.sleeper.app` by `build_data.py`, shown in your scoring format).
- **Mingus estimate** when Sleeper doesn't have one: recent fantasy scoring (season average and last 3), adjusted for how the defense does against the position and for the team's expected points from the Vegas total.
- **Keeping them honest:** `scripts/model_review.py` (with the model itself in `scripts/projections.py`) saves projections before every kickoff and scores them once the box scores are out, week by week, and only changes the model's settings when the change would have done better on games it hadn't seen. The same loop tracks each player's chance to score a touchdown. `scripts/backtest/` holds the multi-season tests (2021-2025, then checked on 2026) behind those settings.

If Sleeper can't be reached during a data update, the build keeps going and the rankings fall back to fantasy points per game.

## Scoring
Pick **PPR**, **Half PPR** or **Standard**, and **4 or 6 points per passing TD**. The choice is saved in the browser and shared by every page.
- Offense: 1 pt per 25 pass yds, 4/6 per pass TD, -2 per INT, 1 per 10 rush/rec yds, 6 per rush/rec TD, 0/0.5/1 per catch, -2 per fumble lost, 2 per two-point conversion.
- Kickers: 3 pts for FGs of 0-39 yards, 4 for 40-49, 5 for 50+, 1 per extra point, -1 per miss.
- D/ST: 1 per sack, 2 per INT, fumble recovery, safety or blocked kick, 6 per TD, plus 10/7/4/1/0/-1/-4 for allowing 0/1-6/7-13/14-20/21-27/28-34/35+ points.

Players are ranked by points per game; anyone who has played fewer than half their team's games is listed last.

## Your notes and articles
Edit the files in `site/content/` (the data script never touches them):
- `notes.json`: notes for games, players and teams (shown on their pages), plus `featured_game` to pick the home page's Game of the Week.
- `articles.json`: the "From Mingus" posts on the home page.

Weather forecasts for upcoming outdoor games come from [Open-Meteo](https://open-meteo.com) in the visitor's browser, about two weeks out.

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
| `schedules/games.csv` | schedule, scores, Vegas totals and spreads (for team totals), roof and surface |

## Run locally
```sh
python3 scripts/build_data.py        # fetch the latest data
python3 -m http.server -d site 8000  # then open http://localhost:8000
python3 -m unittest discover -s tests   # tests
```
The pages load JSON with `fetch`, so they need a local server; opening the HTML file directly won't work.

## Automatic updates
`.github/workflows/update-and-deploy.yml` rebuilds the data and deploys the site to GitHub Pages every evening (23:17 UTC, so the day's injury reports are included), a few hours after each game window (Sunday early and late games, Sunday, Monday and Thursday night games) so finals and stats show up the same night, on every push to `main`, and whenever you click **Run workflow** in the Actions tab.

One-time setup: in the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.

