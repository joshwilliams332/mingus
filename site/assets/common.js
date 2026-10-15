// Shared by every Mingus page: header/footer, data loading and small formatting helpers.

const NAV = [
  { href: "index.html", label: "Home" },
  { href: "players.html", label: "Players" },
  { href: "games.html", label: "Games" },
];
const POSITIONS = ["QB", "RB", "WR", "TE"];

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
          <a class="brand" href="index.html" aria-label="Mingus home">
            <span class="brand-mark" aria-hidden="true">M</span>
            <span class="brand-name">Mingus</span>
          </a>
          <nav class="nav" aria-label="Main">
            ${NAV.map(n => `<a href="${n.href}" ${n.href === here ? 'aria-current="page"' : ""}>${n.label}</a>`).join("")}
          </nav>
          <span class="header-week">${esc(week)}</span>
        </div>
      </header>`);
    document.body.insertAdjacentHTML("beforeend", `
      <footer class="site-footer">
        Data from <a href="https://github.com/nflverse/nflverse-data">nflverse</a>${meta ? ` · updated ${esc(fmtDateTime(meta.built_at))}` : ""}
        <br>Mingus is a fan site and isn't affiliated with the NFL.
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
        If you opened this file directly, serve the folder instead: <code>python3 -m http.server -d site</code></div>`;
    }
  },
};

// ---------- Helpers ----------

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
  return p.headshot
    ? `<img class="headshot ${size}" src="${esc(p.headshot)}" alt="" loading="lazy"
         onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'headshot ${size} placeholder',textContent:${esc(JSON.stringify(p.name[0]))}}))">`
    : `<span class="headshot ${size} placeholder" aria-hidden="true">${esc(p.name[0])}</span>`;
}
function playerUrl(p) {
  return `player.html?id=${encodeURIComponent(p.id)}`;
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
function spreadTag(n) {
  const cls = n < 0 ? "fav" : n > 0 ? "dog" : "";
  return `<span class="spread ${cls}">${fmtSpread(n)}</span>`;
}

// Game card used on the home and games pages. Shows the score once a game is final.
function gameCard(g) {
  const final = g.home_score !== null;
  const row = (team, isHome) => {
    const tg = teamGame(g, team);
    const won = final && tg.score[0] > tg.score[1];
    return `<div class="game-row ${won ? "winner" : ""}">
      <span class="team">${esc(team)}${isHome ? "<small>home</small>" : ""}</span>
      ${final
        ? `<span></span><span class="score">${tg.score[0]}</span>`
        : `<span class="num">${spreadTag(tg.spread)}</span><span class="num">${fmt(tg.implied)}</span>`}
    </div>`;
  };
  return `<div class="game-card">
    <div class="when">${esc(fmtKickoff(g))}</div>
    ${final ? "" : `<div class="game-cols"><span></span><span>Spread</span><span>Implied</span></div>`}
    ${row(g.away, false)}
    ${row(g.home, true)}
    <div class="game-foot">
      <span>${final ? "Final" : `O/U ${fmt(g.total)}`}</span>
      <span>${esc(g.stadium || "")}</span>
    </div>
  </div>`;
}
