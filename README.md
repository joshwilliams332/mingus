# Mingus

NFL rankings, stats and Vegas lines, built from [nflverse](https://github.com/nflverse/nflverse-data) data.

## Pages
- **Home** (`index.html`): top 12 players, top 5 at each position and this week's games with spreads.
- **Players** (`players.html`): every QB, RB, WR and TE, with position filters, search and sortable stat columns.
- **Player** (`player.html?id=…`): season totals, next game with spread/total/implied points, injury report, bio, weekly points chart and game log.
- **Games** (`games.html`): any week's slate, with lines before kickoff and scores after.

The header and footer live in `site/assets/common.js` and appear on every page.

## Data
`scripts/build_data.py` downloads these nflverse files and writes `site/data/*.json`:

| File | Used for |
| --- | --- |
| `stats_player/stats_player_reg_<season>.csv` | season totals, rankings |
| `stats_player/stats_player_week_<season>.csv` | weekly game logs |
| `rosters/roster_<season>.csv` | team, number, bio |
| `injuries/injuries_<season>.csv` | injury tags (game status, or practice status midweek) |
| `schedules/games.csv` | schedule, scores, spreads, totals |

Players are ranked by total PPR fantasy points.

## Run locally
```sh
python3 scripts/build_data.py        # fetch the latest data
python3 -m http.server -d site 8000  # then open http://localhost:8000
```
The pages load JSON with `fetch`, so they need a local server; opening the HTML file directly won't work.

## Automatic updates
`.github/workflows/update-and-deploy.yml` rebuilds the data and deploys the site to GitHub Pages every Tuesday, on every push to `main`, and whenever you click **Run workflow** in the Actions tab.

One-time setup: in the repository go to **Settings → Pages** and set **Source** to **GitHub Actions**.
