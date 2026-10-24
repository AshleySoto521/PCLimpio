// Copyright (C) 2026 ashleysoto521
// SPDX-License-Identifier: GPL-3.0-or-later
// PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"use strict";
// ------------------------------------------------------------------ utilidades
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || sessionStorage.getItem("t") || "";
sessionStorage.setItem("t", TOKEN);
history.replaceState(null, "", location.pathname);
let STATE = { admin: false };

async function api(route, body = {}) {
  const r = await fetch("/api/" + route, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Token": TOKEN }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Error ${r.status}`);
  return data;
}

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// append/replaceChildren nativos no aplanan arreglos ni ignoran null: usar estos
function add(el, ...kids) {
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false && k !== "") el.append(k);
  return el;
}
function fill(el, ...kids) { el.replaceChildren(); return add(el, ...kids); }

function size(n) {
  n = Number(n || 0);
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${n} B` : `${n.toFixed(n < 10 ? 2 : 1)} ${u[i]}`;
}

function toast(msg, error = false) {
  const t = h("div", { class: "toast" + (error ? " error" : "") }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), error ? 9000 : 5000);
}

async function guard(fn) {
  try { return await fn(); } catch (e) { toast(e.message, true); }
}

/** Lanza una tarea larga y muestra su progreso dentro de `box`. Devuelve el resultado o null. */
async function runJob(route, body, box, label) {
  const msg = h("div", { class: "small muted" }, "Iniciando…");
  const fill = h("i", { style: "width:0%" });
  const cancel = h("button", { class: "btn", onclick: () => api("jobs/cancel", { id: jobId }) }, "Cancelar");
  box.replaceChildren(h("div", { class: "progress" }, h("div", { class: "row" }, h("strong", {}, label), h("span", { class: "spacer" }), cancel),
    h("div", { class: "bar" }, fill), msg));
  let jobId;
  try {
    const start = await api(route, body);
    jobId = start.job.id;
    while (true) {
      const j = await api("jobs/get", { id: jobId });
      fill.style.width = j.progress + "%";
      msg.textContent = j.message || "";
      if (j.status === "done") { box.replaceChildren(); return j.result; }
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "cancelled") { box.replaceChildren(h("div", { class: "muted" }, "Cancelado.")); return null; }
      await new Promise(r => setTimeout(r, 600));
    }
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner" }, e.message));
    return null;
  }
}

function card(title, ...kids) { return h("div", { class: "card" }, title ? h("h2", {}, title) : null, ...kids); }

function adminBanner(text) {
  if (STATE.admin) return null;
  return h("div", { class: "banner" }, h("div", {}, h("div", {}, text || "Algunas cosas de esta sección tocan partes de Windows y necesitan tu permiso."),
    h("div", { class: "small" }, "Al pulsar el botón, Windows te preguntará si permites cambios. Es normal: responde «Sí».")),
    h("span", { class: "spacer" }), h("button", { class: "btn", onclick: elevate }, "Dar permiso"));
}

async function elevate() {
  const r = await guard(() => api("elevate"));
  if (r && r.ok) { toast("PCLimpio se abrirá de nuevo con permiso. Esta ventana se cerrará."); setTimeout(() => window.close(), 2500); }
}

/** Párrafo de ayuda al inicio de cada sección: qué hace y qué no toca. */
function intro(...lines) {
  return h("div", { class: "card intro" }, lines.map((l, i) => h("p", { class: i ? "small muted" : "" }, l)));
}

function tabs(defs, host) {
  const bar = h("div", { class: "tabs" });
  const body = h("div", { style: "padding-top:14px;display:grid;gap:14px" });
  const show = (i) => {
    [...bar.children].forEach((b, k) => b.classList.toggle("active", k === i));
    body.replaceChildren();
    defs[i].render(body);
  };
  defs.forEach((d, i) => bar.append(h("button", { onclick: () => show(i) }, d.title)));
  host.append(h("div", { class: "card" }, bar, body));
  show(0);
}

function checkAll(table, on) { table.querySelectorAll("tbody input[type=checkbox]").forEach(c => { c.checked = on; }); }
function checkedValues(root) { return [...root.querySelectorAll("input[type=checkbox]:checked")].map(c => c.value).filter(Boolean); }

/** `locked(r)` devuelve el motivo si la fila está protegida: se muestra el candado y no se puede marcar. */
function selectableTable(cols, rows, { key, checked = () => false, render, locked = () => null }) {
  const all = h("input", { type: "checkbox", onchange: (e) => checkAll(table, e.target.checked) });
  const table = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, all), cols.map(c => h("th", { class: c.num ? "num" : "" }, c.label)))),
    h("tbody", {}, rows.map(r => {
      const why = locked(r);
      return h("tr", { class: why ? "locked" : "" },
        h("td", {}, why ? h("span", { title: why }, "🔒") : h("input", { type: "checkbox", value: key(r), checked: checked(r) })), render(r));
    })));
  return table;
}

/** Etiqueta "Protegido" con el motivo visible debajo. */
function protectedNote(why) {
  return why ? h("div", { class: "protected" }, h("span", { class: "pill bad" }, "🔒 Protegido"), " ", why) : null;
}

function showBlocked(list) {
  if (!list || !list.length) return;
  toast(`${list.length} elemento(s) no se tocaron por protección del sistema: ${list[0].reason}`, true);
}

// ------------------------------------------------------------------ páginas
const PAGES = [
  { id: "home", title: "Inicio", ico: "⌂", sub: "Cómo está tu equipo y por dónde empezar", render: renderHome },
  { sep: "Limpieza" },
  { id: "basic", title: "Limpieza básica", ico: "✦", sub: "Quita archivos que sobran sin tocar lo tuyo", render: (p) => renderCleaning(p, "basica") },
  { id: "advanced", title: "Limpieza avanzada", ico: "✧", sub: "Una limpieza más a fondo: restos de actualizaciones, instaladores y programas", render: renderAdvanced },
  { id: "history", title: "Limpiador automático del historial", ico: "⟲", sub: "Borra el rastro de lo que haces en Internet, cuando tú quieras o solo", render: renderHistory },
  { id: "analyzer", title: "Analizador de disco", ico: "◔", sub: "Descubre qué está llenando tu disco y qué puedes quitar", render: renderAnalyzer },
  { sep: "Rendimiento" },
  { id: "optimizer", title: "Optimizador de rendimiento", ico: "⚡", sub: "Haz que el equipo encienda y vaya más rápido", render: renderOptimizer },
  { id: "drivers", title: "Actualizador de controladores", ico: "⚙", sub: "Que la pantalla, el sonido y el Wi-Fi funcionen bien", render: renderDrivers },
  { id: "software", title: "Actualizador de software", ico: "⇪", sub: "Mantén tus programas al día y quita los que no uses", render: renderSoftware },
  { sep: "Herramientas" },
  { id: "recovery", title: "Recuperación de archivos", ico: "↺", sub: "Rescata archivos que borraste por error", render: renderRecovery },
  { id: "sysinfo", title: "Información del sistema", ico: "ⓘ", sub: "Qué piezas tiene tu equipo y si están bien", render: renderSysinfo },
  { id: "activity", title: "Historial de actividad", ico: "☰", sub: "Todo lo que PCLimpio ha borrado o cambiado en tu equipo", render: renderActivity },
];

// ---------------------------------------------------------------- Historial de actividad
async function renderActivity(p) {
  p.append(card(null, h("p", {}, "Aquí queda anotado, con fecha y hora, todo lo que PCLimpio borra o cambia. Si algo no aparece en esta lista, PCLimpio no lo hizo."),
    h("p", { class: "small muted" }, "PCLimpio tampoco puede borrar archivos de Windows ni de tus programas: esa protección está siempre activa, aunque se abra como administrador. Si faltan archivos del sistema, el cambio se hizo fuera de esta app."),
    h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: () => api("activity/open") }, "Abrir el archivo del historial"))));
  const r = await guard(() => api("activity/list"));
  if (!r) return;
  if (!r.entries.length) return p.append(card(null, h("div", { class: "empty" }, "Todavía no has borrado ni cambiado nada con PCLimpio.")));
  p.append(card(null, h("div", { class: "items" }, r.entries.map(e => h("div", { class: "item v-tuyo" }, h("div", { class: "item-check" }, "•"),
    h("div", { class: "item-body" },
      h("div", { class: "row" }, h("strong", {}, e.summary), h("span", { class: "spacer" }), e.freed ? h("span", { class: "pill ok" }, `${size(e.freed)} liberados`) : null),
      h("div", { class: "small muted" }, `${e.time} · ${e.section}`),
      e.details.length ? h("details", { class: "where" }, h("summary", {}, `Ver detalle (${e.details.length})`),
        h("div", { class: "small path", style: "max-height:240px;overflow:auto" }, e.details.map(d => h("div", {}, d)))) : null))))));
}

function go(id) {
  const page = PAGES.find(p => p.id === id) || PAGES[0];
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("active", b.dataset.id === page.id));
  document.getElementById("page-title").textContent = page.title;
  document.getElementById("page-sub").textContent = page.sub;
  const host = document.getElementById("page");
  host.replaceChildren();
  page.render(host);
  sessionStorage.setItem("page", page.id);
}

// ---------------------------------------------------------------- Inicio
async function renderHome(p) {
  const data = await guard(() => api("home"));
  if (!data) return;
  p.append(h("div", { class: "grid" }, data.drives.map(d => {
    const pct = d.total ? Math.round(d.used * 100 / d.total) : 0;
    return card(`${d.label} (${d.letter}:)`,
      h("div", { class: "big" }, size(d.free), h("span", { class: "small muted" }, " libres")),
      h("div", { class: "bar" + (pct > 90 ? " high" : ""), style: "margin:8px 0" }, h("i", { style: `width:${pct}%` })),
      h("div", { class: "small muted" }, `Ocupado el ${pct} % · ${d.type === "extraíble" ? "memoria USB o disco externo" : "disco del equipo"}`),
      pct > 90 ? h("div", { class: "small", style: "color:var(--bad);margin-top:4px" }, "Queda poco espacio: prueba la Limpieza básica o el Analizador de disco.") : null);
  }), card("Papelera de reciclaje", h("div", { class: "big" }, size(data.recycle.bytes)),
    h("div", { class: "small muted" }, data.recycle.items ? `${data.recycle.items} cosa(s) que borraste y aún puedes recuperar` : "Está vacía"))));
  const steps = [
    ["basic", "1. Haz una limpieza básica", "Quita archivos que sobran. Es seguro y rápido."],
    ["analyzer", "2. Mira qué llena tu disco", "Te dice qué ocupa más y si lo puedes quitar."],
    ["optimizer", "3. Acelera el encendido", "Apaga programas que se abren solos sin que los uses."],
    ["software", "4. Actualiza tus programas", "Corrige fallos de seguridad con un clic."],
  ];
  p.append(card("¿Por dónde empiezo?", h("div", { class: "grid" }, steps.map(([id, t, d]) => h("button", { class: "step", onclick: () => go(id) }, h("strong", {}, t), h("span", { class: "small muted" }, d))))));
  const rules = await guard(() => api("safety/rules"));
  if (rules) p.append(card("🔒 Tu equipo está protegido",
    h("p", { class: "small muted" }, "PCLimpio nunca borra archivos de Windows ni de tus programas, nunca apaga tu antivirus y nunca cierra procesos esenciales, aunque le des permiso. Cuando algo está protegido verás 🔒 y el motivo."),
    h("details", {}, h("summary", {}, "Ver qué está protegido y por qué"),
      h("table", {}, h("tbody", {}, rules.untouchable.map(u => h("tr", {}, h("td", { class: "path small" }, u.path), h("td", { class: "small muted" }, u.reason))))))));
}

// ---------------------------------------------------------------- Limpieza (básica / archivos avanzados)
async function renderCleaning(p, level) {
  p.append(level === "basica"
    ? intro("Quita archivos que sobran: temporales, copias guardadas por los navegadores y restos que Windows vuelve a crear solo cuando los necesita.",
        "No toca tus documentos, fotos, contraseñas ni sesiones. Primero te dice cuánto puedes liberar y luego tú decides.")
    : intro("Lo mismo que la limpieza básica, pero más a fondo: restos de actualizaciones de Windows, de instaladores y archivos temporales de tus programas.",
        "Tampoco toca tus archivos personales. Lo que viene desmarcado es opcional: lee su descripción antes de marcarlo."),
    adminBanner("Algunas carpetas de Windows solo se pueden limpiar con tu permiso. Sin él, se limpia todo lo demás.") || "");
  const data = await guard(() => api("cleaning/rules", { level }));
  if (!data) return;
  const list = h("div");
  const groups = {};
  data.rules.forEach(r => (groups[r.group] = groups[r.group] || []).push(r));
  for (const [g, rules] of Object.entries(groups)) {
    add(list, h("h3", {}, g), rules.map(r => h("label", { class: "check" },
      h("input", { type: "checkbox", value: r.id, checked: r.default }),
      h("span", {}, r.name, r.needs_admin && !STATE.admin ? h("span", { class: "pill warn", style: "margin-left:6px" }, "necesita permiso") : null,
        h("span", { class: "desc" }, r.desc)))));
  }
  const status = h("div");
  const results = h("div");
  const analyze = async () => {
    const ids = checkedValues(list);
    if (!ids.length) return toast("Marca al menos una casilla");
    const res = await runJob("cleaning/analyze", { ids }, status, "Calculando cuánto puedes liberar");
    if (res) showAnalysis(res, ids);
  };
  const noteFor = (r) => [
    r.running_names.length ? h("div", { class: "pill warn" }, `Cierra ${r.running_names.join(" y ")} para limpiar esto`) : null,
    r.skipped_admin ? h("div", { class: "pill" }, "Una parte necesita permiso") : null,
    r.special === "dns" || r.special === "clipboard" ? h("div", { class: "small muted" }, "No libera espacio") : null];
  const showAnalysis = (res, ids) => {
    const running = [...new Set(res.rules.flatMap(r => r.running))];
    const runningNames = [...new Set(res.rules.flatMap(r => r.running_names))];
    fill(results, card(null,
      h("div", { class: "row" }, h("div", { class: "big" }, size(res.total_bytes)), h("span", { class: "muted" }, "puedes liberar"),
        h("span", { class: "spacer" }),
        running.length ? h("button", { class: "btn", onclick: async () => {
          if (!confirm(`Se cerrará ${runningNames.join(" y ")}. Guarda lo que tengas abierto ahí antes de seguir. ¿Lo cierro?`)) return;
          await guard(() => api("close-processes", { processes: running })); analyze();
        } }, `Cerrar ${runningNames.join(" y ")} por mí`) : null,
        h("button", { class: "btn primary", onclick: () => doClean(ids) }, "Limpiar ahora")),
      h("div", { class: "items", style: "margin-top:10px" }, res.rules.map(r => h("div", { class: "item " + (r.bytes ? "v-borrar" : "") },
        h("div", { class: "item-check" }, r.bytes ? "✓" : "–"),
        h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, r.name), h("span", { class: "spacer" }), h("span", { class: "num" }, r.bytes ? size(r.bytes) : "Nada que limpiar")),
          noteFor(r),
          r.sample.length ? h("details", { class: "where" }, h("summary", {}, `Ver qué archivos (${r.files.toLocaleString()})`),
            r.sample.map(s => h("div", { class: "small muted path" }, `${s.path} (${size(s.size)})`))) : null))))));
  };
  const doClean = async (ids) => {
    if (!confirm("Se van a borrar estos archivos sobrantes. Tus documentos, fotos y contraseñas no se tocan. ¿Seguimos?")) return;
    const res = await runJob("cleaning/clean", { ids }, status, "Limpiando");
    if (!res) return;
    fill(results, card(null,
      h("div", { class: "row" }, h("div", { class: "big" }, "¡Listo! " + size(res.total_freed)), h("span", { class: "muted" }, "liberados")),
      h("div", { class: "items", style: "margin-top:10px" }, res.rules.map(r => h("div", { class: "item " + (r.freed ? "v-borrar" : "") }, h("div", { class: "item-check" }, r.freed ? "✓" : "–"),
        h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, r.name), h("span", { class: "spacer" }), h("span", { class: "num" }, size(r.freed))),
          r.note ? h("div", { class: "small muted" }, r.note) : null))))));
    toast(`¡Listo! Liberaste ${size(res.total_freed)}`);
  };
  p.append(card(null, h("div", { class: "row" }, h("button", { class: "btn", onclick: () => list.querySelectorAll("input").forEach(c => c.checked = true) }, "Marcar todo"),
    h("button", { class: "btn", onclick: () => list.querySelectorAll("input").forEach(c => c.checked = false) }, "Desmarcar todo"),
    h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: analyze }, "Ver cuánto puedo liberar")), list), status, results);
}

function renderAdvanced(p) {
  tabs([
    { title: "Archivos y programas", render: (b) => renderCleaning(b, "avanzada") },
    { title: "Anotaciones rotas de Windows", render: renderRegistry },
  ], p);
}

async function renderRegistry(p) {
  p.append(intro("Windows lleva una gran lista interna (el «registro») con tus programas y accesos. Al desinstalar algo, a veces quedan anotaciones que apuntan a cosas que ya no existen.",
      "Quitarlas pone orden, pero seamos sinceros: no hará tu equipo notablemente más rápido. Antes de cambiar nada se guarda una copia para poder deshacerlo."),
    adminBanner("Algunas anotaciones son de Windows y solo se pueden quitar con tu permiso. Sin él, se arreglan las de tu usuario.") || "");
  const status = h("div"), out = h("div"), backups = h("div");
  const scan = async () => {
    const res = await runJob("registry/scan", {}, status, "Revisando anotaciones");
    if (!res) return;
    if (!res.issues.length) return fill(out, h("div", { class: "empty" }, "Todo en orden: no hay anotaciones rotas."));
    const groups = new Map();
    res.issues.forEach(i => { if (!groups.has(i.plain_title)) groups.set(i.plain_title, []); groups.get(i.plain_title).push(i); });
    const list = h("div", { class: "items" }, [...groups.entries()].map(([title, items]) => {
      const usable = items.filter(i => !i.admin || STATE.admin);
      return h("div", { class: "item v-borrar" },
        h("div", { class: "item-check" }, usable.length ? h("input", { type: "checkbox", value: usable.map(i => i.id).join("\n"), checked: true }) : h("span", { title: "Necesita permiso" }, "🔒")),
        h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, title), h("span", { class: "pill" }, `${items.length}`),
            usable.length < items.length ? h("span", { class: "pill warn" }, `${items.length - usable.length} necesitan permiso`) : null),
          h("div", {}, items[0].plain_what),
          h("details", { class: "where" }, h("summary", {}, "Ver cuáles"),
            items.slice(0, 200).map(i => h("div", { class: "small muted path" }, i.target ? `${i.target}` : `${i.hive}\\${i.key}`)))));
    }));
    fill(out, h("div", { class: "row" }, h("strong", {}, `${res.issues.length} anotaciones rotas`), h("span", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: () => fix(checkedValues(list).flatMap(v => v.split("\n"))) }, "Quitar las marcadas")), list);
  };
  const fix = async (ids) => {
    if (!ids.length) return toast("No hay nada marcado");
    if (!confirm(`Se quitarán ${ids.length} anotaciones rotas. Antes se guarda una copia para poder deshacerlo. ¿Seguimos?`)) return;
    const res = await runJob("registry/fix", { ids }, status, "Quitando anotaciones rotas");
    if (res) { toast(`Listo: ${res.fixed} anotaciones quitadas. Si algo falla, usa «Deshacer» abajo.`); if (res.failed.length) toast(`${res.failed.length} no se pudieron quitar: ${res.failed[0].error}`, true); scan(); loadBackups(); }
  };
  const loadBackups = async () => {
    const r = await guard(() => api("registry/backups"));
    if (!r) return;
    const when = (name) => name.replace(/^registro_(\d{4})(\d\d)(\d\d)_(\d\d)(\d\d)\d\d$/, "$3/$2/$1 a las $4:$5");
    fill(backups, h("h3", {}, "Copias para deshacer"), r.backups.length ? r.backups.map(b => h("div", { class: "row" },
      h("span", {}, `Cambios del ${when(b.name)}`), h("span", { class: "spacer" }),
      h("button", { class: "btn", onclick: async () => { if (confirm("¿Deshacer estos cambios y dejar las anotaciones como estaban?")) { const x = await guard(() => api("registry/restore", { name: b.name })); if (x) toast(x.restored ? "Cambios deshechos" : x.errors.join("; "), !x.restored); } } }, "Deshacer"))) : h("div", { class: "empty" }, "Todavía no has cambiado nada aquí."));
  };
  p.append(h("div", { class: "row" }, h("button", { class: "btn primary", onclick: scan }, "Buscar anotaciones rotas")), status, out, backups);
  loadBackups();
}

// ---------------------------------------------------------------- Historial
async function renderHistory(p) {
  const st = await guard(() => api("history/status"));
  if (!st) return;
  const s = st.settings;
  const bList = h("div", {}, st.browsers.length ? st.browsers.map(b => h("label", { class: "check" },
    h("input", { type: "checkbox", value: b.id, checked: b.enabled }),
    h("span", {}, b.name, " ", b.running ? h("span", { class: "pill warn" }, "abierto ahora") : h("span", { class: "pill ok" }, "cerrado"),
      h("span", { class: "desc" }, `Historial ${size(b.sizes.history)} · páginas guardadas ${size(b.sizes.cache)} · sesiones ${size(b.sizes.cookies)}`)))) :
    h("div", { class: "empty" }, "No se encontraron navegadores compatibles."));
  const iList = h("div", {}, Object.entries(st.items).map(([k, v]) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: s.items.includes(k) }), h("span", {}, v))));
  const wList = h("div", {}, Object.entries(st.windows).map(([k, v]) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: s.windows.includes(k) }), h("span", {}, v))));
  const closeBox = h("input", { type: "checkbox" });
  const status = h("div");
  const selection = () => ({ browsers: checkedValues(bList), items: checkedValues(iList), windows: checkedValues(wList) });
  const save = async () => {
    const sel = selection();
    const browsers = Object.fromEntries(st.browsers.map(b => [b.id, sel.browsers.includes(b.id)]));
    await guard(() => api("history/save", { settings: { browsers, items: sel.items, windows: sel.windows } }));
  };
  const clean = async () => {
    const sel = selection();
    if (!sel.browsers.length && !sel.windows.length) return toast("Marca al menos un navegador o una opción de Windows");
    const warnCookies = sel.items.includes("cookies") ? " Tendrás que volver a iniciar sesión en tus webs (correo, redes…)." : "";
    if (!confirm(`Se borrará lo que marcaste.${warnCookies} ¿Seguimos?`)) return;
    await save();
    const res = await runJob("history/clean", { ...sel, close: closeBox.checked }, status, "Limpiando");
    if (!res) return;
    fill(status, card("¡Listo!", res.browsers.map(b => h("div", {}, h("strong", {}, b.browser), ": ",
      b.skipped ? h("span", { class: "pill warn" }, "no se limpió porque estaba abierto") : (b.errors.length ? "limpiado en parte" : "limpio ✓"))),
      res.windows.length ? h("div", {}, h("strong", {}, "Windows"), ": limpio ✓") : null));
  };
  const freq = h("select", {}, h("option", { value: "DAILY", selected: s.schedule.frequency === "DAILY" }, "Cada día"),
    h("option", { value: "WEEKLY", selected: s.schedule.frequency === "WEEKLY" }, "Cada semana (domingo)"));
  const at = h("input", { type: "time", value: s.schedule.time });
  const enabled = h("input", { type: "checkbox", checked: s.schedule.enabled });
  const schedule = async () => {
    await save();
    const r = await guard(() => api("history/schedule", { enabled: enabled.checked, frequency: freq.value, time: at.value }));
    if (r) toast(r.ok ? (enabled.checked ? "Listo: se limpiará solo en el horario elegido" : "Limpieza automática apagada") : "No se pudo guardar el horario", !r.ok);
  };
  p.append(intro("Borra el rastro de lo que haces en Internet: páginas visitadas, sesiones abiertas y más. Útil si compartes el equipo o quieres más privacidad.",
      "Tus favoritos/marcadores y tus contraseñas guardadas no se borran. Los navegadores deben estar cerrados para limpiarlos."),
    h("div", { class: "grid" }, card("1. ¿En qué navegadores?", bList), card("2. ¿Qué borrar?", iList), card("También en Windows", wList)),
    card("Limpiar ahora", h("label", { class: "check" }, closeBox, h("span", {}, "Cerrar los navegadores abiertos por mí",
      h("span", { class: "desc" }, "Guarda antes lo que estés haciendo en ellos. Si no los cierras, los abiertos se saltan."))),
      h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: clean }, "Limpiar ahora"))),
    card("Que se limpie solo", h("p", { class: "muted small" }, "PCLimpio limpiará lo que marcaste el día y la hora que elijas, aunque no abras la app. Si en ese momento un navegador está abierto, se lo salta."),
      h("div", { class: "row" }, h("label", { class: "check" }, enabled, h("span", {}, "Activado")), freq, "a las", at, h("span", { class: "spacer" }),
        h("button", { class: "btn primary", onclick: schedule }, "Guardar horario")),
      h("div", { class: "small muted" }, st.task.exists ? "✓ Está programado." : "Ahora mismo no está programado.")), status);
}

// ---------------------------------------------------------------- Analizador de disco
const CATS = { video: "Video", picture: "Imágenes", music: "Música", document: "Documentos", application: "Aplicaciones", archive: "Comprimidos", other: "Otros" };

async function renderAnalyzer(p) {
  const d = await guard(() => api("analyzer/drives"));
  if (!d) return;
  const drives = h("div", { class: "row" }, d.drives.map(x => h("label", { class: "check" }, h("input", { type: "checkbox", value: x.root, checked: x.letter === "C" }),
    h("span", {}, `${x.label} (${x.letter}:)`, h("span", { class: "desc" }, `${size(x.used)} usados de ${size(x.total)}`)))));
  const folder = h("input", { type: "text", placeholder: "O escribe carpetas separadas por ;  (ej. C:\\Users\\Ashley\\Downloads)", style: "width:100%" });
  const minKb = h("input", { type: "number", value: 1024, min: 0, style: "width:110px" });
  const opt = (label, on) => { const c = h("input", { type: "checkbox", checked: on }); return [c, h("label", { class: "check" }, c, h("span", {}, label))]; };
  const [dupes, dupesL] = opt("Buscar archivos duplicados", true);
  const [hid, hidL] = opt("Ignorar archivos ocultos", false);
  const [sys, sysL] = opt("Ignorar archivos de sistema", true);
  const [ro, roL] = opt("Ignorar solo lectura", false);
  const [comp, compL] = opt("Ignorar comprimidos por NTFS", false);
  const status = h("div"), out = h("div", { style: "display:grid;gap:16px" });
  const scan = async () => {
    const folders = folder.value.split(";").map(s => s.trim()).filter(Boolean);
    const items = folders.length ? folders : checkedValues(drives);
    if (!items.length) return toast("Elige una unidad o carpeta");
    const res = await runJob("analyzer/scan", { items, opts: { min_size: Number(minKb.value) * 1024, duplicates: dupes.checked, ignore_hidden: hid.checked, ignore_system: sys.checked, ignore_readonly: ro.checked, ignore_compressed: comp.checked } }, status, "Analizando disco");
    if (res) showResults(res);
  };
  const del = async (paths, permanent) => {
    if (!paths.length) return toast("No hay archivos seleccionados");
    const how = permanent ? "se ELIMINARÁN PERMANENTEMENTE" : "se moverán a la Papelera";
    if (!confirm(`${paths.length} archivo(s) ${how}. ¿Continuar?`)) return;
    const r = await runJob("analyzer/delete", { paths, permanent }, status, "Eliminando");
    if (r) { toast(`${r.deleted} archivo(s) eliminados · ${size(r.freed)} liberados`); if (r.failed.length) toast(`${r.failed.length} no se pudieron eliminar`, true); showBlocked(r.blocked); }
  };
  const showResults = (r) => {
    const max = Math.max(1, ...r.categories.map(c => c.bytes));
    const safe = r.top_files.filter(f => ["borrar", "limpiar"].includes(f.info.verdict)).reduce((a, f) => a + f.size, 0);
    // Lista de archivos explicados, con filtro por veredicto
    const list = h("div", { class: "items" });
    const counts = {};
    r.top_files.forEach(f => { counts[f.info.verdict] = (counts[f.info.verdict] || 0) + 1; });
    const actionable = r.top_files.length - (counts.no || 0);
    // Por defecto se ve solo lo que el usuario puede quitar; lo de Windows y programas queda en su filtro
    let current = actionable ? "actionable" : "all";
    const drawFiles = () => {
      const rows = r.top_files.filter(f => current === "all" || (current === "actionable" ? f.info.verdict !== "no" : f.info.verdict === current));
      fill(list, rows.length ? groupSame(rows).slice(0, 200).map(g => g.files.length > 1
        ? explainedItem({ ...g.info, title: `${g.info.title} · ${g.files.length} archivos` }, g.size, g.files[0].path, false)
        : explainedItem(g.info, g.size, g.files[0].path, true)) : h("div", { class: "empty" }, "Nada en esta categoría."));
    };
    const chips = h("div", { class: "row chips" }, [["actionable", "Lo que puedes quitar", actionable], ["all", "Todos", r.top_files.length], ...Object.entries(VERDICT_TEXT).filter(([k]) => counts[k]).map(([k, v]) => [k, v, counts[k]])]
      .filter(([k, , n]) => n || k === "all")
      .map(([k, label, n]) => h("button", { class: "chip" + (k === current ? " active" : ""), onclick: (e) => {
        current = k; e.target.parentNode.querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c === e.target)); drawFiles();
      } }, `${label} (${n})`)));
    drawFiles();
    const dupList = h("div", { class: "items" }, r.duplicates.slice(0, 200).map(g => h("div", { class: "item" },
      h("div", { class: "row" }, h("strong", {}, `${g.files.length} copias iguales de «${g.files[0].path.split("\\").pop()}»`), verdictPill(g.info.verdict, g.info.verdict_label),
        h("span", { class: "spacer" }), h("span", { class: "num" }, `${size(g.size * (g.files.length - 1))} repetidos`)),
      h("div", { class: "small muted" }, g.info.what),
      g.files.map((f, i) => h("label", { class: "check small" }, h("input", { type: "checkbox", value: f.path, checked: i > 0 && g.info.verdict !== "no" }),
        h("span", { class: "path" }, f.path, i === 0 ? h("span", { class: "pill ok", style: "margin-left:6px" }, "la más antigua: se conserva") : null))))));
    fill(out,
      card("¿Qué ocupa tu espacio?", h("div", { class: "row" }, h("div", { class: "big" }, size(r.total_bytes)), h("span", { class: "muted" }, `en ${r.scanned.toLocaleString()} archivos`),
        safe ? h("span", { class: "pill ok" }, `${size(safe)} se pueden liberar sin riesgo entre los más grandes`) : null,
        r.duplicates.length ? h("span", { class: "pill warn" }, `${size(r.duplicate_waste)} en archivos repetidos`) : null),
        r.categories.map(c => h("div", { class: "catbar" }, h("span", {}, `${c.name} (${c.files.toLocaleString()})`), h("div", { class: "bar" }, h("i", { style: `width:${c.bytes * 100 / max}%` })), h("span", { class: "num" }, size(c.bytes))))),
      legendCard(),
      card("Archivos más grandes", h("p", { class: "small muted" }, "Cada archivo te dice qué es y si lo puedes borrar. Marca solo los que quieras quitar; se mueven a la Papelera, así que puedes recuperarlos."),
        chips, h("div", { class: "scroll tall" }, list),
        h("div", { class: "row", style: "margin-top:10px" }, h("span", { class: "spacer" }),
          h("button", { class: "btn", onclick: () => del(checkedValues(list), true) }, "Eliminar para siempre"),
          h("button", { class: "btn primary", onclick: () => del(checkedValues(list), false) }, "Mover a la Papelera"))),
      card("Carpetas que más ocupan", h("div", { class: "scroll tall items" }, r.top_folders.slice(0, 40).map(f => explainedItem(f.info, f.size, f.path, false)))),
      r.duplicates.length ? card(`Archivos repetidos (${r.duplicates.length} grupos)`,
        h("p", { class: "small muted" }, "Son copias exactas del mismo archivo (se comparó su contenido, no solo el nombre). Se marca todo menos la copia más antigua."),
        h("div", { class: "scroll tall" }, dupList),
        h("div", { class: "row", style: "margin-top:10px" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: () => del(checkedValues(dupList), false) }, "Mover las copias marcadas a la Papelera"))) : null);
  };
  p.append(card("¿Qué quieres revisar?", drives,
    h("details", { style: "margin-top:8px" }, h("summary", { class: "muted" }, "Opciones avanzadas"),
      h("div", { style: "display:grid;gap:8px;padding:8px 0" }, h("div", {}, h("div", { class: "small muted" }, "Revisar solo estas carpetas (separadas por ;)"), folder),
        h("div", { class: "row" }, "Mostrar archivos a partir de (KB):", minKb), h("div", { class: "row" }, dupesL, hidL, sysL, roL, compL))),
    h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: scan }, "Analizar"))), status, out);
}

const VERDICT_TEXT = { borrar: "Puedes borrarlo", limpiar: "Seguro: límpialo con la app", revisar: "Revisa antes de borrar", tuyo: "Es tuyo: decide tú", no: "No lo borres" };
const VERDICT_CLASS = { borrar: "ok", limpiar: "ok", revisar: "warn", tuyo: "info", no: "bad" };
const PAGE_LABEL = { basic: "Ir a Limpieza básica", advanced: "Ir a Limpieza avanzada", software: "Ir a Programas instalados" };

/** Junta en una sola fila los archivos que no se eligen uno a uno (cachés, partes de un programa…). */
function groupSame(files) {
  const out = [], byKey = new Map();
  for (const f of files) {
    const individual = ["borrar", "revisar", "tuyo"].includes(f.info.verdict) && !f.info.protected;
    const key = individual ? null : `${f.info.verdict}|${f.info.title}`;
    if (key && byKey.has(key)) {
      const g = byKey.get(key);
      g.files.push(f);
      g.size += f.size;
      continue;
    }
    const g = { info: f.info, files: [f], size: f.size };
    out.push(g);
    if (key) byKey.set(key, g);
  }
  return out;
}

function verdictPill(v, label) { return h("span", { class: "pill " + (VERDICT_CLASS[v] || "") }, (v === "no" ? "🔒 " : "") + (label || VERDICT_TEXT[v])); }

/** Un elemento explicado: qué es, si se puede borrar y qué hacer; la ruta queda en segundo plano. */
function explainedItem(info, bytes, path, selectable) {
  const canSelect = selectable && ["borrar", "revisar", "tuyo"].includes(info.verdict) && !info.protected;
  const goTo = info.page ? h("button", { class: "btn small-btn", onclick: () => go(info.page === "software" ? "software" : info.page) }, PAGE_LABEL[info.page]) : null;
  return h("div", { class: "item v-" + info.verdict },
    h("div", { class: "item-check" }, canSelect ? h("input", { type: "checkbox", value: path }) : h("span", { title: info.verdict_label }, info.verdict === "no" ? "🔒" : "")),
    h("div", { class: "item-body" },
      h("div", { class: "row" }, h("strong", {}, info.title), verdictPill(info.verdict, info.verdict_label), h("span", { class: "spacer" }), h("span", { class: "num" }, size(bytes))),
      h("div", {}, info.what),
      h("div", { class: "advice" }, "👉 ", info.advice, " ", goTo),
      h("details", { class: "where" }, h("summary", {}, "¿Dónde está?"),
        h("div", { class: "path small" }, path, " ", h("button", { class: "link", onclick: () => api("open-folder", { path }) }, "Abrir ubicación")))));
}

function legendCard() {
  const lines = [
    ["borrar", "Basura o restos que ya no sirven. Quitarlos no afecta a nada."],
    ["limpiar", "Es seguro quitarlo, pero hazlo desde Limpieza básica o avanzada: la app sabe hacerlo sin romper nada."],
    ["revisar", "Normalmente sobra, pero comprueba que ya no lo necesitas."],
    ["tuyo", "Son tus fotos, videos o documentos. Solo tú sabes si los quieres."],
    ["no", "Lo necesita Windows o un programa. Si quieres quitar un programa, usa Programas instalados."],
  ];
  return h("details", { class: "card legend" }, h("summary", {}, h("strong", {}, "¿Qué significa cada etiqueta?")),
    h("div", { style: "display:grid;gap:6px;margin-top:10px" }, lines.map(([v, t]) => h("div", { class: "row" }, verdictPill(v), h("span", { class: "small" }, t)))));
}

// ---------------------------------------------------------------- Optimizador
function renderOptimizer(p) {
  tabs([
    { title: "Programas que trabajan a escondidas", render: renderApps },
    { title: "Al encender el equipo", render: renderStartup },
    { title: "Qué está usando la memoria", render: renderProcesses },
    { title: "Modo de energía", render: renderPower },
  ], p);
}

let OPT_CACHE = null;
async function loadOverview(box, force) {
  if (OPT_CACHE && !force) return OPT_CACHE;
  OPT_CACHE = await runJob("optimizer/overview", {}, box, "Buscando programas que trabajan a escondidas");
  return OPT_CACHE;
}

async function toggle(id, enabled) {
  const r = await guard(() => api("optimizer/toggle", { id, enabled }));
  if (r) toast(enabled ? "Encendido de nuevo" : "Apagado. Puedes volver a encenderlo cuando quieras.");
  return !!r;
}

/** Interruptor de un componente explicado: qué es, qué pasa si lo apagas, detalles técnicos escondidos. */
function componentRow(c) {
  // Un componente protegido activo no se puede apagar (sí volver a encender si ya estaba apagado)
  const lockedOn = c.protected && c.enabled;
  const sw = lockedOn ? h("span", { title: c.protected }, "🔒")
    : h("label", { class: "switch" }, h("input", { type: "checkbox", checked: c.enabled, onchange: async (e) => { if (!(await toggle(c.id, e.target.checked))) e.target.checked = !e.target.checked; else c.enabled = e.target.checked; } }),
      h("span", { class: "small" }, c.enabled ? "Encendido" : "Apagado"));
  return h("div", { class: "item " + (lockedOn ? "v-no" : c.enabled ? "v-tuyo" : "") }, h("div", { class: "item-check", style: "min-width:90px" }, sw),
    h("div", { class: "item-body" },
      h("div", { class: "row" }, h("strong", {}, c.friendly || c.name), h("span", { class: "pill" }, c.type_plain),
        c.admin && !STATE.admin && !lockedOn ? h("span", { class: "pill warn" }, "necesita permiso") : null),
      lockedOn ? protectedNote(c.protected) : h("div", { class: "small muted" }, "Si lo apagas: ", c.off_effect),
      h("details", { class: "where" }, h("summary", {}, "Detalles técnicos"), h("div", { class: "small muted path" }, `${c.name} · ${c.command}`))));
}

async function renderApps(p) {
  p.append(intro("Muchos programas siguen funcionando aunque no los abras: se encienden con el equipo, buscan actualizaciones o se quedan escondidos. Eso gasta memoria y hace que el equipo arranque más lento.",
      "«Poner a dormir» apaga todo lo que ese programa hace a escondidas. El programa sigue instalado y funciona normal cuando lo abras tú. «Despertar» lo deja exactamente como estaba."),
    adminBanner("Para dormir algunas partes de los programas se necesita tu permiso.") || "");
  const status = h("div"), out = h("div", { class: "items" });
  p.append(h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: () => draw(true) }, "Revisar otra vez")), status, out);
  const draw = async (force) => {
    const data = await loadOverview(status, force);
    if (!data) return;
    fill(out, data.apps.map(a => {
      const all = a.components.every(c => c.protected && c.enabled);
      return h("details", { class: "item " + (a.sleeping ? "v-borrar" : "v-tuyo") }, h("summary", { class: "row", style: "grid-column:1/-1" },
        h("strong", {}, a.name), h("span", { class: "muted small" }, `hace ${a.components.length} cosa(s) a escondidas`),
        a.sleeping ? h("span", { class: "pill ok" }, "😴 dormido") : null, h("span", { class: "spacer" }),
        all ? h("span", { class: "pill bad" }, "🔒 Protegido") : a.sleeping
          ? h("button", { class: "btn", onclick: async (e) => { e.preventDefault(); const r = await guard(() => api("optimizer/wake", { name: a.name })); if (r) { toast(`${a.name} despertó: todo quedó como estaba`); draw(true); } } }, "Despertar")
          : h("button", { class: "btn primary", onclick: async (e) => { e.preventDefault(); const r = await guard(() => api("optimizer/sleep", { name: a.name })); if (r) { toast(`${a.name} está dormido. Puedes despertarlo cuando quieras.`, !!r.errors.length); showBlocked(r.protected); draw(true); } } }, "Poner a dormir")),
        h("div", { class: "items", style: "grid-column:1/-1;margin-top:8px" }, a.components.map(componentRow)));
    }));
  };
  draw(false);
}

async function renderStartup(p) {
  const status = h("div"), out = h("div", { class: "items" });
  p.append(intro("Estos programas se abren solos cada vez que enciendes el equipo. Mientras menos haya, más rápido arranca.",
    "Apagar uno no lo desinstala: solo deja de abrirse solo. Si lo necesitas, lo abres tú como siempre."), status, out);
  const data = await loadOverview(status, false);
  if (!data) return;
  fill(out, data.startup.map(componentRow));
}

async function renderProcesses(p) {
  p.append(intro("Estos son los programas que más memoria están usando ahora mismo. Si el equipo va lento, cerrar uno que no estés usando puede ayudar.",
    "«Cerrar a la fuerza» es como cerrarlo sin preguntar: perderás lo que no hayas guardado en ese programa. Los de Windows están protegidos."));
  const r = await guard(() => api("optimizer/processes"));
  if (!r) return;
  p.append(h("div", { class: "items" }, r.processes.map(x => h("div", { class: "item " + (x.protected ? "v-no" : "v-tuyo") },
    h("div", { class: "item-check" }, x.protected ? "🔒" : ""),
    h("div", { class: "item-body" },
      h("div", { class: "row" }, h("strong", {}, x.friendly), x.count > 1 ? h("span", { class: "muted small" }, `(${x.count} ventanas o partes)`) : null,
        h("span", { class: "spacer" }), h("span", { class: "num" }, `${size(x.mem)} de memoria`),
        x.protected ? null : h("button", { class: "btn danger small-btn", onclick: async () => {
          if (confirm(`¿Cerrar «${x.friendly}» a la fuerza? Perderás lo que no hayas guardado en ese programa.`)) { const k = await guard(() => api("optimizer/kill", { name: x.name })); if (k) toast(k.ok ? "Cerrado" : "No se pudo cerrar", !k.ok); }
        } }, "Cerrar a la fuerza")),
      x.protected ? protectedNote(x.protected) : null,
      h("details", { class: "where" }, h("summary", {}, "Detalles técnicos"), h("div", { class: "small muted path" }, `${x.name}.exe · ${x.path || ""}`)))))));
}

async function renderPower(p) {
  p.append(intro("Elige cómo quieres que trabaje el equipo: más rápido o gastando menos energía. Puedes cambiarlo cuando quieras."));
  const r = await guard(() => api("optimizer/power"));
  if (!r) return;
  p.append(card(null, ...r.plans.map(pl => h("label", { class: "check" }, h("input", { type: "radio", name: "plan", checked: pl.active, onchange: async () => { const x = await guard(() => api("optimizer/power-set", { guid: pl.guid })); if (x) toast(x.ok ? `Ahora usas: ${pl.name}` : x.message, !x.ok); } }),
    h("span", {}, h("strong", {}, pl.name), h("span", { class: "desc" }, pl.plain))))));
}

// ---------------------------------------------------------------- Controladores
async function renderDrivers(p) {
  const status = h("div"), updates = h("div"), inv = h("div");
  p.append(intro("Los controladores son los «traductores» entre Windows y las piezas del equipo: la pantalla, el sonido, el Wi-Fi, la impresora… Si uno está viejo o falla, esa pieza puede ir mal.",
      "Las versiones nuevas se buscan con Windows Update, el mismo sistema oficial de Windows. Antes de instalar se guarda una copia de seguridad para poder volver atrás si algo no va bien."),
    adminBanner("Para instalar controladores o guardar una copia se necesita tu permiso.") || "",
    card("¿Hay controladores nuevos?",
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: search }, "Buscar controladores nuevos"),
        h("button", { class: "btn", onclick: async () => { const r = await runJob("drivers/backup", {}, status, "Guardando una copia de tus controladores"); if (r) toast(r.ok ? "Copia guardada. Si algo falla, podrás volver a estos controladores." : "No se pudo guardar la copia", !r.ok); } }, "Guardar copia de mis controladores")),
      h("div", { class: "small muted" }, "La búsqueda puede tardar unos minutos."), status, updates), inv);
  async function search() {
    const r = await runJob("drivers/search", {}, status, "Buscando controladores nuevos (puede tardar unos minutos)");
    if (!r) return;
    if (!r.updates.length) return fill(updates, h("div", { class: "empty" }, "✓ Tus controladores están al día. No hay que hacer nada."));
    const list = h("div", { class: "items" }, r.updates.map(u => h("label", { class: "item v-borrar" }, h("div", { class: "item-check" }, h("input", { type: "checkbox", value: u.id, checked: true })),
      h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, u.cls_plain), h("span", { class: "spacer" }), h("span", { class: "num small" }, size(u.size))),
        h("div", { class: "small muted" }, `Versión nueva${u.date ? ` del ${u.date.split("-").reverse().join("/")}` : ""} · ${u.title}`)))));
    const rp = h("input", { type: "checkbox", checked: true }), bk = h("input", { type: "checkbox", checked: true });
    fill(updates, h("p", {}, `Hay ${r.updates.length} controlador(es) nuevo(s):`), list,
      h("label", { class: "check" }, rp, h("span", {}, "Crear un punto para volver atrás", h("span", { class: "desc" }, "Si después algo va mal, Windows puede volver a como estaba hoy. Recomendado."))),
      h("label", { class: "check" }, bk, h("span", {}, "Guardar copia de los controladores actuales", h("span", { class: "desc" }, "Por si quieres volver a la versión que tienes ahora."))),
      h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: async () => {
        const ids = checkedValues(list);
        if (!ids.length || !confirm(`Se instalarán ${ids.length} controlador(es). La pantalla puede parpadear o quedarse en negro un momento: es normal. ¿Seguimos?`)) return;
        const res = await runJob("drivers/install", { ids, restore: rp.checked, backup: bk.checked }, status, "Instalando controladores");
        if (res) fill(updates, card(null, res.results.map(x => h("div", {}, h("span", { class: "pill " + (x.code === 2 ? "ok" : "bad") }, x.code === 2 ? "✓ Instalado" : "No se pudo instalar"), " ", x.title)),
          res.reboot ? h("div", { class: "banner" }, "Reinicia el equipo para terminar.") : null));
      } }, "Instalar los marcados")));
  }
  const r = await runJob("drivers/inventory", {}, inv, "Revisando tus controladores");
  if (!r) return;
  const byClass = new Map();
  r.drivers.forEach(d => { if (!byClass.has(d.cls_plain)) byClass.set(d.cls_plain, []); byClass.get(d.cls_plain).push(d); });
  const old = r.drivers.filter(d => d.old);
  fill(inv,
    card(r.problems.length ? `⚠ ${r.problems.length} pieza(s) con problemas` : "✓ Todas las piezas funcionan",
      r.problems.length ? h("div", { class: "items" }, r.problems.map(x => h("div", { class: "item v-revisar" }, h("div", { class: "item-check" }, "⚠"),
        h("div", { class: "item-body" }, h("strong", {}, x.device || "Dispositivo desconocido"), h("div", {}, x.plain), h("div", { class: "advice" }, "👉 ", x.fix)))))
        : h("div", { class: "muted" }, "Windows no informa de ningún dispositivo con errores.")),
    old.length ? card(`${old.length} controlador(es) con más de ${r.old_years} años`, h("p", { class: "small muted" }, "No siempre es un problema: si esas piezas funcionan bien, no hace falta tocarlos. Si alguna falla, busca controladores nuevos arriba."),
      old.map(d => h("div", { class: "small" }, `• ${d.cls_plain}: ${d.device} (${d.date ? d.date.slice(0, 4) : "fecha desconocida"})`))) : "",
    h("details", { class: "card" }, h("summary", {}, h("strong", {}, `Ver todos tus controladores (${r.drivers.length})`)),
      h("div", { class: "scroll", style: "margin-top:10px" }, [...byClass.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([cls, items]) => h("details", { class: "group" },
        h("summary", {}, h("strong", {}, cls), ` (${items.length})`),
        items.map(d => h("div", { class: "small", style: "padding:3px 0 3px 14px" }, d.device, h("span", { class: "muted" }, ` · ${d.provider || ""} · versión ${d.version} · ${d.date || ""}`))))))));
}

// ---------------------------------------------------------------- Software
function renderSoftware(p) {
  tabs([{ title: "Programas con versión nueva", render: renderUpdates }, { title: "Programas instalados", render: renderPrograms }], p);
}

const ymd = (s) => s && /^\d{8}$/.test(s) ? `${s.slice(6, 8)}/${s.slice(4, 6)}/${s.slice(0, 4)}` : "";

async function renderUpdates(p) {
  const status = h("div"), out = h("div");
  p.append(intro("Los programas sin actualizar pueden tener fallos de seguridad o errores ya corregidos. Aquí ves cuáles tienen una versión nueva y los actualizas con un clic.",
      "Se usa el sistema oficial de Windows para instalar programas. Algunos programas pueden pedirte permiso o cerrarse un momento mientras se actualizan."),
    h("div", { class: "row" }, h("button", { class: "btn primary", onclick: check }, "Buscar versiones nuevas")), status, out);
  async function check() {
    const r = await runJob("software/check", {}, status, "Buscando versiones nuevas");
    if (!r) return;
    if (!r.updates.length) return fill(out, h("div", { class: "empty" }, "✓ Todos tus programas están al día."));
    const list = h("div", { class: "items" }, r.updates.map(u => h("label", { class: "item v-borrar" }, h("div", { class: "item-check" }, h("input", { type: "checkbox", value: u.id, checked: true })),
      h("div", { class: "item-body" }, h("strong", {}, u.name),
        h("div", { class: "small" }, "Tienes la versión ", h("span", { class: "muted" }, u.version), " → hay una nueva: ", h("strong", {}, u.available))))));
    fill(out, h("p", {}, `${r.updates.length} programa(s) tienen versión nueva:`), list,
      h("div", { class: "row", style: "margin-top:10px" }, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: async () => {
        const ids = checkedValues(list);
        if (!ids.length) return toast("Marca al menos un programa");
        if (!confirm(`Se actualizarán ${ids.length} programa(s). Guarda tu trabajo en esos programas por si se cierran. ¿Seguimos?`)) return;
        const res = await runJob("software/update", { ids }, status, "Actualizando programas");
        const names = Object.fromEntries(r.updates.map(u => [u.id, u.name]));
        if (res) fill(out, card(null, res.results.map(x => h("div", {}, h("span", { class: "pill " + (x.ok ? "ok" : "bad") }, x.ok ? "✓ Actualizado" : "No se pudo actualizar"), " ", names[x.id] || x.id))));
      } }, "Actualizar los marcados")));
  }
  check();
}

async function renderPrograms(p) {
  const status = h("div"), out = h("div");
  p.append(intro("Tus programas, ordenados por el espacio que ocupan. Si ya no usas alguno, desinstalarlo es la forma correcta de liberar ese espacio.",
    "«Desinstalar» abre el desinstalador oficial del programa, igual que desde Configuración de Windows. Lo que Windows necesita está protegido 🔒."), status, out);
  const r = await runJob("software/programs", {}, status, "Leyendo tus programas");
  if (!r) return;
  const filter = h("input", { type: "text", placeholder: "Buscar un programa…", style: "width:280px" });
  const total = r.programs.reduce((a, x) => a + (x.size || 0), 0);
  const list = h("div", { class: "items" });
  const draw = () => {
    const q = filter.value.toLowerCase();
    fill(list, r.programs.filter(x => !q || x.name.toLowerCase().includes(q) || x.publisher.toLowerCase().includes(q)).map(x => h("div", { class: "item " + (x.protected ? "v-no" : "v-tuyo") },
      h("div", { class: "item-check" }, x.protected ? "🔒" : ""),
      h("div", { class: "item-body" },
        h("div", { class: "row" }, h("strong", {}, x.name), h("span", { class: "spacer" }), h("span", { class: "num" }, x.size ? size(x.size) : "tamaño desconocido"),
          x.protected ? null : h("button", { class: "btn danger small-btn", onclick: async () => { if (confirm(`¿Desinstalar ${x.name}? Se abrirá su desinstalador; sigue sus pasos.`)) { const u = await guard(() => api("software/uninstall", { id: x.id })); if (u) toast(u.message, !u.ok); } } }, "Desinstalar")),
        h("div", { class: "small muted" }, [x.publisher && `De ${x.publisher}`, ymd(x.date) && `instalado el ${ymd(x.date)}`, x.kind === "Store" ? "de la Microsoft Store" : ""].filter(Boolean).join(" · ")),
        x.protected ? protectedNote(x.protected) : null))));
  };
  filter.addEventListener("input", draw);
  out.append(h("div", { class: "row" }, filter, h("span", { class: "spacer" }), h("span", { class: "muted" }, `${r.programs.length} programas · ${size(total)} en total`)),
    h("div", { style: "margin-top:10px" }, list));
  draw();
}

// ---------------------------------------------------------------- Recuperación
function renderRecovery(p) {
  tabs([{ title: "Papelera de reciclaje", render: renderBin }, { title: "Buscar archivos borrados hace tiempo", render: renderDeep }], p);
}

const folderOf = (path) => { const parts = path.split("\\"); parts.pop(); return parts.slice(-2).join("\\") || path; };

async function renderBin(p) {
  p.append(intro("Lo que borraste y todavía está en la Papelera. «Recuperar» lo devuelve exactamente a donde estaba."));
  const r = await guard(() => api("recovery/bin"));
  if (!r) return;
  if (!r.items.length) return p.append(h("div", { class: "empty" }, "La Papelera está vacía. Si ya la vaciaste, prueba en «Buscar archivos borrados hace tiempo»."));
  const list = h("div", { class: "items" }, r.items.map(i => h("label", { class: "item v-tuyo" }, h("div", { class: "item-check" }, h("input", { type: "checkbox", value: i.id })),
    h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, i.name), i.is_dir ? h("span", { class: "pill" }, "carpeta") : null, h("span", { class: "spacer" }), h("span", { class: "num" }, size(i.size))),
      h("div", { class: "small muted" }, `Estaba en «${folderOf(i.original)}» · borrado el ${i.deleted}`)))));
  p.append(h("div", { class: "row" }, h("strong", {}, `${r.items.length} cosa(s) en la Papelera`), h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: async () => {
    const ids = checkedValues(list);
    if (!ids.length) return toast("Marca lo que quieras recuperar");
    const x = await guard(() => api("recovery/restore", { ids }));
    if (x) { toast(`✓ ${x.restored.length} recuperado(s) en su lugar original`); if (x.errors.length) toast(x.errors[0].error, true); p.replaceChildren(); renderBin(p); }
  } }, "Recuperar los marcados")), h("div", { class: "scroll tall" }, list));
}

const STATE_TEXT = { excelente: "Se puede recuperar completo", parcial: "Se recupera solo en parte (podría salir dañado)", sobrescrito: "Ya no se puede recuperar", desconocido: "No se sabe hasta intentarlo", "vacío": "Archivo vacío", irrecuperable: "Ya no se puede recuperar" };

async function renderDeep(p) {
  const d = await guard(() => api("analyzer/drives"));
  if (!d) return;
  const ntfs = d.drives.filter(x => x.fs === "NTFS");
  const drive = h("select", {}, ntfs.map(x => h("option", { value: x.letter }, `${x.label} (${x.letter}:)`)));
  const status = h("div"), out = h("div");
  p.append(intro("Cuando borras un archivo, Windows no lo destruye al momento: solo marca su espacio como libre. Mientras no se escriba nada encima, todavía se puede rescatar.",
      "Importante: mientras más uses el equipo después de borrar, menos se puede recuperar. Los archivos rescatados se guardan en OTRO disco o memoria USB para no pisar los que quieres salvar."),
    adminBanner("Para buscar en todo el disco se necesita tu permiso.") || "",
    h("div", { class: "row" }, "¿En qué disco estaba?", drive, h("button", { class: "btn primary", disabled: !STATE.admin, onclick: scan }, "Buscar archivos borrados")), status, out);
  async function scan() {
    const r = await runJob("recovery/scan", { letter: drive.value }, status, "Buscando archivos borrados (puede tardar unos minutos)");
    if (r) showResults(r);
  }
  function showResults(summary) {
    const text = h("input", { type: "text", placeholder: "Buscar por nombre…" });
    const cat = h("select", {}, h("option", { value: "" }, "Cualquier tipo"), Object.entries(CATS).map(([k, v]) => h("option", { value: k }, v)));
    const state = h("select", {}, h("option", { value: "excelente" }, "Solo los que se recuperan completos"), h("option", { value: "parcial" }, "Los que se recuperan en parte"), h("option", { value: "" }, "Todos"));
    const others = d.drives.filter(x => x.letter !== summary.drive);
    const dest = h("select", {}, others.map(x => h("option", { value: `${x.letter}:\\Recuperados PCLimpio` }, `${x.label} (${x.letter}:)`)));
    const list = h("div");
    const pills = { excelente: "ok", parcial: "warn", sobrescrito: "bad", irrecuperable: "bad" };
    const load = async () => {
      const r = await guard(() => api("recovery/results", { text: text.value, category: cat.value, state: state.value, limit: 1500 }));
      if (!r) return;
      const items = h("div", { class: "items" }, r.files.map(f => h("label", { class: "item " + (f.state === "excelente" ? "v-borrar" : f.state === "parcial" ? "v-revisar" : "v-no") },
        h("div", { class: "item-check" }, ["excelente", "parcial", "desconocido"].includes(f.state) ? h("input", { type: "checkbox", value: String(f.id) }) : "✕"),
        h("div", { class: "item-body" }, h("div", { class: "row" }, h("strong", {}, f.name), h("span", { class: "pill " + (pills[f.state] || "") }, STATE_TEXT[f.state] || f.state), h("span", { class: "spacer" }), h("span", { class: "num" }, size(f.size))),
          h("div", { class: "small muted" }, `Estaba en «${folderOf(f.folder + "\\x")}»${f.modified ? ` · modificado el ${f.modified}` : ""}`)))));
      fill(list, h("div", { class: "small muted" }, `Mostrando ${r.files.length} de ${r.total.toLocaleString()} archivos borrados encontrados`), h("div", { class: "scroll tall" }, items),
        others.length ? h("div", { class: "row", style: "margin-top:10px" }, "Guardarlos en:", dest, h("span", { class: "spacer" }), h("button", { class: "btn primary", onclick: async () => {
          const ids = checkedValues(items);
          if (!ids.length) return toast("Marca los archivos que quieres recuperar");
          const res = await runJob("recovery/recover", { ids, dest: dest.value }, status, "Recuperando");
          if (res) { toast(`✓ ${res.recovered.length} archivo(s) recuperados en «${res.dest}»`); api("open-folder", { path: res.dest }); }
        } }, "Recuperar los marcados")) : h("div", { class: "banner" }, "Conecta una memoria USB u otro disco para guardar lo que recuperes."));
    };
    [text, cat, state].forEach(x => x.addEventListener("change", load));
    fill(out, card(`Se encontraron ${summary.total.toLocaleString()} archivos borrados`,
      h("div", { class: "row" }, Object.entries(summary.states).map(([k, v]) => h("span", { class: "pill " + (pills[k] || "") }, `${STATE_TEXT[k] || k}: ${v.toLocaleString()}`))),
      h("div", { class: "row", style: "margin:10px 0" }, text, cat, state, h("button", { class: "btn", onclick: load }, "Buscar")), list));
    load();
  }
}

// ---------------------------------------------------------------- Información del sistema
function ramVerdict(bytes) {
  const gb = bytes / 2 ** 30;
  if (gb < 7) return ["warn", "poca: puede ir lento con varios programas o pestañas abiertas"];
  if (gb < 15) return ["ok", "suficiente para oficina, estudios e Internet"];
  if (gb < 31) return ["ok", "de sobra para el día a día y juegos"];
  return ["ok", "muchísima: sirve hasta para trabajos pesados"];
}

async function renderSysinfo(p) {
  const status = h("div");
  p.append(status);
  const d = await runJob("sysinfo/collect", {}, status, "Revisando las piezas de tu equipo");
  if (!d) return;
  const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== " ").map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  const tech = (pairs) => h("details", { class: "where" }, h("summary", {}, "Detalles técnicos"), kv(pairs));
  const o = d.os || {}, s = d.system || {}, cpu = d.cpu[0] || {};
  const installed = d.memory.reduce((a, m) => a + (m.size || 0), 0) || s.ram || 0;  // la RAM instalada, no la que Windows deja usar
  const [ramCls, ramTxt] = ramVerdict(installed);
  const fecha = (v) => v ? v.replace(/^(\d{4})-(\d\d)-(\d\d)/, "$3/$2/$1") : v;
  const isVirtual = (k) => /virtual/i.test(`${k.name} ${k.bus}`);
  const realDisks = d.disks.filter(k => !isVirtual(k));
  const sysVol = d.volumes.find(v => v.letter === "C");
  const lowSpace = sysVol && sysVol.size && sysVol.free / sysVol.size < 0.1;
  const diskType = (m) => m === "SSD" ? "SSD (rápido)" : m === "HDD" ? "Disco duro tradicional (más lento)" : "Disco";
  const healthy = (hs) => hs === "Healthy";
  const line = (cls, label, text) => h("div", { class: "row" }, h("span", { class: "pill " + cls }, label), h("span", {}, text));
  p.append(card("Tu equipo en pocas palabras",
      line("info", "Windows", `${o.name || "Windows"}`),
      line("info", "Procesador", `${cpu.name || "desconocido"} · ${cpu.cores || "?"} núcleos (cuantos más, más cosas a la vez)`),
      line(ramCls, "Memoria", `${Math.round(installed / 2 ** 30)} GB: ${ramTxt}`),
      ...realDisks.map(k => line(healthy(k.health) ? "ok" : "bad", "Disco", `${diskType(k.media)} de ${size(k.size)} · salud ${healthy(k.health) ? "buena ✓" : "con problemas: haz copia de tus archivos"}`)),
      sysVol ? line(lowSpace ? "warn" : "ok", "Espacio", `${size(sysVol.free)} libres en C:${lowSpace ? " — queda poco: usa Limpieza o el Analizador de disco" : ""}`) : null,
      d.battery && d.battery.health ? line(d.battery.health < 60 ? "warn" : "ok", "Batería", `conserva el ${d.battery.health} % de su capacidad original${d.battery.health < 60 ? ": dura bastante menos que nueva" : ""}`) : null,
      h("div", { class: "row", style: "margin-top:8px" }, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: async () => { const r = await guard(() => api("sysinfo/export", { data: d })); if (r) { toast("Informe guardado. Puedes enviárselo a un técnico si lo necesitas."); api("open-folder", { path: r.path }); } } }, "Guardar informe para un técnico"))),
    h("div", { class: "grid" },
      card("Windows", kv([["Versión", o.name], ["Instalado el", fecha(o.installed)], ["Encendido desde", fecha(o.boot)], ["Nombre del equipo", o.computer], ["Tu usuario", o.user]]), tech([["Versión exacta", `${o.version} (build ${o.build})`], ["Arquitectura", o.arch]])),
      card("Equipo", kv([["Marca", s.maker], ["Modelo", s.model], ["Memoria instalada", `${Math.round(installed / 2 ** 30)} GB`], ["Memoria libre ahora", size(o.ramFree)]]), tech([["Placa base", s.board], ["BIOS", `${s.bios || ""} ${s.biosDate ? "(" + fecha(s.biosDate) + ")" : ""}`], ["Número de serie", s.serial], ["Memoria utilizable", size(s.ram)]])),
      ...d.cpu.map(c => card("Procesador (el cerebro del equipo)", kv([["Modelo", c.name], ["Núcleos", `${c.cores} (trabajan a la vez)`], ["Uso ahora", c.load != null ? c.load + " %" : ""]]),
        tech([["Hilos", c.threads], ["Frecuencia máxima", `${c.mhz} MHz`], ["Caché L2 / L3", `${c.l2} KB / ${c.l3} KB`], ["Zócalo", c.socket]]))),
      card("Memoria RAM (para tener programas abiertos)", kv([["Total", `${Math.round(installed / 2 ** 30)} GB en ${d.memory.length} pieza(s)`]]),
        tech(d.memory.map(m => [m.slot, `${size(m.size)} · ${m.speed ? m.speed + " MT/s" : ""} · ${m.maker || ""} ${m.part || ""}`]))),
      ...d.gpu.map(g => card("Tarjeta gráfica (imagen)", kv([["Modelo", g.name], ["Pantalla", g.res]]), tech([["Controlador", g.driver], ["Fecha del controlador", fecha(g.driverDate)]]))),
      ...realDisks.map(k => card("Disco (donde se guardan tus archivos)", kv([["Modelo", k.name], ["Tipo", diskType(k.media)], ["Capacidad", size(k.size)],
        ["Salud", h("span", { class: "pill " + (healthy(k.health) ? "ok" : "bad") }, healthy(k.health) ? "Buena" : "Con problemas")], ["Temperatura", k.temperature ? k.temperature + " °C" : ""],
        ["Desgaste", k.wear != null ? `${k.wear} % (0 % = como nuevo)` : ""]]), tech([["Conexión", k.bus], ["Horas encendido", k.hours], ["Firmware", k.firmware], ["Serie", k.serial]]))),
      d.volumes.length ? card("Espacio en tus discos", d.volumes.map(v => kv([[`${v.letter}: ${v.label || ""}`, `${size(v.free)} libres de ${size(v.size)}`]]))) : "",
      d.monitors.length ? card("Pantallas", d.monitors.map(m => kv([[m.maker, m.model]]))) : "",
      d.network.length ? card("Internet y red", d.network.map(n => h("div", {}, kv([["Conexión", n.desc], ["Velocidad", n.speed]]), tech([["Dirección IP", n.ip], ["Dirección MAC", n.mac]])))) : "",
      d.audio.length ? card("Sonido", d.audio.map(a => h("div", {}, a))) : "",
      d.battery && d.battery.charge != null ? card("Batería", kv([["Carga ahora", d.battery.charge + " %"], ["Salud", d.battery.health ? d.battery.health + " % de la capacidad original" : ""]])) : ""));
}

// ------------------------------------------------------------------ arranque
async function init() {
  const nav = document.getElementById("nav");
  for (const pg of PAGES) {
    if (pg.sep) { nav.append(h("div", { class: "sep" }, pg.sep)); continue; }
    nav.append(h("button", { "data-id": pg.id, onclick: () => go(pg.id) }, h("span", { class: "ico" }, pg.ico), pg.title));
  }
  document.getElementById("open-logs").onclick = () => go("activity");
  const st = await guard(() => api("status"));
  if (!st) { document.getElementById("page").append(h("div", { class: "banner" }, "No se pudo conectar con el servicio local. Cierra esta ventana y vuelve a abrir PCLimpio.")); return; }
  STATE = st;
  const a = document.getElementById("admin-state");
  a.textContent = st.admin ? "Con permiso de cambios" : "Modo normal";
  fill(document.getElementById("about"), `PCLimpio v${st.version}`, h("br"), `© ${st.copyright.replace("Copyright (C) ", "")}`, h("br"),
    `Software libre · ${st.license.replace("-or-later", "")}`, st.repo ? [h("br"), h("span", { class: "path" }, st.repo)] : null);
  a.className = "pill" + (st.admin ? " ok" : "");
  setInterval(() => api("heartbeat").catch(() => {}), 15000);
  go(sessionStorage.getItem("page") || "home");
}
init();
