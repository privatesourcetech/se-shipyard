/* SE Shipyard single-page UI. Talks to the JSON API under /api. */
"use strict";

/* ---------- state ---------- */
const state = {
  view: "home",
  servers: null,      // summaries from /api/servers
  detail: {},         // name -> full detail (loaded when a server is expanded)
  defaults: null,
  mods: null,         // library + used mods
  steam: { set: false, source: null },
  ui: loadLocal("ui", { theme: "dark" }),
  open: {}, tab: {},
  searchQ: "", searchRes: null, searching: false, searchErr: null,
  replacingKey: false,
  loadError: null,
};

function loadLocal(k, d) { try { return Object.assign({}, d, JSON.parse(localStorage.getItem("shipyard-" + k) || "{}")); } catch (e) { return d; } }
function saveLocal(k, v) { try { localStorage.setItem("shipyard-" + k, JSON.stringify(v)); } catch (e) { /* ignore */ } }

/* ---------- helpers ---------- */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const q = (v) => esc(JSON.stringify(v));            // safe JS string literal inside an HTML attribute
const sid = (n) => "srv-" + String(n).replace(/[^A-Za-z0-9_-]/g, "_");

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.style.borderColor = isErr ? "var(--bad)" : "var(--accent)";
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), isErr ? 5000 : 2400);
}

async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch("/api" + path, opts); }
  catch (e) { throw new Error("Can't reach the Shipyard backend."); }
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((m) => (m.loc ? m.loc[m.loc.length - 1] + ": " : "") + (m.msg || "").replace(/^Value error, /, "")).join("; ");
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return data;
}
async function attempt(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, true); return undefined; }
}

function srv(name) { return (state.servers || []).find((s) => s.name === name); }
function lines(raw) { return String(raw || "").split(/[\n,]+/).map((x) => x.trim()).filter(Boolean); }
function pill(s) { return `<span class="pill ${esc(s)}">${s === "exited" ? "stopped" : s === "not_found" ? "missing" : esc(s)}</span>`; }
function thumb(m) {
  const letter = esc((m.name || "?")[0]);
  const inner = m.preview_url ? `<img src="${esc(m.preview_url)}" alt="" loading="lazy" onerror="this.remove()">` : letter;
  return `<div class="thumb" style="background:#475569">${inner}</div>`;
}
function applyTheme() {
  let t = state.ui.theme;
  if (t === "system") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
}

/* ---------- data loading ---------- */
async function loadServers() {
  state.servers = await api("/servers");
  state.loadError = null;
}
async function loadDetail(name) {
  const d = await api("/servers/" + encodeURIComponent(name));
  state.detail[name] = d;
  return d;
}
async function loadDefaults() { state.defaults = await api("/defaults"); }
async function loadMods() { state.mods = await api("/mods"); }
async function loadSteam() { state.steam = await api("/steam-key"); }

async function enter(view) {
  state.view = view;
  stopLog();
  render();
  try {
    if (view === "home" || view === "servers") await loadServers();
    if (view === "servers") for (const n of Object.keys(state.open)) if (state.open[n] && !state.detail[n]) await loadDetail(n).catch(() => {});
    if (view === "defaults" || view === "servers") await loadDefaults();
    if (view === "mods") { await Promise.all([loadMods(), loadSteam()]); }
    if (view === "ui") await loadSteam();
    state.loadError = null;
  } catch (e) { state.loadError = e.message; }
  render();
  if (view === "servers") startLogIfNeeded();
}
function go(v) { enter(v); }

/* ---------- navigation ---------- */
const NAV = [["home", "⌂", "Home"], ["mods", "▦", "Mods"], ["defaults", "⚙", "Default settings"], ["ui", "◐", "UI settings"], ["servers", "☰", "Servers"]];
function renderNav() {
  $("#nav").innerHTML = NAV.map(([id, ic, l]) => `<button class="${state.view === id ? "active" : ""}" onclick="go('${id}')">${ic}<span class="t">${l}</span></button>`).join("");
}

/* ---------- views ---------- */
function loadingOrError(ready) {
  if (state.loadError) return `<div class="empty err">${esc(state.loadError)}<br><br><button onclick="enter(state.view)">Retry</button></div>`;
  if (!ready) return `<div class="loading">Loading…</div>`;
  return null;
}

function viewHome() {
  const early = loadingOrError(state.servers); if (early) return `<h1>Home</h1>${early}`;
  const running = state.servers.filter((s) => s.status === "running");
  const others = state.servers.filter((s) => s.status !== "running");
  return `<div class="page-head"><div><h1>Home</h1><p class="sub">${running.length} of ${state.servers.length} servers running</p></div></div>
  ${state.servers.length === 0 ? `<div class="empty">No servers registered yet. <button class="primary" onclick="go('servers');openAdd()">Add one</button></div>` : ""}
  ${running.length ? `<div class="grid">${running.map(homeCard).join("")}</div>` : state.servers.length ? `<div class="empty">No servers are running.</div>` : ""}
  ${others.length ? `<div class="section-title">Stopped</div><div class="grid">${others.map(homeCard).join("")}</div>` : ""}`;
}
function homeCard(s) {
  const st = s.settings;
  const healthBadge = s.health && s.health !== "healthy" ? ` <span class="chip" title="Container health">${esc(s.health)}</span>` : "";
  return `<div class="card" data-card="${esc(s.name)}">
    <h3>${esc(s.name)} <span>${pill(s.status)}</span></h3>
    <div class="meta">${st ? esc(st.game_mode) + " · port " + st.server_port + " · " : ""}up ${esc(s.uptime)}${healthBadge}</div>
    ${s.error ? `<div class="err" style="margin-bottom:10px">${esc(s.error)}</div>` : ""}
    <div class="stats">
      <div class="stat"><b>${st ? st.max_players : "—"}</b><span>max players</span></div>
      <div class="stat"><b>${s.mods.length}</b><span>mods</span></div>
      <div class="stat"><b>${s.cpu}%</b><span>CPU<div class="bar"><i style="width:${Math.min(100, s.cpu)}%"></i></div></span></div>
      <div class="stat"><b>${s.mem_gb} GB</b><span>memory<div class="bar"><i style="width:${Math.min(100, s.mem_gb / 12 * 100)}%"></i></div></span></div>
    </div>
    ${s.pending_restart ? `<div class="banner" style="padding:6px 10px"><span>Restart needed</span></div>` : ""}
    <div class="row">${controls(s)}<button onclick="openServer(${q(s.name)})">Manage →</button></div></div>`;
}
function controls(s) {
  return s.status === "running"
    ? `<button onclick="act(${q(s.name)},'restart')">Restart</button><button class="danger" onclick="act(${q(s.name)},'stop')">Stop</button>`
    : `<button class="primary" onclick="act(${q(s.name)},'start')">Start</button>`;
}

/* -- mods -- */
function wsLink(m) { return `<a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">${esc(m.name)}</a>`; }
function viewMods() {
  const early = loadingOrError(state.mods); if (early) return `<h1>Mods</h1>${early}`;
  const mods = state.mods;
  const searchCard = !state.steam.set
    ? `<div class="row" style="justify-content:space-between"><div><b>Workshop search is off</b><div class="meta" style="color:var(--muted)">Add a free Steam Web API key to search for mods by name.</div></div><button class="primary" onclick="go('ui')">Set up Steam search →</button></div>`
    : `<form class="row" onsubmit="searchMods(event)" style="flex-wrap:nowrap">
        <input id="mod-q" value="${esc(state.searchQ)}" placeholder="Search the Steam Workshop, e.g. Ship Speed Increase" style="flex:1">
        <button class="primary" type="submit">${state.searching ? "Searching…" : "Search"}</button>
        ${state.searchRes ? `<button type="button" onclick="clearSearch()">Clear</button>` : ""}
      </form>
      ${state.searchErr ? `<div class="err" style="margin-top:10px">${esc(state.searchErr)}</div>` : ""}
      ${state.searchRes ? searchResults() : ""}`;
  const serversForGroups = state.servers || [];
  return `<div class="page-head"><div><h1>Mods</h1><p class="sub">${mods.length} mods in your list. Names and descriptions come from the Steam Workshop.</p></div></div>
  <div class="card" style="margin-bottom:22px">${searchCard}</div>
  <div class="card" style="padding:0"><table><thead><tr><th>Mod</th><th>Description</th><th>Used by</th><th></th></tr></thead><tbody>
  ${mods.map((m) => `<tr>
    <td><div class="mod-row">${thumb(m)}<div><div class="mod-title">${wsLink(m)}</div><div class="mod-desc">${esc(m.id)}</div></div></div></td>
    <td class="mod-desc">${esc(m.description)}</td>
    <td>${m.used_by.length ? m.used_by.map((n) => `<span class="chip">${esc(n)}</span>`).join("") : `<span class="chip" style="opacity:.6">none</span>`}</td>
    <td>${m.used_by.length ? "" : `<button class="danger" onclick="dropFromLibrary(${q(m.id)})">Remove</button>`}</td></tr>`).join("") || `<tr><td colspan="4" class="mod-desc">No mods yet. Search above or add one to a server.</td></tr>`}
  </tbody></table></div>
  <div class="section-title">Mod groups by server</div>
  <div class="grid">${serversForGroups.map((s) => `<div class="card"><h3>${esc(s.name)} <span class="chip">${s.mods.length}</span></h3>
    <div class="meta">${pill(s.status)}</div>
    ${s.mods.length ? s.mods.map((id) => { const m = mods.find((x) => x.id === id); return `<div>${esc(m ? m.name : id)}</div>`; }).join("") : `<div class="meta">No mods</div>`}
    <div class="row" style="margin-top:12px"><button onclick="openServer(${q(s.name)},'mods')">Edit mods</button></div></div>`).join("")}</div>`;
}
function searchResults() {
  const have = new Set((state.mods || []).map((m) => m.id));
  const r = state.searchRes;
  if (!r.length) return `<div class="empty" style="margin-top:14px">No Workshop results for “${esc(state.searchQ)}”.</div>`;
  return `<div class="section-title">${r.length} results</div>` + r.map((m) => `<div class="list-row">
    ${thumb(m)}
    <div style="flex:1"><div class="mod-title">${esc(m.name)}</div><div class="mod-desc">${esc(m.description)}</div></div>
    <a href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">View on Steam ↗</a>
    <button ${have.has(m.id) ? "disabled" : 'class="primary"'} onclick="addToLibrary(${q(m.id)})">${have.has(m.id) ? "In list" : "Add to list"}</button></div>`).join("");
}
async function searchMods(e) {
  e.preventDefault();
  const text = $("#mod-q").value.trim(); state.searchQ = text;
  if (text.length < 2) { toast("Type at least 2 characters", true); return; }
  state.searching = true; state.searchErr = null; render();
  try { state.searchRes = await api("/mods/search?q=" + encodeURIComponent(text)); }
  catch (err) { state.searchErr = err.message; state.searchRes = null; }
  state.searching = false; render();
}
function clearSearch() { state.searchQ = ""; state.searchRes = null; state.searchErr = null; render(); }
async function addToLibrary(id) {
  if (await attempt(() => api("/mods/library", "POST", { id }), "Added to your mod list") !== undefined) { await loadMods(); render(); }
}
async function dropFromLibrary(id) {
  if (await attempt(() => api("/mods/library/" + id, "DELETE")) !== undefined) { await loadMods(); render(); }
}

/* -- default settings -- */
function viewDefaults() {
  const early = loadingOrError(state.defaults); if (early) return `<h1>Default settings</h1>${early}`;
  const d = state.defaults;
  return `<div class="page-head"><div><h1>Default settings</h1><p class="sub">Build a template once, then use “Apply default settings” on any server.</p></div></div>
  <div class="card" style="max-width:860px"><form onsubmit="saveDefaults(event)">
    <div class="two">
      <label>Game mode<select name="game_mode"><option ${d.game_mode === "Survival" ? "selected" : ""}>Survival</option><option ${d.game_mode === "Creative" ? "selected" : ""}>Creative</option></select></label>
      <label>Server password ${d.password_set ? "(set — leave blank to keep)" : "(blank = none)"}<input name="password" type="password" autocomplete="new-password"></label>
      <label>Total PCU<input name="total_pcu" type="number" min="0" value="${d.total_pcu}"></label>
      <label>Pirate PCU<input name="pirate_pcu" type="number" min="0" value="${d.pirate_pcu}"></label>
      <label>Max players<input name="max_players" type="number" min="1" value="${d.max_players}"></label>
      <label>Max backup saves<input name="max_backup_saves" type="number" min="0" value="${d.max_backup_saves}"></label>
      <label>Backup interval (minutes)<input name="backup_interval" type="number" min="1" value="${d.backup_interval}"></label>
    </div>
    <div class="three">
      <label>Administrators (SteamIDs)<textarea name="administrators" rows="3">${esc(d.administrators.join("\n"))}</textarea></label>
      <label>Banned<textarea name="banned" rows="3">${esc(d.banned.join("\n"))}</textarea></label>
      <label>Reserved<textarea name="reserved" rows="3">${esc(d.reserved.join("\n"))}</textarea></label>
    </div>
    <div class="row"><button class="primary" type="submit">Save defaults</button>
      ${d.password_set ? `<button type="button" class="danger" onclick="clearDefaultPassword()">Clear default password</button>` : ""}
      <button type="button" onclick="resetDefaults()">Reset to factory</button></div>
  </form></div>`;
}
function formToSettings(f) {
  const num = (k) => Number(f.get(k));
  return {
    game_mode: f.get("game_mode"), total_pcu: num("total_pcu"), pirate_pcu: num("pirate_pcu"), max_players: num("max_players"),
    max_backup_saves: num("max_backup_saves"), backup_interval: num("backup_interval"),
    administrators: lines(f.get("administrators")), banned: lines(f.get("banned")), reserved: lines(f.get("reserved")),
  };
}
async function saveDefaults(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = formToSettings(f);
  const pw = f.get("password");
  if (pw) body.password = pw;   // omitted = keep existing
  const r = await attempt(() => api("/defaults", "PUT", body), "Default settings saved");
  if (r) { state.defaults = r; render(); }
}
async function clearDefaultPassword() {
  const body = { ...state.defaults, password: "" };
  const r = await attempt(() => api("/defaults", "PUT", body), "Default password cleared");
  if (r) { state.defaults = r; render(); }
}
async function resetDefaults() {
  if (!confirm("Reset all default settings to factory values?")) return;
  const r = await attempt(() => api("/defaults", "DELETE"), "Defaults reset");
  if (r) { state.defaults = r; render(); }
}

/* -- UI settings -- */
function viewUI() {
  const opt = (id, label, cols) => `<div class="theme-opt ${state.ui.theme === id ? "sel" : ""}" onclick="setTheme('${id}')">
    <div class="swatch">${cols.map((c) => `<i style="background:${c}"></i>`).join("")}</div><b>${label}</b></div>`;
  return `<div class="page-head"><div><h1>UI settings</h1><p class="sub">Appearance preferences are stored in this browser.</p></div></div>
  <div class="section-title" style="margin-top:0">Theme</div>
  <div class="themes">
    ${opt("light", "Light", ["#f4f6f9", "#ffffff", "#2f6fed", "#1b2330"])}
    ${opt("dark", "Dark", ["#0f1319", "#171d26", "#4c8dff", "#e6ebf3"])}
    ${opt("system", "Match system", ["#f4f6f9", "#0f1319", "#2f6fed", "#4c8dff"])}
  </div>
  <div class="section-title">Steam Workshop search</div>
  <div class="card" style="max-width:620px">${steamCard()}</div>
  <div class="section-title">Coming later</div>
  <div class="card soon" style="max-width:520px">
    <label>Home page layout<select disabled><option>Cards</option><option>List</option></select></label>
    <label>Density<select disabled><option>Comfortable</option></select></label>
    <label>Accent color<select disabled><option>Blue</option></select></label>
  </div>`;
}
function setTheme(t) { state.ui.theme = t; saveLocal("ui", state.ui); applyTheme(); render(); }
function steamCard() {
  const st = state.steam;
  if (st.set && !state.replacingKey) {
    return `<div class="row" style="justify-content:space-between"><div><b style="color:var(--ok)">Key set ✓</b>
      <div class="meta" style="color:var(--muted)">${st.source === "env" ? "Provided by the STEAM_API_KEY environment variable." : "Stored on Shipyard's data volume. It is never shown again."}</div></div>
      <div class="row"><button onclick="testKey()">Test key</button><button onclick="state.replacingKey=true;render()">Replace</button>${st.source === "ui" ? `<button class="danger" onclick="removeKey()">Remove</button>` : ""}</div></div>`;
  }
  return `<form onsubmit="saveKey(event)">
    <label>Steam Web API key<input id="steam-key" type="password" required autocomplete="off" placeholder="32-character key" pattern="[A-Fa-f0-9]{32}" title="32 hex characters"></label>
    <p class="meta" style="color:var(--muted);margin-top:-4px">Get a free key at <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener noreferrer">steamcommunity.com/dev/apikey</a>. It is only used to search the Workshop.</p>
    <div class="row"><button class="primary" type="submit">Save key</button>${st.set ? `<button type="button" onclick="state.replacingKey=false;render()">Cancel</button>` : ""}</div></form>`;
}
async function saveKey(e) {
  e.preventDefault();
  const r = await attempt(() => api("/steam-key", "PUT", { key: $("#steam-key").value }), "Steam key saved");
  if (r) { state.steam = r; state.replacingKey = false; render(); }
}
async function removeKey() {
  if (!confirm("Remove the Steam API key? Workshop search will stop working.")) return;
  const r = await attempt(() => api("/steam-key", "DELETE"), "Key removed");
  if (r) { state.steam = r; render(); }
}
async function testKey() { toast("Testing…"); await attempt(() => api("/steam-key/test", "POST"), "Key works ✓"); }

/* -- servers -- */
function viewServers() {
  const early = loadingOrError(state.servers); if (early) return `<h1>Servers</h1>${early}`;
  return `<div class="page-head"><div><h1>Servers</h1><p class="sub">Click a server to expand its settings, mods, log and backups.</p></div>
    <button class="primary" onclick="openAdd()">+ Add server</button></div>
  ${state.servers.map(serverRow).join("") || `<div class="empty">No servers registered.</div>`}`;
}
function serverInfoLine(s) {
  const st = s.settings;
  return st ? `${esc(st.game_mode)} · max ${st.max_players} players · ${s.mods.length} mods · port ${st.server_port}` : esc(s.error || "");
}
function headInner(s, open) {
  return `<span class="caret">▶</span><span class="name">${esc(s.name)}</span>${pill(s.status)}
    <span class="info">${serverInfoLine(s)}</span><span class="row" onclick="event.stopPropagation()">${controls(s)}</span>`;
}
function serverRow(s) {
  const open = !!state.open[s.name], tab = state.tab[s.name] || "settings";
  const d = state.detail[s.name];
  return `<div class="srv ${open ? "open" : ""}" id="${sid(s.name)}">
    <div class="srv-head" onclick="toggle(${q(s.name)})">${headInner(s, open)}</div>
    ${open ? `<div class="srv-body">
      <div class="tabs">${["settings", "mods", "log", "backups"].map((t) => `<button class="${tab === t ? "active" : ""}" onclick="setTab(${q(s.name)},'${t}')">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>
      <div id="${sid(s.name)}-banner">${bannerHtml(s)}</div>
      ${!d ? `<div class="loading">Loading…</div>` : tab === "settings" ? tabSettings(s, d) : tab === "mods" ? tabMods(s, d) : tab === "log" ? tabLog(s) : tabBackups(s, d)}
    </div>` : ""}</div>`;
}
function bannerHtml(s) {
  return s.pending_restart ? `<div class="banner"><span>Changes saved. Restart this server for them to take effect.</span><button onclick="act(${q(s.name)},'restart')">Restart now</button></div>` : "";
}
function tabSettings(s, d) {
  const x = d.settings;
  if (!x) return `<div class="err">${esc(d.error || "Settings unavailable")}</div>`;
  const defaultsPw = state.defaults && state.defaults.password_set;
  return `<form id="${sid(s.name)}-form" onsubmit="saveSettings(event,${q(s.name)})">
    <div class="row" style="margin-bottom:12px"><button type="button" onclick="applyDefaults(${q(s.name)})">⬇ Apply default settings</button>
      <span class="meta" style="color:var(--muted)">Fills the fields below from your defaults. Nothing is saved until you press Save.</span></div>
    <div class="three">
      <label>Server name<input name="server_name" value="${esc(x.server_name)}"></label>
      <label>Game mode<select name="game_mode"><option ${x.game_mode === "Survival" ? "selected" : ""}>Survival</option><option ${x.game_mode === "Creative" ? "selected" : ""}>Creative</option></select></label>
      <label>Max players<input type="number" min="1" name="max_players" value="${x.max_players}"></label>
      <label>Total PCU<input type="number" min="0" name="total_pcu" value="${x.total_pcu}"></label>
      <label>Pirate PCU<input type="number" min="0" name="pirate_pcu" value="${x.pirate_pcu}"></label>
      <label>Max backup saves<input type="number" min="0" name="max_backup_saves" value="${x.max_backup_saves}"></label>
      <label>Backup interval (min)<input type="number" min="1" name="backup_interval" value="${x.backup_interval}"></label>
      <label>Password ${x.has_password ? "(currently set)" : "(none)"}<input type="password" name="password" placeholder="leave blank to keep" autocomplete="new-password"></label>
      <div style="align-self:end;margin-bottom:10px" class="row">
        <button type="button" class="danger" ${x.has_password ? "" : "disabled"} onclick="clearPw(${q(s.name)})">Clear password</button>
      </div>
    </div>
    ${defaultsPw ? `<label class="chk"><input type="checkbox" name="use_default_password"> Use my default password (applied on save)</label>` : ""}
    <div class="three">
      <label>Administrators (SteamIDs)<textarea name="administrators" rows="3">${esc(x.administrators.join("\n"))}</textarea></label>
      <label>Banned<textarea name="banned" rows="3">${esc(x.banned.join("\n"))}</textarea></label>
      <label>Reserved<textarea name="reserved" rows="3">${esc(x.reserved.join("\n"))}</textarea></label>
    </div>
    <button class="primary" type="submit">Save settings</button>
  </form>`;
}
function tabMods(s, d) {
  const inUse = new Set(d.mods.map((m) => m.id));
  const suggestions = (state.mods || []).filter((m) => !inUse.has(m.id));
  return `${d.mods.length ? d.mods.map((m) => `<div class="list-row">${thumb(m)}
    <div style="flex:1"><div class="mod-title">${wsLink(m)}</div><div class="mod-desc">${esc(m.description)}</div></div>
    <button class="danger" onclick="removeMod(${q(s.name)},${q(m.id)},${q(m.name)})">Remove</button></div>`).join("") : `<div class="empty">No mods on this server.</div>`}
  <div class="row" style="margin-top:14px"><input id="${sid(s.name)}-newmod" list="${sid(s.name)}-lib" placeholder="Workshop ID, or pick from your mod list" style="max-width:340px">
    <datalist id="${sid(s.name)}-lib">${suggestions.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join("")}</datalist>
    <button onclick="addMod(${q(s.name)})">Add mod</button></div>`;
}
function tabLog(s) {
  if (s.status !== "running") return `<div class="empty">Server isn't running — no live log.</div>`;
  return `<div class="row" style="margin-bottom:8px"><label class="chk" style="margin:0"><input type="checkbox" id="log-follow" checked> Follow</label>
    <select id="log-filter" style="width:auto" onchange="renderLogLines()"><option value="all">All</option><option value="joins">Joins only</option><option value="noautosave">Hide autosaves</option></select></div>
    <div class="log" id="log-box">Loading…</div>`;
}
function tabBackups(s, d) {
  return `<div class="row" style="margin-bottom:10px"><button class="primary" onclick="backupNow(${q(s.name)})">Back up now</button>
    <span class="meta" style="color:var(--muted)">Copies the world as it is on disk. Autosave backups are safer while players are online.</span></div>
  ${d.backups.map((b) => `<div class="list-row"><span style="flex:1">${esc(b.name)} <span class="meta" style="color:var(--muted)">(${esc(b.modified)})</span></span>
    <button class="danger" onclick="restoreBackup(${q(s.name)},${q(b.name)})">Restore</button></div>`).join("") || `<div class="empty">No backups found.</div>`}`;
}

/* ---------- server actions ---------- */
async function toggle(n) {
  state.open[n] = !state.open[n];
  stopLog(); render();
  if (state.open[n] && !state.detail[n]) { await attempt(() => loadDetail(n)); render(); }
  startLogIfNeeded();
}
async function setTab(n, t) {
  state.tab[n] = t; stopLog(); render();
  if (t === "mods" && !state.mods) { await attempt(loadMods); render(); }
  startLogIfNeeded();
}
async function openServer(n, tab) {
  state.open[n] = true; if (tab) state.tab[n] = tab;
  await enter("servers");
  if (!state.detail[n]) { await attempt(() => loadDetail(n)); render(); }
  if (tab === "mods" && !state.mods) { await attempt(loadMods); render(); }
  startLogIfNeeded();
  setTimeout(() => { const el = document.getElementById(sid(n)); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }, 30);
}
async function refreshAll(n) {
  await loadServers();
  if (n && state.open[n]) await loadDetail(n);
  render();
}
async function act(n, a) {
  if (a === "stop" && !confirm(`Stop ${n}? Players will be disconnected.`)) return;
  if (a === "restart" && !confirm(`Restart ${n}? Players will be disconnected.`)) return;
  const ok = await attempt(() => api(`/servers/${encodeURIComponent(n)}/${a}`, "POST"), `${n}: ${a} requested`);
  if (ok === undefined) return;
  await attempt(() => refreshAll(n));
}
async function saveSettings(e, n) {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { ...formToSettings(f), server_name: f.get("server_name"), use_default_password: f.get("use_default_password") === "on" };
  const pw = f.get("password"); if (pw) body.password = pw;
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/settings`, "PUT", body), "Settings saved");
  if (r) await refreshAll(n);
}
async function clearPw(n) {
  if (!confirm("Clear the server password?")) return;
  const f = document.getElementById(sid(n) + "-form");
  const body = { ...formToSettings(new FormData(f)), server_name: new FormData(f).get("server_name"), clear_password: true };
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/settings`, "PUT", body), "Password cleared");
  if (r) await refreshAll(n);
}
function applyDefaults(n) {
  const d = state.defaults, form = document.getElementById(sid(n) + "-form");
  if (!d || !form) return;
  const set = (name, val) => { const el = form.elements[name]; if (el && String(el.value) !== String(val)) { el.value = val; el.classList.add("changed"); } };
  ["game_mode", "total_pcu", "pirate_pcu", "max_players", "max_backup_saves", "backup_interval"].forEach((k) => set(k, d[k]));
  ["administrators", "banned", "reserved"].forEach((k) => set(k, d[k].join("\n")));
  if (d.password_set && form.elements.use_default_password) { form.elements.use_default_password.checked = true; }
  toast("Defaults applied — review and press Save");
}
async function addMod(n) {
  const el = document.getElementById(sid(n) + "-newmod"), id = el.value.trim();
  if (!/^\d+$/.test(id)) { toast("Workshop ID must be numeric", true); return; }
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/mods`, "POST", { id }), "Mod added");
  if (r) { await loadMods().catch(() => {}); await refreshAll(n); }
}
async function removeMod(n, id, name) {
  if (!confirm(`Remove ${name} from ${n}?`)) return;
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/mods/${id}`, "DELETE"), "Mod removed");
  if (r) { await loadMods().catch(() => {}); await refreshAll(n); }
}
async function backupNow(n) {
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/backups`, "POST"), "Backup created");
  if (r) await refreshAll(n);
}
async function restoreBackup(n, b) {
  if (!confirm(`Restore ${b}?\n\nThis stops the server, overwrites the live world with this backup, then starts it again.`)) return;
  toast("Restoring…");
  const r = await attempt(() => api(`/servers/${encodeURIComponent(n)}/backups/${encodeURIComponent(b)}/restore`, "POST"), "Restore complete");
  if (r) await refreshAll(n);
}

/* ---------- add server modal ---------- */
function openAdd() {
  $("#modal").innerHTML = `<h2>Add server</h2>
  <form onsubmit="addServer(event)">
    <div class="two">
      <label>Name<input name="name" required placeholder="Plateau"></label>
      <label>Container name<input name="container_name" required placeholder="se-plateau"></label>
      <label>Dataset mount<input name="dataset_mount" required placeholder="/mnt/instances/plateau"></label>
      <label>Instance dir (INSTANCE_NAME)<input name="instance_dir" required placeholder="Plateau"></label>
      <label>World folder<input name="world_folder" required placeholder="Plateau"></label>
      <label>Backup mount<input name="backup_mount" required placeholder="/mnt/backups/plateau"></label>
    </div>
    <label class="chk"><input type="checkbox" name="use_defaults" checked> Apply my default settings to this server</label>
    <p class="meta" style="color:var(--muted)">The dataset and backup folders must already be bind-mounted into Shipyard's compose file.</p>
    <div class="err" id="add-err" style="margin-bottom:8px"></div>
    <div class="row" style="justify-content:flex-end"><button type="button" onclick="closeModal()">Cancel</button><button class="primary" type="submit">Add server</button></div>
  </form>`;
  $("#modal-bg").classList.add("show");
}
function closeModal() { $("#modal-bg").classList.remove("show"); }
async function addServer(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = Object.fromEntries(["name", "container_name", "dataset_mount", "instance_dir", "world_folder", "backup_mount"].map((k) => [k, String(f.get(k)).trim()]));
  body.use_defaults = f.get("use_defaults") === "on";
  try { await api("/servers", "POST", body); }
  catch (err) { $("#add-err").textContent = err.message; return; }
  closeModal(); state.open[body.name] = true; toast("Server added");
  await enter("servers");
}

/* ---------- live log ---------- */
let logTimer = null, logData = [];
function stopLog() { clearInterval(logTimer); logTimer = null; }
function startLogIfNeeded() {
  stopLog();
  if (state.view !== "servers") return;
  const n = Object.keys(state.open).find((k) => state.open[k] && (state.tab[k] || "settings") === "log");
  const s = n && srv(n);
  if (!s || s.status !== "running") return;
  const tick = async () => {
    try { const r = await api(`/servers/${encodeURIComponent(n)}/log?tail=300`); logData = r.lines; renderLogLines(); } catch (e) { /* keep last */ }
  };
  tick(); logTimer = setInterval(tick, 3000);
}
function renderLogLines() {
  const box = $("#log-box"); if (!box) return;
  const filter = $("#log-filter") ? $("#log-filter").value : "all";
  const rows = logData.filter((l) => filter === "all" || (filter === "joins" ? ["join_attempt", "world_loaded"].includes(l.category) : l.category !== "autosave"));
  const cls = { join_attempt: "ev-join", world_loaded: "ev-join", autosave: "ev-save" };
  box.innerHTML = rows.map((l) => `<span class="${cls[l.category] || (/error|exception|fail/i.test(l.text) ? "ev-err" : /warn/i.test(l.text) ? "ev-warn" : "")}">${esc(l.text)}</span>`).join("\n") || "No matching log lines.";
  if ($("#log-follow") && $("#log-follow").checked) box.scrollTop = box.scrollHeight;
}

/* ---------- background status refresh (never re-renders forms) ---------- */
async function pollStatus() {
  if (document.hidden || !["home", "servers"].includes(state.view)) return;
  try { await loadServers(); } catch (e) { return; }
  if (state.view === "home") {
    // Home has no forms, so a full render is safe.
    render();
  } else {
    for (const s of state.servers) {
      const el = document.getElementById(sid(s.name)); if (!el) continue;
      const head = el.querySelector(".srv-head"); if (head) head.innerHTML = headInner(s, !!state.open[s.name]);
      const ban = document.getElementById(sid(s.name) + "-banner"); if (ban) ban.innerHTML = bannerHtml(s);
    }
  }
}
setInterval(pollStatus, 5000);

/* ---------- render ---------- */
function render() {
  renderNav();
  const scroll = window.scrollY;
  $("#main").innerHTML = { home: viewHome, mods: viewMods, defaults: viewDefaults, ui: viewUI, servers: viewServers }[state.view]();
  window.scrollTo(0, scroll);
  $("#foot").textContent = state.servers ? `${state.servers.length} server${state.servers.length === 1 ? "" : "s"} registered` : "";
}

$("#modal-bg").addEventListener("click", (e) => { if (e.target.id === "modal-bg") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
applyTheme();
enter("home");
