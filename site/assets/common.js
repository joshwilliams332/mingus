// Shared by every Mingus Sports page: header/footer, data loading, fantasy scoring and formatting helpers.

const RANK_TABS = ["QB", "RB", "WR", "TE", "FLX", "K", "DST"];
const FLEX = ["RB", "WR", "TE"];
const TAB_LABELS = { QB: "Quarterbacks", RB: "Running Backs", WR: "Wide Receivers", TE: "Tight Ends", FLX: "Flex (RB/WR/TE)", K: "Kickers", DST: "Defense/Special Teams" };

const Mingus = {
  cache: {},

  async load(name) {
    if (!this.cache[name]) {
      this.cache[name] = fetch(`data/${name}.json`).then(r => {
        if (!r.ok) throw new Error(`Couldn't load data/${name}.json (${r.status})`);
        return r.json();
      });
    }
    return this.cache[name];
  },

  // The header and footer are injected here so every page shares one copy.
  renderChrome(meta) {
    const here = location.pathname.split("/").pop() || "index.html";
    const week = meta ? `${meta.season} · Week ${meta.next_week ?? meta.last_week}` : "";
    document.body.insertAdjacentHTML("afterbegin", `
      <header class="site-header">
        <div class="header-inner">
          <a class="brand" href="index.html" aria-label="Mingus Sports home">
            <span class="brand-mark" aria-hidden="true">M</span>
            <span class="brand-name">Mingus Sports</span>
          </a>
          <nav class="nav" aria-label="Main">
            <div class="nav-drop">
              <a href="rankings.html" ${here === "rankings.html" ? 'aria-current="page"' : ""} aria-haspopup="true">Rankings <span aria-hidden="true">▾</span></a>
              <div class="nav-menu">
                ${RANK_TABS.map(t => `<a href="rankings.html?pos=${t}"><strong>${t}</strong><span>${TAB_LABELS[t]}</span></a>`).join("")}
              </div>
            </div>
            <a href="games.html" ${here === "games.html" ? 'aria-current="page"' : ""}>Games</a>
          </nav>
          <span class="header-week">${esc(week)}</span>
        </div>
      </header>`);
    document.body.insertAdjacentHTML("beforeend", `
      <footer class="site-footer">
        Data from <a href="https://github.com/nflverse/nflverse-data">nflverse</a>${meta ? ` · updated ${esc(fmtDateTime(meta.built_at))}` : ""}
        <br>Mingus Sports is a fan site and isn't affiliated with the NFL.
      </footer>`);
  },

  // Loads meta, draws the header and footer, then runs the page's own code.
  async start(fn) {
    const main = document.querySelector("main");
    let meta = null;
    try {
      meta = await this.load("meta");
    } catch (e) { /* header still renders without the week */ }
    this.renderChrome(meta);
    try {
      await fn(main, meta);
    } catch (e) {
      console.error(e);
      main.innerHTML = `<div class="notice">Couldn't load the data. ${esc(e.message)}<br>
        If you opened this file directly, serve the folder instead: <code>python -m http.server -d site 8000</code></div>`;
    }
  },
};

// ---------- Fantasy scoring ----------
// The data holds raw stats only; points are worked out here so the format can be switched.

const FORMATS = { ppr: { label: "PPR", rec: 1 }, half: { label: "Half PPR", rec: 0.5 }, std: { label: "Standard", rec: 0 } };

const Scoring = {
  get() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem("mingus-scoring") || "{}"); } catch (e) { /* storage blocked */ }
    return { fmt: FORMATS[saved.fmt] ? saved.fmt : "ppr", passTd: saved.passTd === 6 ? 6 : 4 };
  },
  set(sc) {
    try { localStorage.setItem("mingus-scoring", JSON.stringify(sc)); } catch (e) { /* storage blocked */ }
  },
  label(sc) {
    return `${FORMATS[sc.fmt].label}${sc.passTd === 6 ? " · 6pt pass TD" : ""}`;
  },
};

function dstPointsAllowed(pa) {
  if (pa === 0) return 10;
  if (pa <= 6) return 7;
  if (pa <= 13) return 4;
  if (pa <= 20) return 1;
  if (pa <= 27) return 0;
  if (pa <= 34) return -1;
  return -4;
}

// Fantasy points for one game-log entry.
function scoreGame(e, pos, sc) {
  const v = k => e[k] || 0;
  let pts;
  if (pos === "K") {
    pts = 3 * v("fg_0_39") + 4 * v("fg_40_49") + 5 * v("fg_50") + v("xp") - v("fg_miss") - v("xp_miss");
  } else if (pos === "DST") {
    pts = v("sacks") + 2 * v("int") + 2 * v("fr") + 6 * v("td") + 2 * v("safety") + 2 * v("blk") + dstPointsAllowed(v("pa"));
  } else {
    pts = v("pass_yds") / 25 + sc.passTd * v("pass_td") - 2 * v("int")
      + v("rush_yds") / 10 + 6 * v("rush_td")
      + v("rec_yds") / 10 + 6 * v("rec_td") + FORMATS[sc.fmt].rec * v("rec")
      - 2 * v("fl") + 2 * v("two_pt") + 6 * v("st_td");
  }
  return Math.round(pts * 100) / 100;
}

// Season summary for a player under the chosen format: totals of every stat, points per game, last-3 average.
function summarize(p, sc) {
  const tot = {};
  const pts = p.log.map(e => scoreGame(e, p.pos, sc));
  for (const e of p.log) {
    for (const [k, val] of Object.entries(e)) if (typeof val === "number" && k !== "week") tot[k] = (tot[k] || 0) + val;
  }
  const g = p.log.length;
  const sum = pts.reduce((a, b) => a + b, 0);
  const last3 = pts.slice(-3);
  return {
    g, tot, pts,
    fpts: Math.round(sum * 10) / 10,
    ppg: g ? Math.round(sum / g * 10) / 10 : 0,
    last3: last3.length ? Math.round(last3.reduce((a, b) => a + b, 0) / last3.length * 10) / 10 : 0,
    fg_long: Math.max(0, ...p.log.map(e => e.fg_long || 0)),
  };
}

// Players need to have played in about half their team's games to be ranked by points per game.
function minGames(meta) {
  return Math.max(1, Math.ceil((meta?.last_week || 1) / 2));
}

// Ranks a list by points per game; players short of the games minimum go to the bottom.
function rankList(list, sc, meta) {
  const min = minGames(meta);
  return list
    .map(p => ({ p, s: summarize(p, sc) }))
    .sort((a, b) => ((b.s.g >= min) - (a.s.g >= min)) || (b.s.ppg - a.s.ppg));
}

// Scoring dropdowns. Changing one saves it (shared by every page) and calls onChange.
function scoringControls(sc, onChange) {
  const id = `sc${Math.random().toString(36).slice(2, 7)}`;
  setTimeout(() => {
    const fmtSel = document.getElementById(`${id}-fmt`), tdSel = document.getElementById(`${id}-td`);
    const fire = () => {
      const next = { fmt: fmtSel.value, passTd: Number(tdSel.value) };
      Scoring.set(next);
      onChange(next);
    };
    fmtSel.onchange = fire;
    tdSel.onchange = fire;
  });
  return `<div class="scoring">
    <label>Scoring
      <select id="${id}-fmt">${Object.entries(FORMATS).map(([k, f]) => `<option value="${k}" ${sc.fmt === k ? "selected" : ""}>${f.label}</option>`).join("")}</select>
    </label>
    <label>Pass TD
      <select id="${id}-td"><option value="4" ${sc.passTd === 4 ? "selected" : ""}>4 pts</option><option value="6" ${sc.passTd === 6 ? "selected" : ""}>6 pts</option></select>
    </label>
  </div>`;
}

// ---------- Teams, games and search ----------

// Matches "ATL", "atlanta", "falcons" or "atlanta falcons".
function teamMatches(abbr, q, teams) {
  const t = teams?.[abbr];
  const hay = [abbr, t?.city, t?.nickname, t && `${t.city} ${t.nickname}`].filter(Boolean).join(" | ").toLowerCase();
  return hay.includes(q);
}

// A team's view of a game: opponent, home/away, its own spread and implied total.
function teamGame(g, team) {
  const home = g.home === team;
  return {
    ...g,
    isHome: home,
    opp: home ? g.away : g.home,
    spread: g.home_spread === null ? null : home ? g.home_spread : -g.home_spread,
    implied: home ? g.home_implied : g.away_implied,
    score: g.home_score === null ? null : home ? [g.home_score, g.away_score] : [g.away_score, g.home_score],
  };
}

// The team's game in a given week, or null when they're on bye.
function weekGame(games, team, week) {
  const g = games.find(x => x.week === week && (x.home === team || x.away === team));
  return g ? teamGame(g, team) : null;
}

function oppLabel(tg) {
  return tg ? `${tg.isHome ? "vs." : "@"} ${tg.opp}` : "BYE";
}

// Against-the-spread and over/under results for a finished game.
function lineResults(g) {
  if (g.home_score === null || g.home_spread === null) return null;
  const ats = g.home_score - g.away_score + g.home_spread;
  const sum = g.home_score + g.away_score;
  return {
    cover: ats > 0 ? g.home : ats < 0 ? g.away : null,
    ou: g.total === null ? null : sum > g.total ? "Over" : sum < g.total ? "Under" : "Push",
    sum,
  };
}

// ---------- Formatting helpers ----------

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n, digits = 1) {
  if (n === null || n === undefined) return "—";
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(digits);
}
function fmtSpread(n) {
  if (n === null || n === undefined) return "—";
  return n === 0 ? "PK" : n > 0 ? `+${n}` : `${n}`;
}
function fmtDateTime(iso) {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function fmtKickoff(g) {
  const d = new Date(`${g.date}T${g.time || "13:00"}:00`);
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) +
    (g.time ? ` · ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} ET` : "");
}
function posBadge(pos) {
  return `<span class="pos pos-${esc(pos)}">${esc(pos)}</span>`;
}
function injuryTag(inj) {
  if (!inj) return "";
  const cls = { Questionable: "q", Doubtful: "d", Out: "out", DNP: "d", Limited: "q" }[inj.status] || "q";
  const short = { Questionable: "Q", Doubtful: "D", Out: "OUT" }[inj.status] || inj.status;
  const title = `${inj.status}${inj.injury ? ` — ${inj.injury}` : ""}`;
  return `<span class="inj inj-${cls}" title="${esc(title)}">${esc(short)}</span>`;
}
function headshot(p, size = "md") {
  if (p.pos === "DST") return `<span class="headshot ${size} placeholder team-mark" aria-hidden="true">${esc(p.team)}</span>`;
  return p.headshot
    ? `<img class="headshot ${size}" src="${esc(p.headshot)}" alt="" loading="lazy"
         onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'headshot ${size} placeholder',textContent:${esc(JSON.stringify(p.name[0]))}}))">`
    : `<span class="headshot ${size} placeholder" aria-hidden="true">${esc(p.name[0])}</span>`;
}
function playerUrl(p) {
  return `player.html?id=${encodeURIComponent(p.id)}`;
}
function spreadTag(n) {
  const cls = n < 0 ? "fav" : n > 0 ? "dog" : "";
  return `<span class="spread ${cls}">${fmtSpread(n)}</span>`;
}

// Game card used on the home and games pages. Before kickoff it shows the lines;
// once final it shows the score, the closing line and who covered.
function gameCard(g) {
  const final = g.home_score !== null;
  const res = lineResults(g);
  const row = (team, isHome) => {
    const tg = teamGame(g, team);
    const won = final && tg.score[0] > tg.score[1];
    const covered = res && res.cover === team;
    return `<div class="game-row ${won ? "winner" : ""}">
      <span class="team">${esc(team)}${isHome ? "<small>home</small>" : ""}${covered ? `<span class="badge cover">Covered</span>` : ""}</span>
      <span class="num">${spreadTag(tg.spread)}</span>
      <span class="num ${final ? "score" : ""}">${final ? tg.score[0] : fmt(tg.implied)}</span>
    </div>`;
  };
  return `<div class="game-card ${final ? "final" : ""}">
    <div class="when">${final ? "Final" : esc(fmtKickoff(g))}</div>
    <div class="game-cols"><span></span><span>Spread</span><span>${final ? "Score" : "Implied"}</span></div>
    ${row(g.away, false)}
    ${row(g.home, true)}
    <div class="game-foot">
      ${final && res
        ? `<span>O/U ${fmt(g.total)} · <strong class="ou-${res.ou.toLowerCase()}">${res.ou}</strong> (${res.sum})</span>${res.cover ? "" : "<span>ATS push</span>"}`
        : `<span>O/U ${fmt(g.total)}</span>`}
      <span class="stadium">${esc(g.stadium || "")}</span>
    </div>
  </div>`;
}
