"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TIER_ORDER = ["S", "A", "B", "C", "?"];
const TREND = {
  up: ['<span class="tag trend-up">▲ Sube</span>'],
  down: ['<span class="tag trend-down">▼ Baja</span>'],
  new: ['<span class="tag trend-new">● Nueva</span>'],
  stable: [""],
};
const LEVELS = {
  1: ["unique"],
  2: ["bronze", "gold"],
  3: ["bronze", "silver", "gold"],
  4: ["bronze", "silver", "gold", "prism"],
  5: ["bronze", "silver", "gold", "gold", "prism"],
};
const MAX_BOARD = 10;
const MAX_INV = 12;

const state = { set: null, comps: null, champ: {}, trait: {}, item: {}, emblemTrait: {}, style: "", query: "", traitSel: new Set(), board: [], boardItems: {}, inv: [], recipe: {}, poolTrait: "" };

/* ---------- Carga ---------- */

async function load() {
  const [set, comps] = await Promise.all([
    fetch("data/set.json").then((r) => r.json()),
    fetch("data/comps.json").then((r) => r.json()),
  ]);
  state.set = set;
  state.comps = comps;
  set.champions.forEach((c) => (state.champ[c.id] = c));
  set.traits.forEach((t) => (state.trait[t.id] = t));
  set.items.forEach((i) => {
    state.item[i.id] = i;
    const m = i.name.match(/^Emblema de (.+)$/i);
    if (m) {
      const t = set.traits.find((t) => t.name.toLowerCase() === m[1].toLowerCase());
      if (t) state.emblemTrait[i.id] = t.id;
    }
  });
  set.items.forEach((i) => {
    if (i.components.length === 2) state.recipe[[...i.components].sort().join("+")] = i.id;
  });
  try {
    state.board = JSON.parse(localStorage.getItem("tft-board") || "[]").filter((id) => state.champ[id]);
    const saved = JSON.parse(localStorage.getItem("tft-board-items") || "{}");
    state.board.forEach((id) => { if (Array.isArray(saved[id])) state.boardItems[id] = saved[id].filter((i) => state.item[i]).slice(0, 3); });
    state.inv = JSON.parse(localStorage.getItem("tft-inv") || "[]").filter((i) => state.item[i]).slice(0, MAX_INV);
  } catch { state.board = []; state.boardItems = {}; state.inv = []; }

  $("#patch").textContent = `Set ${set.set} · Parche ${comps.patch}`;
  $("#source").textContent = `${comps.source} Última actualización: ${comps.updated}.`;
  if (comps.newPatch) {
    $("#patch-banner").textContent = comps.stale
      ? `Parche nuevo (${comps.patch}): aún no hay suficientes partidas, así que se muestran las estadísticas del parche anterior.`
      : `Parche nuevo (${comps.patch}): todavía hay pocas partidas, así que las estadísticas pueden cambiar bastante en los próximos días.`;
    $("#patch-banner").hidden = false;
  }
  comps.comps.forEach((c) => {
    c.activeTraits = computeTraits(c.units, c.items).filter((x) => x.idx >= 0 && x.level !== "unique");
  });
  renderTraitFilter();
  renderComps();
  initBuilder();
}

/* ---------- Utilidades de render ---------- */

function champHTML(id, { items = [], carry = false, name = false, tag = "div" } = {}) {
  const c = state.champ[id];
  if (!c) return "";
  const its = items.map((i) => state.item[i]).filter(Boolean)
    .map((i) => `<img src="${i.img}" alt="${esc(i.name)}" title="${esc(i.name)}" loading="lazy">`).join("");
  return `<${tag} class="champ c${c.cost}${carry ? " carry" : ""}" data-id="${c.id}" title="${esc(c.name)}">
    <img class="pic" src="${c.img}" alt="${esc(c.name)}" loading="lazy">
    ${its ? `<div class="its">${its}</div>` : ""}
    ${name ? `<div class="nm">${esc(c.name)}</div>` : ""}
  </${tag}>`;
}

/** Cuenta rasgos de un tablero (unidades únicas + emblemas) y devuelve los rasgos ordenados. */
function computeTraits(units, items = {}) {
  const count = {};
  new Set(units).forEach((id) => {
    const c = state.champ[id];
    if (!c) return;
    const own = new Set(c.traits);
    c.traits.forEach((t) => (count[t] = (count[t] || 0) + 1));
    (items[id] || []).forEach((it) => {
      const t = state.emblemTrait[it];
      if (t && !own.has(t)) { own.add(t); count[t] = (count[t] || 0) + 1; }
    });
  });
  return Object.entries(count).map(([id, n]) => {
    const t = state.trait[id];
    if (!t) return null;
    const bps = t.breakpoints;
    let idx = -1;
    bps.forEach((b, i) => { if (n >= b) idx = i; });
    const levels = bps.length === 1 && bps[0] > 1 ? ["gold"] : LEVELS[Math.min(bps.length, 5)];
    return { t, n, idx, level: idx >= 0 ? levels[Math.min(idx, levels.length - 1)] : "off" };
  }).filter(Boolean).sort((a, b) => {
    const rank = { prism: 5, gold: 4, unique: 3, silver: 2, bronze: 1, off: 0 };
    return rank[b.level] - rank[a.level] || b.n - a.n;
  });
}

function traitHTML({ t, n, idx, level }) {
  const bps = t.breakpoints.length > 1
    ? `<span class="bp">${t.breakpoints.map((b, i) => (i === idx ? `<span class="on">${b}</span>` : b)).join(" / ")}</span>`
    : "";
  return `<span class="trait ${level}" title="${esc(t.desc)}">
    <span class="hex"><img src="${t.img}" alt=""></span>
    <span class="n">${n}</span> ${esc(t.name)} ${bps}
  </span>`;
}

/* ---------- Transición early / mid ---------- */

const STAGES = [
  { key: "early", title: "Early game", sub: "Fase 2 · nivel 4–5", size: 5, maxCost: 2 },
  { key: "mid", title: "Mid game", sub: "Fase 3–4 · nivel 6–7", size: 7, maxCost: 3 },
];

/** Puntuación de un tablero: rasgos activos (más alto el nivel, mejor). */
function boardValue(units) {
  return computeTraits(units).reduce((s, x) => s + (x.idx >= 0 && x.level !== "unique" ? (x.idx + 1) * 2 : 0), 0);
}

/**
 * Propone un tablero intermedio que lleve a la composición final:
 * mantiene las unidades baratas del tablero final y rellena con las que
 * más rasgos activan o comparten rasgos con la composición final.
 */
function suggestBoard(comp, { size, maxCost }, prefer = []) {
  const finalTraits = new Set(comp.units.flatMap((u) => state.champ[u]?.traits || []));
  const allowed = (c) => c.cost <= maxCost || (comp.units.includes(c.id) && c.cost <= maxCost + 1 && comp.carries.includes(c.id));
  const bonus = (c) =>
    (comp.carries.includes(c.id) ? 4 : 0) +
    (comp.units.includes(c.id) ? 3 : 0) +
    (prefer.includes(c.id) ? 2.5 : 0) +
    c.traits.filter((t) => finalTraits.has(t)).length * 0.75 -
    c.cost * 0.15;

  const board = [];
  const pool = state.set.champions.filter((c) => allowed(c) && !/\(/.test(c.name));
  while (board.length < size) {
    const base = boardValue(board);
    let best = null, bestScore = -Infinity;
    for (const c of pool) {
      if (board.includes(c.id)) continue;
      const score = boardValue([...board, c.id]) - base + bonus(c);
      if (score > bestScore) { best = c; bestScore = score; }
    }
    if (!best) break;
    board.push(best.id);
  }
  return board.sort((a, b) => state.champ[a].cost - state.champ[b].cost);
}

/** Componentes más necesarios para los objetos de los carries. */
function priorityComponents(comp) {
  const count = {};
  comp.carries.forEach((u) => (comp.items[u] || []).forEach((it) => {
    (state.item[it]?.components || []).forEach((c) => (count[c] = (count[c] || 0) + 1));
  }));
  return Object.entries(count).filter(([id]) => state.item[id]).sort((a, b) => b[1] - a[1]).slice(0, 4);
}

function transitionHTML(c) {
  // El mid se calcula primero para que el early lleve hacia él
  const boards = {};
  [...STAGES].reverse().forEach((st, i, arr) => {
    boards[st.key] = suggestBoard(c, st, i ? boards[arr[i - 1].key] : []);
  });
  const stages = STAGES.map((st) => {
    const units = boards[st.key];
    const traits = computeTraits(units).filter((x) => x.idx >= 0 && x.level !== "unique");
    const keep = units.filter((u) => c.units.includes(u)).length;
    return `<div class="stage">
      <div class="stage-head"><b>${st.title}</b><small>${st.sub}</small><span class="tag">${keep}/${units.length} se quedan</span></div>
      <div class="units">${units.map((u) => champHTML(u, { carry: c.carries.includes(u), name: true })
        .replace('class="champ', `class="champ${c.units.includes(u) ? " keep" : ""}`)).join("")}</div>
      <div class="traits" style="margin-top:8px">${traits.map(traitHTML).join("")}</div>
    </div>`;
  }).join("");
  const comps = priorityComponents(c);
  const compHTML = comps.length ? `<div class="stage">
      <div class="stage-head"><b>Componentes prioritarios</b><small>Guárdalos para los carries</small></div>
      <div class="item-list">${comps.map(([id, n]) => `<span class="item-chip"><img src="${state.item[id].img}" alt="">${esc(state.item[id].name)} ×${n}</span>`).join("")}</div>
    </div>` : "";
  return `${stages}${compHTML}
    <p class="source">Sugerencia automática según los rasgos del set. Las unidades con borde punteado no están en el tablero final: véndelas al hacer la transición.</p>`;
}

/** Todos los componentes del jugador: los sueltos y los que forman los objetos ya puestos. */
function myComponents() {
  const list = [...state.inv];
  Object.values(state.boardItems).flat().forEach((id) => {
    const it = state.item[id];
    if (!it) return;
    if (it.kind === "completed") list.push(...it.components);
    else if (it.kind === "component") list.push(id);
  });
  return list;
}

/** Objetos recomendados de la composición que se pueden fabricar con los componentes dados. */
function buildableItems(comp, components) {
  const left = {};
  components.forEach((c) => (left[c] = (left[c] || 0) + 1));
  const owners = [...comp.carries, ...Object.keys(comp.items).filter((u) => !comp.carries.includes(u))];
  const out = [];
  owners.forEach((u) => (comp.items[u] || []).forEach((id) => {
    const parts = state.item[id]?.components || [];
    if (parts.length !== 2) return;
    const need = {};
    parts.forEach((p) => (need[p] = (need[p] || 0) + 1));
    if (Object.entries(need).every(([p, n]) => (left[p] || 0) >= n)) {
      parts.forEach((p) => left[p]--);
      out.push({ item: id, champ: u });
    }
  }));
  return out;
}

/** Componentes de la composición que encajan con los tuyos (aunque no completen un objeto). */
function matchingComponents(comp, components) {
  const need = {};
  Object.values(comp.items).flat().forEach((id) => (state.item[id]?.components || []).forEach((p) => (need[p] = (need[p] || 0) + 1)));
  let n = 0;
  components.forEach((c) => { if (need[c] > 0) { need[c]--; n++; } });
  return n;
}

/** Composiciones que mejor encajan con tus campeones y componentes. */
function similarComps(units, components = []) {
  if (!units.length && !components.length) return [];
  const myTraits = new Set(units.flatMap((u) => state.champ[u]?.traits || []));
  return state.comps.comps.map((c) => {
    const shared = units.filter((u) => c.units.includes(u)).length;
    const compTraits = new Set(c.units.flatMap((u) => state.champ[u]?.traits || []));
    const traitOverlap = [...myTraits].filter((t) => compTraits.has(t)).length;
    const build = buildableItems(c, components);
    const matched = matchingComponents(c, components);
    const tierBonus = { S: 1, A: 0.5 }[c.tier] || 0;
    const score = shared * 3 + traitOverlap + build.length * 3 + matched + tierBonus;
    return { c, shared, build, matched, score };
  }).filter((x) => x.shared || x.matched || x.build.length || x.score > 1.5)
    .sort((a, b) => b.score - a.score).slice(0, 3);
}

/* ---------- Aumentos ---------- */

/** Aumentos del set ligados a los rasgos activos (o campeones) de la composición. */
function compAugments(c) {
  const active = {};
  computeTraits(c.units, c.items).filter((x) => x.idx >= 0).forEach((x) => (active[x.t.id] = x.n));
  return (state.set.augments || []).map((a) => {
    const carryTraits = new Set(c.carries.flatMap((u) => state.champ[u]?.traits || []));
    const t = a.traits.find((id) => active[id] && (active[id] >= 2 || carryTraits.has(id)));
    if (!t) return null;
    // Variantes ligadas a un campeón concreto (p. ej. "Bestia interior (Sivir)")
    if (a.name.includes("(") && !a.champs.some((u) => u !== "da_vi18" && c.units.includes(u))) return null;
    return { a, trait: state.trait[t], n: active[t] };
  }).filter(Boolean).sort((x, y) => y.n - x.n || x.a.plus - y.a.plus);
}

function augmentsHTML(c) {
  const list = compAugments(c);
  if (!list.length) return `<p class="source">Esta composición no tiene aumentos propios del set ligados a sus rasgos.</p>`;
  return list.map(({ a, trait }) => `<div class="aug">
      <img src="${a.img}" alt="" loading="lazy">
      <div><b>${esc(a.name)}</b> <span class="tag">${esc(trait.name)}</span><p>${esc(a.desc)}</p></div>
    </div>`).join("") +
    `<p class="source">Aumentos del Set 18 relacionados con los rasgos de esta composición. La API de Riot no publica datos de aumentos, así que no hay estadísticas de cuál rinde más.</p>`;
}

/* ---------- Composiciones ---------- */

/** Rasgos que aparecen activos en alguna composición, con cuántas los usan. */
function renderTraitFilter() {
  const count = {};
  state.comps.comps.forEach((c) => c.activeTraits.forEach(({ t }) => (count[t.id] = (count[t.id] || 0) + 1)));
  const traits = Object.keys(count).map((id) => state.trait[id])
    .sort((a, b) => count[b.id] - count[a.id] || a.name.localeCompare(b.name, "es"));
  $("#comp-traits").innerHTML = traits.map((t) => `<button class="tf${state.traitSel.has(t.id) ? " active" : ""}" data-trait="${t.id}" title="${esc(t.desc)}">
      <span class="hex"><img src="${t.img}" alt=""></span>${esc(t.name)}<small>${count[t.id]}</small>
    </button>`).join("") +
    (state.traitSel.size ? `<button class="tf clear" data-trait="">✕ Quitar filtro</button>` : "");
}

function renderComps() {
  const q = state.query.trim().toLowerCase();
  const list = state.comps.comps.filter((c) => {
    if (state.style && c.style !== state.style) return false;
    const ids = new Set(c.activeTraits.map(({ t }) => t.id));
    if ([...state.traitSel].some((t) => !ids.has(t))) return false;
    if (!q) return true;
    if (c.name.toLowerCase().includes(q)) return true;
    if (c.activeTraits.some(({ t }) => t.name.toLowerCase().includes(q))) return true;
    return c.units.some((u) => state.champ[u]?.name.toLowerCase().includes(q));
  });

  const html = TIER_ORDER.map((tier) => {
    const comps = list.filter((c) => c.tier === tier);
    if (!comps.length) return "";
    const label = tier === "?" ? `<div class="tier-label q">Orientativas</div>` : `<div class="tier-label ${tier}">${tier}</div>`;
    return `<div class="tier">${label}<div class="tier-list">${comps.map(cardHTML).join("")}</div></div>`;
  }).join("");

  $("#tiers").innerHTML = html || `<p class="source">No hay composiciones que coincidan.</p>`;
}

function cardHTML(c) {
  const sorted = [...c.units].sort((a, b) => (state.champ[a]?.cost || 0) - (state.champ[b]?.cost || 0));
  const stats = c.stats
    ? `<div class="stats"><span>Puesto medio <b>${c.stats.avg.toFixed(2)}</b></span><span>Top 4 <b>${c.stats.top4}%</b></span><span>Victoria <b>${c.stats.win}%</b></span>${c.stats.games ? `<span><b>${c.stats.games}</b> partidas${c.stats.games < 40 ? " ⚠" : ""}</span>` : ""}</div>`
    : `<div class="stats"><span>Sin estadísticas</span></div>`;
  return `<button class="card" data-comp="${c.id}">
    <div class="card-head">
      <span class="card-name">${esc(c.name)}</span>
      <span class="tag">${esc(c.style)}</span>
      ${TREND[c.trend || "stable"]}
    </div>
    ${stats}
    <div class="units">${sorted.map((u) => champHTML(u, { items: c.items[u] || [], carry: c.carries.includes(u) })).join("")}</div>
    <div class="mini-traits">${c.activeTraits.map(({ t, n, level }) =>
      `<span class="trait ${level}${state.traitSel.has(t.id) ? " sel" : ""}" title="${esc(t.name)}"><span class="hex"><img src="${t.img}" alt=""></span><span class="n">${n}</span></span>`).join("")}</div>
  </button>`;
}

function openComp(id) {
  const c = state.comps.comps.find((x) => x.id === id);
  if (!c) return;
  const traits = computeTraits(c.units, c.items).filter((x) => x.idx >= 0);
  const stats = c.stats ? `<div class="statgrid">
      <div class="stat"><div class="v">${c.stats.avg.toFixed(2)}</div><div class="l">Puesto medio</div></div>
      <div class="stat"><div class="v">${c.stats.top4}%</div><div class="l">Top 4</div></div>
      <div class="stat"><div class="v">${c.stats.win}%</div><div class="l">Victorias</div></div>
      <div class="stat"><div class="v">${c.stats.pick}</div><div class="l">Frecuencia por partida</div></div>
      ${c.stats.games ? `<div class="stat"><div class="v">${c.stats.games}</div><div class="l">Tableros analizados</div></div>` : ""}
    </div>${c.stats.games && c.stats.games < 40 ? `<p class="warn">⚠ Pocas partidas: las estadísticas pueden cambiar bastante.</p>` : ""}` : `<p class="warn">⚠ Composición orientativa: sin estadísticas y con tablero aproximado.</p>`;

  const itemRows = Object.entries(c.items).map(([u, its]) => {
    const ch = state.champ[u];
    if (!ch) return "";
    return `<div class="carry-row">
      <img class="pic" src="${ch.img}" alt="" style="border-color:var(--c${ch.cost})">
      <div class="info"><b>${esc(ch.name)}</b> ${c.carries.includes(u) ? '<span class="tag" style="color:var(--accent)">Carry</span>' : ""}<br>
        <small>${ch.traits.map((t) => esc(state.trait[t]?.name || "")).join(" · ")}</small>
        <div class="item-list" style="margin-top:6px">${its.map((i) => state.item[i]).filter(Boolean)
          .map((i) => `<span class="item-chip"><img src="${i.img}" alt="">${esc(i.name)}</span>`).join("")}</div>
      </div>
    </div>`;
  }).join("");

  delete $("#sheet-body").dataset.champ;
  $("#sheet-body").innerHTML = `
    <h2>${esc(c.name)}</h2>
    <div class="card-head"><span class="tag">Tier ${c.tier === "?" ? "—" : c.tier}</span><span class="tag">${esc(c.style)}</span>${TREND[c.trend || "stable"]}</div>
    ${stats}
    <h3>Tablero final</h3>
    <div class="units">${c.units.map((u) => champHTML(u, { carry: c.carries.includes(u), name: true })).join("")}</div>
    <h3>Rasgos activos</h3>
    <div class="traits">${traits.map(traitHTML).join("")}</div>
    <h3>Aumentos recomendados</h3>
    ${augmentsHTML(c)}
    <h3>Cómo llegar: early y mid game</h3>
    ${transitionHTML(c)}
    <h3>Objetos</h3>
    ${itemRows}
    <h3>Consejos</h3>
    <p class="tips">${esc(c.tips)}</p>
    <button class="btn" data-load="${c.id}">Abrir en el creador</button>`;
  $("#sheet").hidden = false;
}

/* ---------- Creador ---------- */

function initBuilder() {
  renderTraitDropdown();
  renderPool();
  renderBoard();
}

function renderPool() {
  const q = $("#pool-search").value.trim().toLowerCase();
  const tf = state.poolTrait;
  const colors = { 1: "var(--c1)", 2: "var(--c2)", 3: "var(--c3)", 4: "var(--c4)", 5: "var(--c5)" };
  const groups = [1, 2, 3, 4, 5].map((cost) => {
    const champs = state.set.champions
      .filter((c) => c.cost === cost && (!q || c.name.toLowerCase().includes(q)) && (!tf || c.traits.includes(tf)))
      .sort((a, b) => a.name.localeCompare(b.name, "es"));
    if (!champs.length) return "";
    return `<div class="pool-group"><h3><i style="background:${colors[cost]}"></i>Coste ${cost}</h3>
      <div class="pool">${champs.map((c) => champHTML(c.id, { name: true, tag: "button" }).replace('class="champ', `class="champ${state.board.includes(c.id) ? " picked" : ""}`)).join("")}</div></div>`;
  }).join("");
  $("#pool").innerHTML = groups || `<p class="source">Ningún campeón coincide.</p>`;
}

function renderBoard() {
  const b = state.board;
  $("#board-count").textContent = `${b.length}/${MAX_BOARD}`;
  $("#board").innerHTML = b.length
    ? b.map((id) => champHTML(id, { name: true, tag: "button", items: state.boardItems[id] || [] })).join("")
    : `<span class="empty">Toca campeones de abajo para añadirlos. Toca uno de tu equipo para ponerle objetos o quitarlo.</span>`;
  const traits = computeTraits(b, state.boardItems);
  $("#board-traits").innerHTML = traits.map(traitHTML).join("");
  renderInv();
  const comps = myComponents();
  const similar = similarComps(b, comps);
  $("#board-suggest").innerHTML = similar.length
    ? `<h3>Te recomiendo ir a…</h3>${similar.map(({ c, shared, build, matched }) => {
        const why = [
          shared ? `${shared} de tus campeones` : "",
          comps.length ? `${matched}/${comps.length} componentes sirven` : "",
          esc(c.style),
        ].filter(Boolean).join(" · ");
        const craft = build.length
          ? `<span class="craft">Puedes hacer: ${build.map(({ item, champ }) =>
              `<span class="craft-it"><img src="${state.item[item].img}" alt="">${esc(state.item[item].name)} <small>→ ${esc(state.champ[champ]?.name || "")}</small></span>`).join("")}</span>`
          : "";
        return `<button class="suggest" data-comp="${c.id}">
          <span class="tier-dot ${c.tier === "?" ? "q" : c.tier}">${c.tier === "?" ? "–" : c.tier}</span>
          <span class="s-name">${esc(c.name)}<small>${why}</small>${craft}</span>
          <span class="s-units">${c.carries.map((u) => champHTML(u, { carry: true })).join("")}</span>
        </button>`;
      }).join("")}`
    : "";
  try {
    localStorage.setItem("tft-inv", JSON.stringify(state.inv));
    localStorage.setItem("tft-board", JSON.stringify(b));
    localStorage.setItem("tft-board-items", JSON.stringify(state.boardItems));
  } catch {}
}

function toggleChamp(id) {
  const i = state.board.indexOf(id);
  if (i >= 0) { state.board.splice(i, 1); delete state.boardItems[id]; }
  else if (state.board.length < MAX_BOARD) state.board.push(id);
  renderBoard();
  renderPool();
}

/* ---------- Desplegable de rasgos con icono ---------- */

function renderTraitDropdown() {
  const count = {};
  state.set.champions.forEach((c) => c.traits.forEach((t) => (count[t] = (count[t] || 0) + 1)));
  const hex = (t) => `<span class="hex"><img src="${t.img}" alt=""></span>`;
  const sel = state.trait[state.poolTrait];
  $("#trait-dd-btn").innerHTML = sel
    ? `${hex(sel)}<span class="dd-label">${esc(sel.name)}</span><span class="dd-caret">▾</span>`
    : `<span class="hex all">★</span><span class="dd-label">Todos los rasgos</span><span class="dd-caret">▾</span>`;
  const traits = [...state.set.traits].sort((a, b) => a.name.localeCompare(b.name, "es"));
  $("#trait-dd-list").innerHTML =
    `<button class="dd-opt${!sel ? " active" : ""}" data-pool-trait="" role="option"><span class="hex all">★</span>Todos los rasgos</button>` +
    traits.map((t) => `<button class="dd-opt${t.id === state.poolTrait ? " active" : ""}" data-pool-trait="${t.id}" role="option">
      ${hex(t)}<span class="dd-label">${esc(t.name)}</span><small>${count[t.id] || 0}</small></button>`).join("");
}

function toggleDropdown(open) {
  const list = $("#trait-dd-list");
  list.hidden = !open;
  $("#trait-dd-btn").setAttribute("aria-expanded", String(open));
  if (open) list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
}

/* ---------- Componentes sueltos ---------- */

function renderInv() {
  $("#inv-count").textContent = `${state.inv.length}/${MAX_INV}`;
  $("#inv").innerHTML = state.inv.length
    ? state.inv.map((id, k) => `<button class="inv-it" data-inv-rm="${k}" title="Quitar ${esc(state.item[id].name)}"><img src="${state.item[id].img}" alt="${esc(state.item[id].name)}"></button>`).join("")
    : `<span class="empty">Añádelos en la pestaña <b>Componentes</b> de abajo.</span>`;
  const comps = state.set.items.filter(isComponent);
  $("#inv-pick").innerHTML = comps.map((i) => `<button class="inv-add" data-inv-add="${i.id}" title="${esc(i.name)}"${state.inv.length >= MAX_INV ? " disabled" : ""}>
      <img src="${i.img}" alt=""><span>${esc(i.name)}</span></button>`).join("");
}

/* ---------- Objetos en el creador ---------- */

const isEmblem = (i) => i.kind === "emblem";
const isComponent = (i) => i.kind === "component";

/** Añade un objeto; si es un componente y ya lleva otro suelto, los combina como en el juego. */
function addItem(champ, itemId) {
  const items = state.boardItems[champ] || (state.boardItems[champ] = []);
  const item = state.item[itemId];
  if (isComponent(item)) {
    const j = items.findIndex((x) => isComponent(state.item[x]));
    const combo = j >= 0 && state.recipe[[items[j], itemId].sort().join("+")];
    if (combo) { items[j] = combo; return; }
  }
  if (items.length < 3) items.push(itemId);
}

function openChamp(id) {
  const c = state.champ[id];
  const items = state.boardItems[id] || [];
  const full = items.length >= 3 && !items.some((x) => isComponent(state.item[x]));
  const all = state.set.items;
  const group = (title, list) => `<h3>${title}</h3><div class="item-grid">${list
    .sort((a, b) => a.name.localeCompare(b.name, "es"))
    .map((i) => `<button class="item-btn" data-add-item="${i.id}" title="${esc(i.desc)}"${full ? " disabled" : ""}>
        <img src="${i.img}" alt=""><span>${esc(i.name)}</span></button>`).join("")}</div>`;

  $("#sheet-body").innerHTML = `
    <div class="champ-head">
      <img class="pic" src="${c.img}" alt="" style="border-color:var(--c${c.cost})">
      <div><h2>${esc(c.name)}</h2><small>Coste ${c.cost} · ${c.traits.map((t) => esc(state.trait[t]?.name || "")).join(" · ")}</small></div>
    </div>
    <h3>Objetos (${items.length}/3)</h3>
    <div class="slots">${[0, 1, 2].map((k) => {
      const it = state.item[items[k]];
      return it
        ? `<button class="slot filled" data-rm-item="${k}" title="Quitar"><img src="${it.img}" alt=""><span>${esc(it.name)}</span><b>×</b></button>`
        : `<div class="slot empty">Vacío</div>`;
    }).join("")}</div>
    <p class="source">Dos componentes se combinan solos en el objeto completo. Los emblemas añaden su rasgo al equipo.</p>
    ${group("Componentes", all.filter(isComponent))}
    ${group("Objetos completos", all.filter((i) => i.kind === "completed"))}
    ${group("Emblemas", all.filter(isEmblem))}
    ${group("Radiantes", all.filter((i) => i.kind === "radiant"))}
    ${group("Artefactos", all.filter((i) => i.kind === "artifact"))}
    <button class="btn danger" data-rm-champ="${id}">Quitar a ${esc(c.name)} del equipo</button>`;
  $("#sheet-body").dataset.champ = id;
  $("#sheet").hidden = false;
}

function showView(view) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  $("#view-comps").hidden = view !== "comps";
  $("#view-builder").hidden = view !== "builder";
  window.scrollTo(0, 0);
}

/* ---------- Eventos ---------- */

document.addEventListener("click", (e) => {
  if (e.target.closest("#trait-dd-btn")) return toggleDropdown($("#trait-dd-list").hidden);
  const opt = e.target.closest("[data-pool-trait]");
  if (opt) {
    state.poolTrait = opt.dataset.poolTrait;
    toggleDropdown(false);
    renderTraitDropdown();
    return renderPool();
  }
  if (!e.target.closest("#trait-dd")) toggleDropdown(false);

  const sub = e.target.closest(".subtab");
  if (sub) {
    document.querySelectorAll(".subtab").forEach((t) => t.classList.toggle("active", t === sub));
    $("#sub-champs").hidden = sub.dataset.sub !== "champs";
    $("#sub-items").hidden = sub.dataset.sub !== "items";
    return;
  }

  const tab = e.target.closest(".tab");
  if (tab) return showView(tab.dataset.view);

  const chip = e.target.closest(".chip");
  if (chip) {
    document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === chip));
    state.style = chip.dataset.style;
    return renderComps();
  }

  const tf = e.target.closest(".tf");
  if (tf) {
    const id = tf.dataset.trait;
    if (!id) state.traitSel.clear();
    else if (state.traitSel.has(id)) state.traitSel.delete(id);
    else state.traitSel.add(id);
    renderTraitFilter();
    return renderComps();
  }

  if (e.target.closest("[data-close]")) return ($("#sheet").hidden = true);

  const champId = $("#sheet-body").dataset.champ;
  const add = e.target.closest("[data-add-item]");
  if (add && champId) {
    addItem(champId, add.dataset.addItem);
    renderBoard();
    return openChamp(champId);
  }
  const rmItem = e.target.closest("[data-rm-item]");
  if (rmItem && champId) {
    (state.boardItems[champId] || []).splice(+rmItem.dataset.rmItem, 1);
    renderBoard();
    return openChamp(champId);
  }
  const rmChamp = e.target.closest("[data-rm-champ]");
  if (rmChamp) {
    $("#sheet").hidden = true;
    return toggleChamp(rmChamp.dataset.rmChamp);
  }

  const load = e.target.closest("[data-load]");
  if (load) {
    const c = state.comps.comps.find((x) => x.id === load.dataset.load);
    state.board = c.units.slice(0, MAX_BOARD);
    state.boardItems = Object.fromEntries(Object.entries(c.items).map(([u, its]) => [u, [...its]]));
    $("#sheet").hidden = true;
    renderBoard();
    renderPool();
    return showView("builder");
  }

  const card = e.target.closest(".card, .suggest");
  if (card) return openComp(card.dataset.comp);

  const invAdd = e.target.closest("[data-inv-add]");
  if (invAdd) {
    if (state.inv.length < MAX_INV) state.inv.push(invAdd.dataset.invAdd);
    return renderBoard();
  }
  const invRm = e.target.closest("[data-inv-rm]");
  if (invRm) {
    state.inv.splice(+invRm.dataset.invRm, 1);
    return renderBoard();
  }

  const onBoard = e.target.closest("#board .champ");
  if (onBoard) return openChamp(onBoard.dataset.id);

  const champ = e.target.closest("#pool .champ");
  if (champ) return toggleChamp(champ.dataset.id);

  if (e.target.id === "clear-board") { state.board = []; state.boardItems = {}; state.inv = []; renderBoard(); renderPool(); }
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#sheet").hidden = true; });
$("#search").addEventListener("input", (e) => { state.query = e.target.value; renderComps(); });
$("#pool-search").addEventListener("input", renderPool);


load().catch((err) => {
  $("#tiers").innerHTML = `<p class="warn">No se pudieron cargar los datos (${esc(err.message)}). Abre la web con el servidor local, no como archivo.</p>`;
});
