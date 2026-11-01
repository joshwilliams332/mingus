# Football model backtest

Replays past seasons through the projection model. Each game is projected only from earlier games that season, and
the chance of the over is scored against a "typical" line (floor of his average so far + 0.5), because historical
sportsbook prop lines aren't available. Used Oct 31, 2026 to tune the settings in `scripts/nfl_picks.py`
(2021-2025 to tune, 2026 held out). Results are in CLAUDE.md.

```sh
mkdir hist && cd hist
for s in 2021 2022 2023 2024 2025 2026; do
  curl -fsSLo stats_$s.csv https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_$s.csv
done
# optional, for the snap-share test (P["snap"] in engine.py): snaps_<season>.csv and roster_<season>.csv
#   from .../snap_counts/snap_counts_$s.csv and .../rosters/roster_$s.csv
curl -fsSLo games.csv https://github.com/nflverse/nfldata/raw/master/data/games.csv
cd .. && export MINGUS_HIST=hist/
python3 scripts/backtest/build_features.py   # hist/features.pkl + the pre-tuning settings' score per season
python3 scripts/backtest/tune.py             # coordinate search on 2021-2025 -> hist/tuned.json
```

`engine.py` mirrors `projection()` and `chance_over()` in nfl_picks.py with every setting exposed (`CURRENT` = the
settings before tuning). If the model changes there, change it here too, or the backtest stops describing the real
model. Not backtested: the Sleeper blend and injury openings (no historical Sleeper projections or injury reports).

## Anytime touchdowns (`td/`)
The TD model in `nfl_picks.td_chance` (Nov 1, 2026). Offline only (needs numpy + scikit-learn). Folder layout: `ROOT/hist/`
(stats + games.csv as above), `ROOT/pbp/pbp_<season>.csv.gz` (nflverse `pbp/play_by_play_<season>.csv.gz`), `ROOT/td/`.

```sh
for s in 2021 2022 2023 2024 2025 2026; do python3 scripts/backtest/td/extract.py ROOT $s; done  # red-zone usage
python3 scripts/backtest/td/features.py ROOT    # one row per player game (week 4+, 3+ earlier games)
python3 scripts/backtest/td/fit.py ROOT         # fit 2021-2025, test 2026 -> ROOT/td/td_model.json (copy into TD_MODEL)
```
Results: Brier 0.1674 on 2021-2025 held out by season and 0.1790 on 2026 (his own TD rate alone: 0.1738 / 0.1919).
Inside-10 / inside-5 carries and the defense's TDs allowed to the position added nothing, so the shipped model uses
only fields players.json already has.
