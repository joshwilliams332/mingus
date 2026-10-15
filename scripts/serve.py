#!/usr/bin/env python3
"""Run Mingus Sports locally, with the My League page able to add and sync ESPN leagues.

    python scripts/serve.py            # then open http://localhost:8000
    python scripts/serve.py 8080       # different port

Serves the site/ folder like `python -m http.server`, plus a tiny API the My League
page uses to save leagues to scripts/espn_config.json and sync them from ESPN. It only
listens on 127.0.0.1 (this computer), because the config can hold your ESPN login cookies.
"""

import io
import json
import re
import sys
from contextlib import redirect_stdout
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_data  # noqa: E402
import espn_sync  # noqa: E402

_roster_cache = {}


def current_season():
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


def roster_rows(season):
    """nflverse roster (for matching ESPN players), downloaded once per server run."""
    if season not in _roster_cache:
        _roster_cache[season] = build_data.build_roster(season)
    return _roster_cache[season]


def read_config():
    if espn_sync.CONFIG.exists():
        cfg = json.loads(espn_sync.CONFIG.read_text())
    else:
        cfg = {}
    # Move the old single-league format into the "leagues" list.
    if cfg.get("league_id"):
        cfg.setdefault("leagues", []).insert(0, {"league_id": cfg.pop("league_id"), "team_id": cfg.pop("team_id", "")})
    cfg.setdefault("leagues", [])
    return cfg


def write_config(cfg):
    espn_sync.CONFIG.write_text(json.dumps(cfg, indent=2))


def run_sync():
    """Sync every configured league; returns (ok, log lines)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            season = current_season()
            ok = espn_sync.sync(season, roster_rows(season))
        except Exception as e:
            print(f"  WARNING: sync failed ({e})")
            ok = False
    lines = [l.strip() for l in buf.getvalue().splitlines() if l.strip() and not l.strip().startswith("downloading")]
    if not read_config()["leagues"] and espn_sync.OUT.exists():
        espn_sync.OUT.unlink()  # no leagues left
    return ok, lines


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        # Requests must come from the site itself: other web pages can't send this custom
        # header to localhost without a CORS preflight, which this server never approves.
        if self.headers.get("X-Mingus") != "1":
            self._json(403, {"ok": False, "error": "forbidden"})
            return False
        return True

    def end_headers(self):
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store")  # always show freshly synced data
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/status"):
            if not self._allowed():
                return
            cfg = read_config()
            return self._json(200, {
                "ok": True,
                "leagues": [{k: l.get(k, "") for k in ("league_id", "team_id", "label")} for l in cfg["leagues"]],
                "has_cookies": bool(cfg.get("espn_s2") and cfg.get("swid")),
            })
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/") or not self._allowed():
            return self._json(404, {"ok": False})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "Bad request"})

        cfg = read_config()
        if self.path.startswith("/api/leagues"):
            league_id = str(body.get("league_id", "")).strip()
            team_id = str(body.get("team_id", "")).strip()
            if not re.fullmatch(r"\d+", league_id):
                return self._json(400, {"ok": False, "error": "League ID should be a number (the leagueId=... part of your ESPN link)."})
            if team_id and not re.fullmatch(r"\d+", team_id):
                return self._json(400, {"ok": False, "error": "Team ID should be a number (the teamId=... part of your ESPN link)."})
            entry = {"league_id": league_id, "team_id": team_id, "label": str(body.get("label", "")).strip()[:40]}
            cfg["leagues"] = [l for l in cfg["leagues"] if str(l.get("league_id")) != league_id] + [entry]
            if body.get("espn_s2") and body.get("swid"):
                cfg["espn_s2"], cfg["swid"] = body["espn_s2"].strip(), body["swid"].strip()
            write_config(cfg)
        elif self.path.startswith("/api/remove"):
            league_id = str(body.get("league_id", ""))
            cfg["leagues"] = [l for l in cfg["leagues"] if str(l.get("league_id")) != league_id]
            write_config(cfg)
        elif self.path.startswith("/api/clear-cookies"):
            cfg.pop("espn_s2", None)
            cfg.pop("swid", None)
            write_config(cfg)
            return self._json(200, {"ok": True, "log": ["ESPN cookies removed."]})
        elif not self.path.startswith("/api/sync"):
            return self._json(404, {"ok": False})

        ok, log = run_sync()
        return self._json(200, {"ok": ok or not cfg["leagues"], "log": log})

    def log_message(self, fmt, *args):
        # Keep the terminal quiet: only log league API calls.
        if args and "/api/" in str(args[0]):
            super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(Handler, directory=str(ROOT / "site"))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Mingus Sports running at http://localhost:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
