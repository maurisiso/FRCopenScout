/*
 * Offline-first scouting form.
 *
 * 1. The page embeds the form definition + match schedule as JSON (#scout-data).
 * 2. When a scout taps "Save", the entry goes into an IndexedDB "outbox" on the phone.
 * 3. We try to upload the outbox right away, whenever the phone comes back online,
 *    and every 30 seconds. Each entry has a random client_uuid, so uploading the
 *    same entry twice is harmless (the server answers "duplicate").
 */
(function () {
  const dataEl = document.getElementById("scout-data");
  if (!dataEl) return;
  const CFG = JSON.parse(dataEl.textContent);
  const T = CFG.i18n;
  const SYNC_URL = document.getElementById("scout-root").dataset.syncUrl;
  const form = CFG.form;
  const isMatch = form.kind === "match";
  const $ = (sel, root = document) => root.querySelector(sel);
  const STATION_KEY = "openscout-station";

  // ---------- IndexedDB outbox ----------
  const DB_NAME = "openscout", STORE = "outbox";
  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "client_uuid" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function tx(mode, fn) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const result = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(result && result.result !== undefined ? result.result : result);
      t.onerror = () => reject(t.error);
    });
  }
  const outboxPut = (e) => tx("readwrite", (s) => s.put(e));
  const outboxDelete = (id) => tx("readwrite", (s) => s.delete(id));
  const outboxAll = () => tx("readonly", (s) => s.getAll());

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    // Fallback for plain-http LAN testing (randomUUID needs a secure context).
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : document.getElementById("scout-root").dataset.csrf;
  }

  // ---------- Sync ----------
  let syncing = false;
  async function sync() {
    if (syncing) return;
    const pending = await outboxAll();
    renderOutbox(pending);
    if (!pending.length) return;
    if (!navigator.onLine) { setStatus(T.offline_saved, "warn"); return; }
    syncing = true;
    setStatus(T.syncing);
    try {
      const resp = await fetch(SYNC_URL, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ entries: pending }),
      });
      if (resp.status === 401 || resp.status === 403) {
        setStatus(T.signin, "warn");
        return;
      }
      const body = await resp.json();
      for (const r of body.results || []) {
        if (r.status === "ok" || r.status === "duplicate") {
          await outboxDelete(r.client_uuid);
        } else {
          const e = pending.find((p) => p.client_uuid === r.client_uuid);
          if (e) { e.error = r.error; await outboxPut(e); }
        }
      }
      setStatus(T.synced, "ok");
    } catch (err) {
      setStatus(T.offline_saved, "warn");
    } finally {
      syncing = false;
      renderOutbox(await outboxAll());
    }
  }

  function setStatus(text, kind = "") {
    const el = $("#sync-status");
    el.textContent = text;
    el.className = "sync-status " + kind;
  }

  function renderOutbox(items) {
    $("#pending-count").textContent = items.length;
    const list = $("#outbox-list");
    list.innerHTML = "";
    items.forEach((e) => {
      const li = document.createElement("li");
      li.innerHTML = `<span><strong>${e.scouted_team}</strong> · ${e.match_label || T.pit}</span>`;
      if (e.error) {
        const err = document.createElement("span");
        err.className = "err";
        err.textContent = e.error;
        li.appendChild(err);
        const del = document.createElement("button");
        del.type = "button";
        del.className = "btn btn-sm btn-ghost";
        del.textContent = T.discard;
        del.onclick = async () => { if (confirmDiscard()) { await outboxDelete(e.client_uuid); sync(); } };
        li.appendChild(del);
      }
      list.appendChild(li);
    });
    $("#outbox").hidden = !items.length;
  }
  function confirmDiscard() { return window.confirm(T.confirm_discard); }

  // ---------- Form rendering ----------
  const PHASE_ORDER = ["prematch", "auto", "teleop", "endgame", "general"];
  const values = {};

  function el(tag, attrs = {}, children = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    children.forEach((c) => n.appendChild(c));
    return n;
  }

  function buildField(f) {
    const wrap = el("div", { class: "sf-field sf-" + f.type, "data-key": f.key });
    wrap.appendChild(el("label", { class: "sf-label", text: f.label + (f.required ? " *" : "") }));
    if (f.help) wrap.appendChild(el("div", { class: "sf-help", text: f.help }));
    const body = el("div", { class: "sf-input" });
    wrap.appendChild(body);

    if (f.type === "counter") {
      values[f.key] = f.min ?? 0;
      const out = el("output", { class: "counter-value", text: String(values[f.key]) });
      const set = (v) => {
        if (f.min != null && v < f.min) v = f.min;
        if (f.max != null && v > f.max) v = f.max;
        values[f.key] = v; out.textContent = v;
      };
      body.append(
        el("button", { type: "button", class: "counter-btn minus", text: "−", onclick: () => set(values[f.key] - 1) }),
        out,
        el("button", { type: "button", class: "counter-btn plus", text: "+", onclick: () => set(values[f.key] + 1) })
      );
      wrap._reset = () => set(f.min ?? 0);
    } else if (f.type === "number") {
      const inp = el("input", { type: "number", inputmode: "decimal", class: "input" });
      if (f.min != null) inp.min = f.min;
      if (f.max != null) inp.max = f.max;
      inp.addEventListener("input", () => (values[f.key] = inp.value === "" ? null : Number(inp.value)));
      body.appendChild(inp);
      wrap._reset = () => { inp.value = ""; values[f.key] = null; };
    } else if (f.type === "boolean") {
      values[f.key] = false;
      const yes = el("button", { type: "button", class: "chip", text: T.yes });
      const no = el("button", { type: "button", class: "chip active", text: T.no });
      const set = (v) => { values[f.key] = v; yes.classList.toggle("active", v); no.classList.toggle("active", !v); };
      yes.onclick = () => set(true); no.onclick = () => set(false);
      body.append(no, yes);
      wrap._reset = () => set(false);
    } else if (f.type === "choice" || f.type === "rating") {
      const opts = f.type === "rating" ? ["1", "2", "3", "4", "5"] : f.options;
      values[f.key] = null;
      const btns = opts.map((o) => el("button", { type: "button", class: "chip", text: o }));
      btns.forEach((b, i) => b.addEventListener("click", () => {
        const already = b.classList.contains("active");
        btns.forEach((x) => x.classList.remove("active"));
        if (already) { values[f.key] = null; return; }
        b.classList.add("active");
        values[f.key] = f.type === "rating" ? i + 1 : opts[i];
      }));
      body.append(...btns);
      wrap._reset = () => { btns.forEach((x) => x.classList.remove("active")); values[f.key] = null; };
    } else if (f.type === "multi") {
      values[f.key] = [];
      const btns = f.options.map((o) => el("button", { type: "button", class: "chip", text: o }));
      btns.forEach((b, i) => b.addEventListener("click", () => {
        b.classList.toggle("active");
        values[f.key] = f.options.filter((_, j) => btns[j].classList.contains("active"));
      }));
      body.append(...btns);
      wrap._reset = () => { btns.forEach((x) => x.classList.remove("active")); values[f.key] = []; };
    } else {
      const ta = el("textarea", { rows: "2", class: "input" });
      ta.addEventListener("input", () => (values[f.key] = ta.value));
      body.appendChild(ta);
      wrap._reset = () => { ta.value = ""; values[f.key] = ""; };
    }
    return wrap;
  }

  function buildForm() {
    const host = $("#sf-fields");
    PHASE_ORDER.forEach((phase) => {
      const fields = form.fields.filter((f) => f.phase === phase);
      if (!fields.length) return;
      const sec = el("section", { class: "sf-phase phase-" + phase });
      sec.appendChild(el("h3", { text: T.phases[phase] || phase }));
      fields.forEach((f) => sec.appendChild(buildField(f)));
      host.appendChild(sec);
    });
  }

  // ---------- Match / team selection ----------
  const matchSel = $("#sf-match");
  const teamInp = $("#sf-team");
  const stationSel = $("#sf-station");
  const robotBox = $("#sf-robots");

  function currentMatch() { return CFG.matches.find((m) => m.key === matchSel.value); }

  function renderRobots() {
    robotBox.innerHTML = "";
    const m = currentMatch();
    if (!m) return;
    const station = stationSel ? stationSel.value : "";
    [["red", m.red], ["blue", m.blue]].forEach(([color, teams]) => {
      teams.forEach((t, i) => {
        const b = el("button", { type: "button", class: `robot ${color}`, text: String(t) });
        if (String(t) === teamInp.value) b.classList.add("active");
        b.onclick = () => { teamInp.value = t; renderRobots(); };
        robotBox.appendChild(b);
      });
    });
    if (station) {
      const [color, idx] = [station.slice(0, -1), Number(station.slice(-1)) - 1];
      const t = (color === "red" ? m.red : m.blue)[idx];
      if (t && !teamInp.dataset.manual) { teamInp.value = t; Array.from(robotBox.children).forEach((b) => b.classList.toggle("active", b.textContent === String(t))); }
    }
  }

  function setupSelectors() {
    if (isMatch) {
      CFG.matches.forEach((m) => matchSel.appendChild(el("option", { value: m.key, text: `${m.label}  —  🔴 ${m.red.join(" ")}  🔵 ${m.blue.join(" ")}` })));
      const params = new URLSearchParams(location.search);
      if (params.get("match")) matchSel.value = params.get("match");
      if (params.get("team")) { teamInp.value = params.get("team"); teamInp.dataset.manual = "1"; }
      try { if (stationSel) stationSel.value = localStorage.getItem(STATION_KEY) || ""; } catch (e) {}
      matchSel.addEventListener("change", () => { delete teamInp.dataset.manual; renderRobots(); });
      stationSel?.addEventListener("change", () => {
        try { localStorage.setItem(STATION_KEY, stationSel.value); } catch (e) {}
        delete teamInp.dataset.manual; renderRobots();
      });
      teamInp.addEventListener("input", () => { teamInp.dataset.manual = "1"; renderRobots(); });
      renderRobots();
    } else {
      const params = new URLSearchParams(location.search);
      if (params.get("team")) teamInp.value = params.get("team");
    }
  }

  function resetForm() {
    document.querySelectorAll(".sf-field").forEach((w) => w._reset && w._reset());
    if (isMatch) {
      // Move to the next match so a scout assigned to a station can keep going.
      const i = CFG.matches.findIndex((m) => m.key === matchSel.value);
      if (i >= 0 && i < CFG.matches.length - 1) matchSel.value = CFG.matches[i + 1].key;
      delete teamInp.dataset.manual;
      teamInp.value = "";
      renderRobots();
    } else {
      teamInp.value = "";
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function submit(ev) {
    ev.preventDefault();
    const team = parseInt(teamInp.value, 10);
    const errors = [];
    if (!team) errors.push(T.need_team);
    if (isMatch && !matchSel.value) errors.push(T.need_match);
    form.fields.forEach((f) => {
      const v = values[f.key];
      if (f.required && (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length))) errors.push(`${f.label}: ${T.required}`);
    });
    const errBox = $("#sf-errors");
    errBox.textContent = errors.join(" · ");
    errBox.hidden = !errors.length;
    if (errors.length) return;

    const m = currentMatch();
    const entry = {
      client_uuid: uuid(),
      team: CFG.team,
      event: CFG.event,
      form: form.id,
      match_key: isMatch ? matchSel.value : "",
      match_label: m ? m.label : "",
      scouted_team: team,
      data: JSON.parse(JSON.stringify(values)),
      recorded_at: new Date().toISOString(),
      offline: !navigator.onLine,
    };
    await outboxPut(entry);
    flash(`${T.saved} ${team}${m ? " · " + m.label : ""}`);
    resetForm();
    sync();
  }

  function flash(text) {
    const f = $("#sf-flash");
    f.textContent = text;
    f.hidden = false;
    clearTimeout(f._t);
    f._t = setTimeout(() => (f.hidden = true), 2500);
  }

  // ---------- Boot ----------
  buildForm();
  setupSelectors();
  $("#sf-form").addEventListener("submit", submit);
  $("#sync-now").addEventListener("click", sync);
  window.addEventListener("online", sync);
  setInterval(sync, 30000);
  sync();
})();
