# Mingus Sports

Fantasy football rankings, NFL stats and Vegas lines, built from [nflverse](https://github.com/nflverse/nflverse-data) data.

## Pages
- **Home** (`index.html`): top players, position leaders and this week's games with spreads.
- **Rankings** (`rankings.html?pos=QB|RB|WR|TE|FLX|K|DST`): fantasy points per game with this week's opponent and season stats. Opened from the Rankings dropdown in the header.
- **Player** (`player.html?id=…`): season so far, this week's matchup and lines, injury note, bio, weekly points chart and game log.
- **Games** (`games.html?week=N`): any week's slate. Upcoming games show spreads and implied totals; finished games show the score, who covered and whether the total went over or under.

The header and footer live in `site/assets/common.js` and appear on every page.

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
| `schedules/games.csv` | schedule, scores, spreads, totals |

## Run locally
```sh
python3 scripts/build_data.py        # fetch the latest data
python3 -m http.server -d site 8000  # then open http://localhost:8000
```
The pages load JSON with `fetch`, so they need a local server; opening the HTML file directly won't work.

## Automatic updates
`.github/workflows/update-and-deploy.yml` rebuilds the data and deploys the site to GitHub Pages every Tuesday, on every push to `main`, and whenever you click **Run workflow** in the Actions tab.

One-time setup: in the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.
