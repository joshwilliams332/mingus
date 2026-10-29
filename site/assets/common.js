// Shared by every Mingus FF page: header/footer, data loading, fantasy scoring and formatting helpers.

const RANK_TABS = ["QB", "RB", "WR", "TE", "FLX", "K", "DST"];
const FLEX = ["RB", "WR", "TE"];
const TAB_LABELS = { QB: "Quarterbacks", RB: "Running Backs", WR: "Wide Receivers", TE: "Tight Ends", FLX: "Flex (RB/WR/TE)", K: "Kickers", DST: "Defense/Special Teams" };

const Mingus = {
  cache: {},

  async load(name) {
    if (!this.cache[name]) {
      // "no-cache" makes the browser check for a newer copy every time (a quick "not modified" when
      // nothing changed), so a new deploy's pages never run on yesterday's data.
      this.cache[name] = fetch(`data/${name}.json`, { cache: "no-cache" }).then(r => {
        if (!r.ok) throw new Error(`Couldn't load data/${name}.json (${r.status})`);
        return r.json();
      });
    }
    return this.cache[name];
  },

  // Hand-written content (notes, articles). Missing or broken files just mean "no content".
  async content(name, fallback) {
    try {
      const r = await fetch(`content/${name}.json`, { cache: "no-cache" });
      return r.ok ? await r.json() : fallback;
    } catch (e) {
      return fallback;
    }
  },

  // The header and footer are injected here so every page shares one copy.
  renderChrome(meta) {
    const here = location.pathname.split("/").pop() || "index.html";
    const week = meta ? `${meta.season} · Week ${meta.next_week ?? meta.last_week}` : "";
    document.body.insertAdjacentHTML("afterbegin", `
      <header class="site-header">
        <div class="header-inner">
          <a class="brand" href="index.html" aria-label="Mingus FF home">
            <span class="brand-mark" aria-hidden="true">M</span>
            <span class="brand-name">Mingus FF</span>
          </a>
          <nav class="nav" aria-label="Main">
            <div class="nav-drop">
              <a href="players.html" ${here === "players.html" || here === "player.html" ? 'aria-current="page"' : ""} aria-haspopup="true"><span class="nl">Player Database</span><span class="ns">Players</span> <span class="caret" aria-hidden="true">▾</span></a>
              <div class="nav-menu">
                <a href="players.html"><strong>All</strong><span>Every position</span></a>
                ${["QB", "RB", "WR", "TE", "K", "DST"].map(t => `<a href="players.html?pos=${t}"><strong>${t}</strong><span>${TAB_LABELS[t]}</span></a>`).join("")}
              </div>
            </div>
            <div class="nav-drop">
              <a href="rankings.html" ${here === "rankings.html" ? 'aria-current="page"' : ""} aria-haspopup="true"><span class="nl">Fantasy Rankings</span><span class="ns">Rankings</span> <span class="caret" aria-hidden="true">▾</span></a>
              <div class="nav-menu">
                ${RANK_TABS.map(t => `<a href="rankings.html?pos=${t}"><strong>${t}</strong><span>${TAB_LABELS[t]}</span></a>`).join("")}
              </div>
            </div>
            <a href="startsit.html" ${here === "startsit.html" ? 'aria-current="page"' : ""}><span class="nl">Start/Sit</span><span class="ns">Start/Sit</span></a>
            <a href="games.html" ${["games.html", "game.html"].includes(here) ? 'aria-current="page"' : ""}><span class="nl">Schedule</span><span class="ns">Schedule</span></a>
            <a href="teams.html" ${["teams.html", "team.html"].includes(here) ? 'aria-current="page"' : ""}><span class="nl">Teams</span><span class="ns">Teams</span></a>
            <a href="trends.html" ${here === "trends.html" ? 'aria-current="page"' : ""}><span class="nl">Trends</span><span class="ns">Trends</span></a>
            <div class="nav-drop">
              <a href="analytics.html" ${["analytics.html", "ngs.html"].includes(here) ? 'aria-current="page"' : ""} aria-haspopup="true"><span class="nl">Analytics</span><span class="ns">Analytics</span> <span class="caret" aria-hidden="true">▾</span></a>
              <div class="nav-menu wide right">
                <a href="analytics.html"><strong>Chart builder</strong><span>Any two stats, plotted</span></a>
                <a href="ngs.html"><strong>Next Gen Stats</strong><span>NFL tracking leaderboards</span></a>
              </div>
            </div>
          </nav>
          <span class="header-week">${esc(week)}</span>
        </div>
      </header>`);
    document.body.insertAdjacentHTML("beforeend", `
      <footer class="site-footer">
        Data from <a href="https://github.com/nflverse/nflverse-data">nflverse</a>${meta ? ` · updated ${esc(fmtDateTime(meta.built_at))}` : ""}
        <br>Mingus FF is a fan site and isn't affiliated with the NFL.
      </footer>`);
  },

  // "Back" links return to the page you came from (e.g. the matchup page), falling back to their href.
  wireBackLinks() {
    document.addEventListener("click", e => {
      const a = e.target.closest("a[data-back]");
      if (!a || !document.referrer) return;
      try {
        if (new URL(document.referrer).origin === location.origin && history.length > 1) {
          e.preventDefault();
          history.back();
        }
      } catch (err) { /* follow the link normally */ }
    });
  },

  // Loads meta, draws the header and footer, then runs the page's own code.
  async start(fn) {
    const main = document.querySelector("main");
    let meta = null;
    try {
      meta = await this.load("meta");
    } catch (e) { /* header still renders without the week */ }
    this.renderChrome(meta);
    const current = document.querySelector('.nav [aria-current="page"]'), nav = document.querySelector(".nav");
    if (current && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = current.offsetLeft - nav.clientWidth / 2 + current.offsetWidth / 2;
    this.wireBackLinks();
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
// Kickoff stacked on two lines ("Mon, Oct 19" over "8:15 PM ET") so it fits narrow table cells.
function kickoffCell(g) {
  const d = new Date(`${g.date}T${g.time || "13:00"}:00`);
  return `<span class="sched-when muted">${esc(d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }))}` +
    (g.time ? `<small>${esc(d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))} ET</small>` : "") + `</span>`;
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
function backLink(fallbackHref) {
  return `<a class="back" href="${fallbackHref}" data-back>← Back</a>`;
}
// Small colored rank chip for how a defense treats a position (1st = allows the most = best matchup).
function matchupChip(d, opp, pos) {
  if (!d) return `<span class="muted">—</span>`;
  return `<span class="mchip ${matchupClass(d.rank)}" title="${esc(opp)} allows the ${ordinal(d.rank)}-most fantasy pts to ${pos}s (${d.ppg}/game)">${ordinal(d.rank)}</span>`;
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
// One row of the schedule: both teams with logos, then the spread and total. Before kickoff it shows
// each team's implied points; once final it shows the score, who covered and how the total landed.
function scheduleRow(g, teams) {
  const final = g.home_score !== null;
  const res = lineResults(g);
  const fav = g.home_spread === null ? null : g.home_spread <= 0 ? g.home : g.away;
  const side = (team, isHome) => {
    const tg = teamGame(g, team);
    const won = final && tg.score[0] > tg.score[1];
    const name = `<span class="sr-name">${esc(teamName(team, teams, false))}<small>${final ? esc(team) : `${esc(team)} · ${fmt(tg.implied)} implied`}</small></span>`;
    const score = final ? `<span class="sr-score ${won ? "won" : ""}">${tg.score[0]}</span>` : "";
    return `<span class="sr-team ${isHome ? "home" : "away"} ${final && !won ? "lost" : ""}">
      ${isHome ? `${score}${name}${teamMark(team, teams, "md")}` : `${teamMark(team, teams, "md")}${name}${score}`}</span>`;
  };
  const spread = fav === null ? "—" : g.home_spread === 0 ? "Pick'em" : `${esc(fav)} ${fmtSpread(-Math.abs(g.home_spread))}`;
  return `<a class="sched-row ${final ? "final" : ""}" href="${gameUrl(g)}">
    <span class="sr-matchup">${side(g.away, false)}<span class="sr-at">${final ? "–" : "@"}</span>${side(g.home, true)}</span>
    <span class="sr-lines">
      <span class="sr-line"><span class="sr-k">Spread</span><strong>${spread}</strong>${res ? `<span class="sr-res">${res.cover ? `${esc(res.cover)} covered` : "Push"}</span>` : ""}</span>
      <span class="sr-line"><span class="sr-k">Total</span><strong>${fmt(g.total)}</strong>${res?.ou ? `<span class="sr-res">${res.ou} · ${res.sum}</span>` : ""}</span>
    </span>
  </a>`;
}

// ---------- Teams, matchups and weather ----------

function gameUrl(g) { return `game.html?id=${encodeURIComponent(g.id)}`; }
function teamUrl(abbr) { return `team.html?team=${encodeURIComponent(abbr)}`; }
function teamName(abbr, teams, full = true) {
  const t = teams?.[abbr];
  return t ? (full ? `${t.city} ${t.nickname}` : t.nickname) : abbr;
}
// Team logo (linked from ESPN). If the image can't load, the colored abbreviation badge takes its place.
function teamMark(abbr, teams, size = "md") {
  const t = teams?.[abbr];
  const badge = `<span class="team-badge ${size}" style="--tc:${t?.color || "#556"}">${esc(abbr)}</span>`;
  if (!t?.logo) return badge;
  return `<img class="team-logo ${size}" src="${esc(t.logo)}" alt="${esc(abbr)}" loading="lazy" data-fallback="${esc(badge)}" onerror="this.outerHTML=this.dataset.fallback">`;
}

// Every finished game for a team with betting results from that team's side.
function teamResults(games, team) {
  return games
    .filter(g => g.type === "REG" && g.home_score !== null && (g.home === team || g.away === team))
    .sort((a, b) => a.week - b.week)
    .map(g => {
      const tg = teamGame(g, team);
      const [pf, pa] = tg.score;
      const ats = tg.spread === null ? null : pf - pa + tg.spread;
      return {
        ...tg, pf, pa,
        result: pf > pa ? "W" : pf < pa ? "L" : "T",
        ats: ats === null ? null : ats > 0 ? "W" : ats < 0 ? "L" : "P",
        ou: g.total === null ? null : pf + pa > g.total ? "O" : pf + pa < g.total ? "U" : "P",
        vsImplied: tg.implied === null ? null : Math.round((pf - tg.implied) * 10) / 10,
      };
    });
}
// Per-game averages for every team (points scored, allowed, and vs the implied total) from finished
// regular-season games before beforeWeek.
function teamAverages(games, beforeWeek = Infinity) {
  const out = {};
  for (const team of new Set(games.flatMap(g => [g.home, g.away]))) {
    const rs = teamResults(games, team).filter(r => r.week < beforeWeek);
    if (!rs.length) continue;
    const mean = list => (list.length ? Math.round(list.reduce((a, b) => a + b, 0) / list.length * 10) / 10 : null);
    out[team] = { pf: mean(rs.map(r => r.pf)), pa: mean(rs.map(r => r.pa)), vs: mean(rs.filter(r => r.vsImplied !== null).map(r => r.vsImplied)) };
  }
  return out;
}
// " (5th)" after a stat: where a value ranks in a list of values (1st = highest, or lowest when lowBetter).
// Ties share the better rank. Top 5 is highlighted green, or red when bad is set (most interceptions thrown).
function rankTag(value, values, lowBetter = false, title = "", bad = false, showOf = false) {
  const pool = values.filter(x => x !== null && x !== undefined);
  if (value === null || value === undefined || pool.length < 2) return "";
  const r = pool.filter(x => (lowBetter ? x < value : x > value)).length + 1;
  return ` <span class="rank-tag ${r <= 5 ? (bad ? "top bad" : "top") : ""}" title="${esc(`${ordinal(r)} of ${pool.length}${title ? ` ${title}` : ""}`)}">(${ordinal(r)}${showOf ? ` of ${pool.length}` : ""})</span>`;
}
// Where a game's over/under and a team's implied total rank among that week's games (1st = highest).
function weekLineRanks(games, week) {
  const wk = games.filter(g => g.week === week && g.total !== null);
  const totals = wk.map(g => g.total);
  const implied = wk.flatMap(g => [g.home_implied, g.away_implied]);
  return {
    total: g => rankTag(g.total, totals, false, `Week ${week} games, by over/under`, false, true),
    implied: v => rankTag(v, implied, false, `Week ${week} teams, by implied points`, false, true),
  };
}
// Rank of one team's average among all teams, e.g. rankOf(avg, "SF", "pa", true).
function rankOf(avg, team, key, lowBetter = false) {
  return rankTag(avg[team]?.[key], Object.values(avg).map(t => t[key]), lowBetter, `NFL teams${lowBetter ? " (fewest = 1st)" : ""}`);
}
// "3-2" style records from a list of results.
function record(list, key, win = "W", loss = "L") {
  const w = list.filter(r => r[key] === win).length, l = list.filter(r => r[key] === loss).length;
  const p = list.filter(r => r[key] === "P" || r[key] === "T").length;
  return `${w}-${l}${p ? `-${p}` : ""}`;
}

// Fantasy points each defense allows per game to each position, ranked 1 (most allowed = best matchup) to 32.
// Pass beforeWeek to only count games played before that week (used for projections).
function defenseVsPos(players, games, sc, beforeWeek = Infinity) {
  const allowed = {};
  for (const p of players) {
    if (!["QB", "RB", "WR", "TE", "K"].includes(p.pos)) continue;
    for (const e of p.log) {
      if (e.week >= beforeWeek) continue;
      const d = (allowed[e.opp] ||= {});
      d[p.pos] = (d[p.pos] || 0) + scoreGame(e, p.pos, sc);
    }
  }
  const played = {};
  for (const g of games) {
    if (g.type !== "REG" || g.home_score === null || g.week >= beforeWeek) continue;
    played[g.home] = (played[g.home] || 0) + 1;
    played[g.away] = (played[g.away] || 0) + 1;
  }
  const out = {};
  for (const team of Object.keys(played)) {
    out[team] = {};
    for (const pos of ["QB", "RB", "WR", "TE", "K"]) out[team][pos] = { ppg: Math.round((allowed[team]?.[pos] || 0) / played[team] * 10) / 10 };
  }
  for (const pos of ["QB", "RB", "WR", "TE", "K"]) {
    Object.keys(out).sort((a, b) => out[b][pos].ppg - out[a][pos].ppg).forEach((t, i) => { out[t][pos].rank = i + 1; });
  }
  return out;
}
function matchupClass(rank) { return rank <= 8 ? "great" : rank <= 16 ? "good" : rank <= 24 ? "meh" : "tough"; }
function matchupLabel(rank) { return { great: "Great matchup", good: "Good matchup", meh: "Below average", tough: "Tough matchup" }[matchupClass(rank)]; }
function ordinal(n) { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

// NFL Next Gen Stats: [key, label, unit, better ("high" / "low" / null = style, not good or bad), what it means].
const NGS = {
  passing: ["Passing", [
    ["cpoe", "Completion % over expected", "%", "high", "How much more often he completes passes than expected, given how hard each throw was"],
    ["xcmp", "Expected completion %", "%", null, "How completable his throws are on average; lower means harder throws"],
    ["aggr", "Aggressiveness", "%", null, "Share of throws into tight windows (a defender within a yard)"],
    ["ttt", "Time to throw", "s", null, "Average time from the snap to the throw"],
    ["iay", "Intended air yards", " yds", null, "How far downfield his throws travel on average"],
    ["cay", "Completed air yards", " yds", "high", "How far downfield his completions travel on average"],
    ["sticks", "Air yards to the sticks", " yds", null, "How far past (+) or short (−) of the first-down marker he throws on average"],
  ]],
  receiving: ["Receiving", [
    ["sep", "Separation", " yds", "high", "Distance from the nearest defender when the ball arrives. Short targets (screens, flats) are naturally more open"],
    ["sep_oe", "Separation vs. depth", " yds", "high", "How much more open he is than receivers targeted at the same depth (separation with the short-target boost taken out)"],
    ["yacoe", "YAC over expected", " yds", "high", "Yards after the catch beyond what's expected, per catch"],
    ["ays", "Share of team air yards", "%", "high", "His share of all the air yards his team throws at"],
    ["catch", "Catch rate", "%", "high", "Catches per target"],
    ["iay", "Average target depth", " yds", null, "How far downfield he's targeted on average"],
    ["cush", "Cushion", " yds", null, "Distance from the nearest defender at the snap"],
  ]],
  rushing: ["Rushing", [
    ["ryoe", "Rush yds over expected / carry", " yds", "high", "Yards per carry beyond what the blocking and defenders' positions suggest"],
    ["ryoe_tot", "Rush yds over expected", " yds", "high", "Season total of the above"],
    ["roe_pct", "Runs beating expected", "%", "high", "Share of his carries that gained more than expected"],
    ["eff", "Efficiency", "", "low", "Distance run per yard gained; lower means more north-south running"],
    ["box8", "Stacked boxes", "%", null, "Share of his carries against 8+ defenders in the box"],
    ["ttl", "Time to line of scrimmage", "s", null, "Average time from the handoff to crossing the line"],
  ]],
};
const NGS_ORDER = { QB: ["passing", "rushing"], RB: ["rushing", "receiving"], WR: ["receiving"], TE: ["receiving"] };
// Separation depends a lot on depth (a screen is open by design), so add separation compared with what's typical
// for a target that deep: a straight-line fit of separation on target depth across every qualifying pass catcher.
function ngsDerive(players) {
  const rec = players.map(p => p.ngs?.receiving).filter(r => r && r.sep !== undefined && r.iay !== undefined);
  if (rec.length < 10 || rec[0].sep_oe !== undefined) return;
  const mx = rec.reduce((s, r) => s + r.iay, 0) / rec.length, my = rec.reduce((s, r) => s + r.sep, 0) / rec.length;
  const slope = rec.reduce((s, r) => s + (r.iay - mx) * (r.sep - my), 0) / rec.reduce((s, r) => s + (r.iay - mx) ** 2, 0);
  for (const r of rec) r.sep_oe = Math.round((r.sep - (my + slope * (r.iay - mx))) * 100) / 100;
}
// The volume behind each kind (per game, from the game log), and what counts as a "regular" for the leaderboard filter.
const NGS_VOL = { passing: ["att", "att/g", 20], receiving: ["tgt", "tgt/g", { WR: 5, TE: 4, RB: 2 }], rushing: ["car", "car/g", { RB: 10, QB: 3 }] };
function ngsVolume(p, kind) {
  const games = p.log.length;
  return games ? p.log.reduce((s, g) => s + (g[NGS_VOL[kind][0]] || 0), 0) / games : 0;
}
function ngsRegularMin(kind, pos) { const m = NGS_VOL[kind][2]; return typeof m === "number" ? m : m[pos]; }
// Which positions each NGS kind is listed for on the leaderboard (the first is the default).
const NGS_POS = { passing: ["QB"], receiving: ["WR", "TE", "RB"], rushing: ["RB", "QB"] };
// Rank v among vals (1 = best; for style stats 1 = most). Ties share a rank.
function ngsRank(vals, v, better) { return vals.filter(x => (better === "low" ? x < v : x > v)).length + 1; }
// How an NGS value is shown: rush % as a whole percent, season RYOE whole yards, the rest to one decimal.
function ngsShow(k, v) {
  if (v === null || v === undefined) return "—";
  const n = (k === "roe_pct" ? Math.round(v * 100) : k === "ryoe_tot" ? Math.round(v) : Math.round(v * 10) / 10) || 0;
  return `${n > 0 && ["sticks", "ryoe", "ryoe_tot", "yacoe", "cpoe", "sep_oe"].includes(k) ? "+" : ""}${fmt(n)}`;
}
function ngsUrl(kind, key, pos, hl) {
  return `ngs.html?stat=${kind}.${key}${pos ? `&pos=${pos}` : ""}${hl ? `&hl=${encodeURIComponent(hl)}` : ""}`;
}

function roofLabel(roof) {
  return { dome: "Indoors (dome)", closed: "Retractable roof (closed)", open: "Retractable roof (open)", outdoors: "Outdoors" }[roof] || "—";
}
// Live forecast for an upcoming outdoor game from Open-Meteo (free, no key). Resolves to null when unavailable.
async function fetchForecast(g) {
  if (!g.coords || ["dome", "closed"].includes(g.roof) || g.home_score !== null) return null;
  const days = (new Date(`${g.date}T12:00:00`) - new Date()) / 864e5;
  if (days < -1 || days > 15) return null;
  const [lat, lon] = g.coords;
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    `&hourly=temperature_2m,precipitation_probability,wind_speed_10m&temperature_unit=fahrenheit&wind_speed_unit=mph` +
    `&timezone=America%2FNew_York&start_date=${g.date}&end_date=${g.date}`;
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    const h = (await r.json()).hourly;
    const i = Math.min(23, Number((g.time || "13:00").split(":")[0]));
    return { temp: Math.round(h.temperature_2m[i]), rain: h.precipitation_probability?.[i], wind: Math.round(h.wind_speed_10m[i]) };
  } catch (e) {
    return null;
  }
}

// ---------- Projections ----------
// Sleeper's weekly projections, added to the data by build_data.py when Sleeper could be reached.

function makeProjector(players, games, sc, meta) {
  function get(p, week) {
    const s = p.proj?.sleeper?.[week];
    if (!s || !weekGame(games, p.team, week)) return null;  // no projection on a bye
    if (p.pos === "K" || p.pos === "DST") return s.ppr ?? s.std;
    const base = { ppr: s.ppr, half: s.half, std: s.std }[sc.fmt];
    return Math.round((base + (sc.passTd - 4) * (s.ptd || 0)) * 10) / 10;
  }

  // Sleeper's average miss (in fantasy points) on completed weeks, fantasy-relevant skill players only.
  function accuracy() {
    const errs = [], weeks = [];
    for (let w = 1; w <= (meta.last_week || 0); w++) {
      let any = false;
      for (const p of players) {
        if (!["QB", "RB", "WR", "TE"].includes(p.pos)) continue;
        const e = p.log.find(x => x.week === w), proj = get(p, w);
        if (!e || proj === null || proj < 5) continue;
        errs.push(Math.abs(proj - scoreGame(e, p.pos, sc)));
        any = true;
      }
      if (any) weeks.push(w);
    }
    return { mae: errs.length ? Math.round(errs.reduce((a, b) => a + b, 0) / errs.length * 10) / 10 : null, weeks };
  }

  return { get, accuracy, hasSleeper: !!meta.projections?.sleeper };
}

// ---------- Team splits by position ----------
// What each defense gives up and each offense produces, per position, per game, ranked across the league.

const DIVISIONS = {
  "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
  "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LAC", "LV"],
  "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
  "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LA", "SF", "SEA"],
};
const POS_PLURAL = { QB: "QBs", RB: "RBs", WR: "WRs", TE: "TEs" };

// [key, label, options]. rate: computed from totals (yards per catch/carry), not per game.
// bad: more is bad for the offense (INTs, sacks), so for a defense a high rank is a tough matchup.
const SPLIT_STATS = {
  QB: [["fpts", "Fantasy pts"], ["pass_yds", "Pass yds"], ["pass_td", "Pass TD"], ["rush_yds", "Rush yds"],
       ["int", "INT", { bad: true }], ["sk", "Sacks", { bad: true }]],
  RB: [["fpts", "Fantasy pts"], ["car", "Carries"], ["rush_yds", "Rush yds"], ["ypc", "Yds/carry", { rate: true }], ["rush_td", "Rush TD"],
       ["tgt", "Targets"], ["rec", "Catches"], ["rec_yds", "Rec yds"], ["rec_td", "Rec TD"]],
  WR: [["fpts", "Fantasy pts"], ["tgt", "Targets"], ["rec", "Catches"], ["rec_yds", "Rec yds"], ["ypr", "Yds/catch", { rate: true }], ["rec_td", "Rec TD"]],
};
SPLIT_STATS.TE = SPLIT_STATS.WR;

// splits.def[team][pos][stat] = { v, rank } (rank 1 = most allowed); splits.off likewise (1 = most produced).
// Games are counted per team from the stats themselves, so a final whose stats aren't published yet doesn't count.
function positionSplits(players, sc) {
  const tot = { def: {}, off: {} }, gameWeeks = { def: {}, off: {} };
  const keys = ["pass_yds", "pass_td", "rush_yds", "int", "sk", "car", "rush_td", "tgt", "rec", "rec_yds", "rec_td"];
  for (const p of players) {
    if (!POS_PLURAL[p.pos]) continue;
    for (const e of p.log) {
      for (const [side, team] of [["def", e.opp], ["off", e.team]]) {
        const t = ((tot[side][team] ||= {})[p.pos] ||= { fpts: 0 });
        for (const k of keys) t[k] = (t[k] || 0) + (e[k] || 0);
        t.fpts += scoreGame(e, p.pos, sc);
        (gameWeeks[side][team] ||= new Set()).add(e.week);
      }
    }
  }
  const out = { def: {}, off: {} };
  for (const side of ["def", "off"]) {
    for (const [team, byPos] of Object.entries(tot[side])) {
      const g = gameWeeks[side][team].size;
      out[side][team] = { games: g };
      for (const [pos, t] of Object.entries(byPos)) {
        out[side][team][pos] = {};
        for (const [k, , o] of SPLIT_STATS[pos]) {
          const rate = k === "ypc" || k === "ypr";
          const v = k === "ypc" ? (t.car ? t.rush_yds / t.car : null) : k === "ypr" ? (t.rec ? t.rec_yds / t.rec : null) : t[k] / g;
          const round = x => (x === null ? null : Math.round(x * 10) / 10);
          // v = per game; tot = season total (rates like yards per catch are the same either way).
          out[side][team][pos][k] = { v: round(v), tot: round(rate ? v : t[k]) };
        }
      }
    }
    // Rank every stat across teams (1 = highest); ties share the better rank.
    for (const pos of Object.keys(SPLIT_STATS)) {
      for (const [k] of SPLIT_STATS[pos]) {
        const vals = Object.values(out[side]).map(t => t[pos]?.[k]?.v).filter(v => v !== null && v !== undefined);
        for (const t of Object.values(out[side])) {
          const c = t[pos]?.[k];
          if (c && c.v !== null) { c.rank = vals.filter(x => x > c.v).length + 1; c.of = vals.length; }
        }
        const tots = Object.values(out[side]).map(t => t[pos]?.[k]?.tot).filter(v => v !== null && v !== undefined);
        for (const t of Object.values(out[side])) {
          const c = t[pos]?.[k];
          if (c && c.tot !== null) c.rankTot = tots.filter(x => x > c.tot).length + 1;
        }
      }
    }
  }
  return out;
}

const SPLIT_NAMES = {
  fpts: "fantasy points", pass_yds: "passing yards", pass_td: "passing TDs", rush_yds: "rushing yards", int: "INTs", sk: "sacks",
  car: "carries", ypc: "yards per carry", rush_td: "rushing TDs", tgt: "targets", rec: "catches", rec_yds: "receiving yards",
  ypr: "yards per catch", rec_td: "receiving TDs",
};

// For a defense: is this stat a soft spot (good for the offense) or a tough one? Flips for INTs and sacks.
function splitMatchup(pos, key, rank, of = 32) {
  const bad = SPLIT_STATS[pos].find(s => s[0] === key)?.[2]?.bad;
  const r = bad ? of + 1 - rank : rank;  // r = 1 means the best matchup for the offense
  return matchupClass(Math.round(r / of * 32));
}

// "Gives up the 2nd-most catches to RBs (6.8/g)" / "Forces the 3rd-most INTs from QBs (1.4/g)".
function splitPhrase(pos, key, cell) {
  const [, label, o = {}] = SPLIT_STATS[pos].find(st => st[0] === key);
  const most = cell.rank <= cell.of / 2, k = most ? cell.rank : cell.of + 1 - cell.rank;
  const word = o.rate ? (most ? "highest" : "lowest") : (most ? "most" : "fewest");
  const what = SPLIT_NAMES[key] || label.toLowerCase();
  const verb = key === "int" ? "Forces" : key === "sk" ? "Gets" : "Gives up";
  const prep = key === "int" ? "from" : key === "sk" ? "against" : "to";
  return `${verb} the ${k === 1 ? "" : `${ordinal(k)}-`}${word} ${what} ${prep} ${POS_PLURAL[pos]} <span class="muted">(${fmt(cell.v)}${o.rate ? "" : "/g"})</span>`;
}

// Where an offense can attack a defense: the defense's soft spots (bottom 5 per game, i.e. gives up among the most)
// and tough spots (top 5), as sentences, plus the offense's top players at the soft positions.
const PLAN_DEPTH = { QB: 1, RB: 2, WR: 3, TE: 1 };
function attackPlan(offTeam, defTeam, splits, { players, teams, sc, meta }) {
  const d = splits.def[defTeam];
  if (!d) return `<p class="muted">Not enough games yet.</p>`;
  const spots = [];
  for (const pos of Object.keys(SPLIT_STATS)) {
    for (const [k, , o = {}] of SPLIT_STATS[pos]) {
      const c = d[pos]?.[k];
      if (!c || c.v === null) continue;
      spots.push({ pos, k, c, r: o.bad ? c.of + 1 - c.rank : c.rank });  // r = 1 is best for the offense
    }
  }
  const soft = spots.filter(x => x.r <= 5).sort((a, b) => a.r - b.r).slice(0, 6);
  const tough = spots.filter(x => x.r >= 28).sort((a, b) => b.r - a.r).slice(0, 4);
  const helped = [...new Set(soft.map(x => x.pos))].flatMap(pos =>
    rankList(players.filter(p => p.team === offTeam && p.pos === pos), sc, meta).filter(r => r.s.g >= 1).slice(0, PLAN_DEPTH[pos]).map(r => r.p));
  const li = x => `<li>${posBadge(x.pos)} ${splitPhrase(x.pos, x.k, x.c)}</li>`;
  return `
    <h4 class="plan-head ok">Soft spots in the ${esc(teamName(defTeam, teams, false))} defense</h4>
    ${soft.length ? `<ul class="plan">${soft.map(li).join("")}</ul>` : `<p class="muted small">No clear weak spots (nothing in the bottom 5).</p>`}
    <h4 class="plan-head bad">Tough spots</h4>
    ${tough.length ? `<ul class="plan">${tough.map(li).join("")}</ul>` : `<p class="muted small">Nothing in the top 5.</p>`}
    ${helped.length ? `<h4 class="plan-head">Who it helps</h4><div class="helped">${helped.map(p => `<a class="helped-chip" href="${playerUrl(p)}">${posBadge(p.pos)} ${esc(p.short)}</a>`).join("")}</div>` : ""}`;
}
