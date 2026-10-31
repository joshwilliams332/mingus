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
curl -fsSLo games.csv https://github.com/nflverse/nfldata/raw/master/data/games.csv
cd .. && export MINGUS_HIST=hist/
python3 scripts/backtest/build_features.py   # hist/features.pkl + the pre-tuning settings' score per season
python3 scripts/backtest/tune.py             # coordinate search on 2021-2025 -> hist/tuned.json
```

`engine.py` mirrors `projection()` and `chance_over()` in nfl_picks.py with every setting exposed (`CURRENT` = the
settings before tuning). If the model changes there, change it here too, or the backtest stops describing the real
model. Not backtested: the Sleeper blend and injury openings (no historical Sleeper projections or injury reports).
