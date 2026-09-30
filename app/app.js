/* Pili.PH — Philippine officials directory.
 * Static app: reads JSON produced by /scraper into app/data/.
 * No data is invented here; every field shown comes from a scraped source.
 */
(() => {
  "use strict";

  const ELECTION_DAY = new Date("2028-05-08T07:00:00+08:00"); // 2nd Monday of May 2028
  const PAGE = 60;
  const STORE_KEY = "pili.ballot.v1";

  const LEVELS = {
    senate: "Senador",
    house: "Kinatawan",
    governor: "Gobernador",
    vice_governor: "Bise Gobernador",
    board_member: "Bokal",
    mayor: "Alkalde",
    vice_mayor: "Bise Alkalde",
    councilor: "Konsehal",
    punong_barangay: "Punong Barangay",
    kagawad: "Kagawad",
    sk_chair: "SK Chair",
    sk_kagawad: "SK Kagawad",
    barangay_secretary: "Kalihim ng Barangay",
    barangay_treasurer: "Ingat-yaman ng Barangay",
    other: "Iba pa",
  };
  const FILTERS = [
    ["all", "Lahat", () => true],
    ["senate", "Senado", (o) => o.level === "senate"],
    ["house", "Kamara", (o) => o.level === "house"],
    ["gov", "Gobernador", (o) => o.level === "governor" || o.level === "vice_governor"],
    ["mayor", "Alkalde", (o) => o.level === "mayor" || o.level === "vice_mayor"],
    ["council", "Konsehal", (o) => o.level === "councilor" || o.level === "board_member"],
    ["brgy", "Barangay", (o) => o.dataset === "barangay"],
  ];
  const BALLOT_SLOTS = [
    { key: "president", label: "Pangulo", max: 1 },
    { key: "vp", label: "Bise Pangulo", max: 1 },
    { key: "senate", label: "Senado", max: 12, hint: (o) => o.level === "senate" },
    { key: "rep", label: "Kinatawan ng Distrito / Party-list", max: 1, hint: (o) => o.level === "house" },
    { key: "mayor", label: "Alkalde", max: 1, hint: (o) => o.level === "mayor" },
    { key: "local", label: "Iba pang lokal na opisyal", max: 10 },
  ];

  // ------------------------------------------------------------------ state
  const state = {
    manifest: null,
    officials: [],           // senate + house + lgu (always loaded)
    byKey: new Map(),        // `${dataset}/${id}` -> official
    lgus: [],
    brgyIndex: null,
    brgyFiles: new Map(),    // file -> records (lazy)
    filter: "all",
    q: "",
    shown: PAGE,
    compare: [null, null],
    loading: true,
    error: null,
  };

  // --------------------------------------------------------------- helpers
  const $ = (s, el = document) => el.querySelector(s);
  const view = $("#view");
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const key = (o) => `${o.dataset}/${o.id}`;
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fil-PH", { year: "numeric", month: "long", day: "numeric" }) : "—");
  const fmtNum = (n) => Number(n || 0).toLocaleString("en-PH");
  const initials = (name) => name.split(/\s+/).filter((w) => /^[A-Za-zÀ-ÿÑñ]/.test(w)).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const place = (o, withDistrict = true) => [o.barangay && `Brgy. ${o.barangay}`, o.lgu, withDistrict && o.district, o.province, o.region].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", ");
  const levelLabel = (o) => o.position || LEVELS[o.level] || o.level;

  function avatar(o, cls = "") {
    const img = safeUrl(o.photo);
    return `<span class="avatar ${cls}">${img ? `<img src="${esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}<span>${esc(initials(o.name))}</span></span>`;
  }
  // When the photo loads it covers the initials; if it fails we remove it.
  document.addEventListener("load", (e) => { if (e.target.matches?.(".avatar img")) e.target.nextElementSibling?.remove(); }, true);

  function row(o, i) {
    return `<a class="row" href="#/o/${encodeURIComponent(o.dataset)}/${encodeURIComponent(o.id)}">
      ${i != null ? `<span class="num">${i + 1}</span>` : ""}
      ${avatar(o)}
      <span class="who"><b>${esc(o.name)}</b><span>${esc(levelLabel(o))}${place(o) ? " · " + esc(place(o)) : ""}</span></span>
      ${o.party ? `<span class="tag">${esc(o.party)}</span>` : ""}
    </a>`;
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2400);
  }

  async function getJSON(path) {
    const res = await fetch(`data/${path}`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  }

  function addRecords(records, dataset) {
    for (const r of records || []) {
      const o = { ...r, dataset, _s: norm([r.name, r.position, r.party, r.district, r.province, r.lgu, r.barangay, r.region].join(" ")) };
      state.byKey.set(key(o), o);
      state.officials.push(o);
    }
  }

  // ----------------------------------------------------------------- data
  async function load() {
    try {
      state.manifest = await getJSON("manifest.json");
    } catch (e) {
      state.manifest = { datasets: [] };
    }
    const ds = Object.fromEntries((state.manifest.datasets || []).map((d) => [d.key, d]));
    const tasks = ["senate", "house", "lgu"].filter((k) => ds[k]?.count).map(async (k) => {
      try {
        const doc = await getJSON(ds[k].file);
        addRecords(doc.records, k);
        if (k === "lgu") state.lgus = doc.lgus || [];
      } catch (e) {
        console.warn(e);
      }
    });
    if (ds.barangay?.count) {
      tasks.push(getJSON(ds.barangay.file).then((d) => (state.brgyIndex = d)).catch(console.warn));
    }
    await Promise.all(tasks);
    const order = ["senate", "house", "governor", "vice_governor", "mayor", "vice_mayor", "board_member", "councilor"];
    state.officials.sort((a, b) => (order.indexOf(a.level) + 1 || 99) - (order.indexOf(b.level) + 1 || 99) || a.name.localeCompare(b.name));
    restoreCompare();
    state.loading = false;
    render();
  }

  async function loadBrgyFile(file) {
    if (state.brgyFiles.has(file)) return state.brgyFiles.get(file);
    const doc = await getJSON(file);
    const recs = doc.records.map((r) => ({ ...r, dataset: "barangay", _file: file, _s: norm([r.name, r.position, r.lgu, r.barangay, r.province].join(" ")) }));
    recs.forEach((o) => state.byKey.set(key(o), o));
    state.brgyFiles.set(file, recs);
    return recs;
  }

  async function findOfficial(dataset, id) {
    let o = state.byKey.get(`${dataset}/${id}`);
    if (o || dataset !== "barangay" || !state.brgyIndex) return o;
    // Barangay IDs start with the province slug; load the matching file.
    for (const f of state.brgyIndex.files) {
      const prov = f.file.split("--")[1]?.replace(".json", "");
      if (prov && id.includes(prov)) {
        await loadBrgyFile(f.file);
        o = state.byKey.get(`${dataset}/${id}`);
        if (o) return o;
      }
    }
    return undefined;
  }

  const hasData = () => state.officials.length > 0 || (state.brgyIndex?.files?.length ?? 0) > 0;

  function noData() {
    return `<div class="empty"><span class="ei">🗂️</span>
      <b>Wala pang datos.</b><br>Kinokolekta pa ang listahan ng mga opisyal mula sa opisyal na mga website ng gobyerno. Subukan muli mamaya.
      <p class="meta">Mga pinagkukunan: Senado, Kamara, PSA, DILG — tingnan ang <a href="#/ako">Datos</a>.</p></div>`;
  }

  // --------------------------------------------------------------- views
  function viewHome() {
    const f = FILTERS.find((x) => x[0] === state.filter) || FILTERS[0];
    const q = norm(state.q).trim();
    const terms = q.split(/\s+/).filter(Boolean);
    let list = state.officials.filter(f[2]).filter((o) => terms.every((t) => o._s.includes(t)));
    const brgyNote = state.filter === "brgy";

    view.innerHTML = `
      <input class="search" id="q" type="search" placeholder="Hanapin ang opisyal, posisyon, lugar…" value="${esc(state.q)}" aria-label="Hanapin">
      <div class="chips" role="toolbar" aria-label="Filter">${FILTERS.map(([k, label]) => `<button class="chip" data-f="${k}" aria-pressed="${k === state.filter}">${label}</button>`).join("")}</div>
      <div class="quick">
        <a href="#/ihambing"><span class="qi">⚖️</span><b>Ihambing</b><small>Compare</small></a>
        <a href="#/pili"><span class="qi">🗳️</span><b>2028 List</b><small>Pili Ko</small></a>
        <a href="#/ako"><span class="qi">📊</span><b>Stats</b><small>Datos</small></a>
      </div>
      <div id="results"></div>`;

    const results = $("#results");
    if (state.loading) {
      results.innerHTML = `<div class="section-label">Naglo-load…</div>` + '<div class="skeleton"></div>'.repeat(6);
    } else if (!hasData()) {
      results.innerHTML = noData();
    } else if (brgyNote) {
      results.innerHTML = `<div class="empty"><span class="ei">🏘️</span>May ${fmtNum(state.brgyIndex?.count)} barangay officials sa directory.<br>Piliin ang lugar sa <a href="#/hanap">Hanapin</a> para makita sila.</div>`;
    } else {
      results.innerHTML = `<div class="section-label">${esc(f[1])} · ${fmtNum(list.length)} opisyal</div>
        <div class="list">${list.slice(0, state.shown).map((o) => row(o)).join("") || `<div class="empty">Walang tugma sa “${esc(state.q)}”.</div>`}</div>
        ${list.length > state.shown ? `<button class="btn more" id="more">Ipakita pa (${fmtNum(list.length - state.shown)})</button>` : ""}`;
    }

    const input = $("#q");
    input.addEventListener("input", () => {
      state.q = input.value;
      state.shown = PAGE;
      const pos = input.selectionStart;
      viewHome();
      const i2 = $("#q");
      i2.focus();
      i2.setSelectionRange(pos, pos);
    });
    view.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => { state.filter = b.dataset.f; state.shown = PAGE; viewHome(); }));
    $("#more")?.addEventListener("click", () => { state.shown += PAGE * 2; viewHome(); });
  }

  // Browse by place: region -> province -> city/municipality -> barangay
  const hanap = { region: "", province: "", lgu: "", barangay: "" };
  async function viewHanap() {
    if (state.loading) { view.innerHTML = '<div class="skeleton"></div>'.repeat(4); return; }
    if (!hasData()) { view.innerHTML = noData(); return; }

    const brgyFiles = state.brgyIndex?.files || [];
    const regions = new Set(), provinces = new Set();
    state.officials.forEach((o) => { if (o.region) regions.add(o.region); });
    brgyFiles.forEach((f) => { if (f.region) regions.add(f.region); });
    const inRegion = (r) => !hanap.region || r === hanap.region;
    state.officials.forEach((o) => { if (o.province && inRegion(o.region)) provinces.add(o.province); });
    brgyFiles.forEach((f) => { if (f.province && inRegion(f.region)) provinces.add(f.province); });

    let brgyRecs = [];
    const files = brgyFiles.filter((f) => inRegion(f.region) && (!hanap.province || f.province === hanap.province));
    if (hanap.province && files.length) {
      view.innerHTML = '<div class="skeleton"></div>'.repeat(4);
      brgyRecs = (await Promise.all(files.map((f) => loadBrgyFile(f.file).catch(() => [])))).flat();
    }
    const lgus = new Set();
    state.officials.forEach((o) => { if (o.lgu && inRegion(o.region) && (!hanap.province || o.province === hanap.province)) lgus.add(o.lgu); });
    brgyRecs.forEach((o) => o.lgu && lgus.add(o.lgu));
    const brgys = new Set(brgyRecs.filter((o) => !hanap.lgu || o.lgu === hanap.lgu).map((o) => o.barangay).filter(Boolean));

    const opt = (set, cur, all) => `<option value="">${all}</option>` + [...set].sort().map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
    const match = (o) => inRegion(o.region) && (!hanap.province || o.province === hanap.province) && (!hanap.lgu || o.lgu === hanap.lgu) && (!hanap.barangay || o.barangay === hanap.barangay);
    const anyFilter = hanap.region || hanap.province || hanap.lgu || hanap.barangay;
    const list = anyFilter ? [...state.officials.filter((o) => o.level !== "senate" && match(o)), ...brgyRecs.filter(match)] : [];

    view.innerHTML = `
      <div class="section-label">Hanapin ayon sa lugar</div>
      <select class="select" data-k="region" aria-label="Rehiyon">${opt(regions, hanap.region, "Lahat ng rehiyon")}</select>
      <select class="select" data-k="province" aria-label="Probinsya">${opt(provinces, hanap.province, "Lahat ng probinsya")}</select>
      <select class="select" data-k="lgu" aria-label="Lungsod / Bayan" ${lgus.size ? "" : "disabled"}>${opt(lgus, hanap.lgu, "Lahat ng lungsod / bayan")}</select>
      <select class="select" data-k="barangay" aria-label="Barangay" ${brgys.size ? "" : "disabled"}>${opt(brgys, hanap.barangay, hanap.province ? "Lahat ng barangay" : "Pumili muna ng probinsya para sa barangay")}</select>
      ${anyFilter ? `<div class="section-label">${fmtNum(list.length)} opisyal</div><div class="list">${list.slice(0, 400).map((o) => row(o)).join("") || '<div class="empty">Walang opisyal na nakatala para sa lugar na ito.</div>'}</div>${list.length > 400 ? `<p class="meta">Ipinapakita ang unang 400. Paliitin ang lugar para makita ang iba.</p>` : ""}`
        : `<div class="empty"><span class="ei">📍</span>Pumili ng rehiyon o probinsya para makita ang mga kinatawan, alkalde, at barangay officials doon.<br><br>Para sa mga senador (nationwide), gamitin ang <a href="#/">Opisyal</a> tab.</div>`}`;

    view.querySelectorAll("select[data-k]").forEach((s) => s.addEventListener("change", () => {
      const k = s.dataset.k;
      hanap[k] = s.value;
      const order = ["region", "province", "lgu", "barangay"];
      order.slice(order.indexOf(k) + 1).forEach((kk) => (hanap[kk] = ""));
      viewHanap();
    }));
  }

  async function viewProfile(dataset, id) {
    view.innerHTML = '<div class="skeleton" style="height:180px"></div>';
    const o = await findOfficial(dataset, id);
    if (!o) {
      view.innerHTML = `<div class="empty"><span class="ei">🤷</span>Hindi nahanap ang opisyal na ito.<br><a href="#/">Bumalik sa listahan</a></div>`;
      return;
    }
    setTitle(o.name);
    const rows = [
      ["Posisyon", levelLabel(o)],
      ["Partido", o.party],
      ["Distrito", o.district],
      ["Barangay", o.barangay],
      ["Lungsod / Bayan", o.lgu],
      ["Probinsya", o.province],
      ["Rehiyon", o.region],
      ["Contact", o.contact],
    ];
    const d = o.details || {};
    if (d.address) rows.push(["Opisina", d.address]);
    const skip = new Set(["title", "position_raw", "address", "biography", "resume", "created_at", "updated_at", "deleted_at"]);
    const extra = Object.entries(d).filter(([k, v]) => v && !skip.has(k) && !/^line\d|href|photo|image|img|^id$|_id$|slug/.test(k) && !rows.some(([, rv]) => rv === v));
    const pretty = (k) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    const cv = safeUrl(d.resume);
    const inBallot = Object.values(getBallot()).some((arr) => arr.includes(key(o)));

    view.innerHTML = `
      <div class="profile-head">
        ${avatar(o, "lg")}
        <h1>${esc(o.name)}</h1>
        <p>${esc(levelLabel(o))}</p>
        <div class="badges">
          ${o.party ? `<span class="badge">${esc(o.party)}</span>` : ""}
          ${/wikipedia/i.test(o.source) ? '<span class="badge warn">Wikipedia · hindi opisyal</span>' : /saved copy/i.test(o.source) ? '<span class="badge ok">✓ Kopya ng opisyal na datos</span>' : '<span class="badge ok">✓ Opisyal na datos</span>'}
        </div>
      </div>
      <div class="btn-row">
        <button class="btn" id="cmp">⚖️ Ihambing</button>
        <button class="btn primary" id="pick">${inBallot ? "✓ Nasa Pili Ko" : "＋ Pili Ko 2028"}</button>
      </div>
      <div class="section-label">Impormasyon</div>
      <table class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("")}
        ${extra.slice(0, 20).map(([k, v]) => `<tr><th>${esc(pretty(k))}</th><td>${esc(v)}</td></tr>`).join("")}</table>
      ${(o.achievements || []).length ? `<div class="section-label">Mga Nagawa at Parangal</div><ul class="bullets">${o.achievements.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      ${(o.bills || []).length ? `<div class="section-label">Mga Panukalang Batas (${fmtNum(o.bills.length)})</div><ul class="bills">${o.bills.slice(0, 50).map((b) => `<li>${safeUrl(b.url) ? `<a href="${esc(b.url)}" target="_blank" rel="noopener">` : ""}<b>${esc(b.number || "")}</b> ${esc(b.title || "")}${safeUrl(b.url) ? "</a>" : ""}${b.status ? `<span class="meta"> · ${esc(b.status)}</span>` : ""}${b.date ? `<span class="meta"> · ${esc(b.date)}</span>` : ""}</li>`).join("")}</ul>${o.bills.length > 50 ? `<p class="meta">Ipinapakita ang unang 50.</p>` : ""}` : ""}
      ${d.biography ? `<div class="section-label">Talambuhay</div><p class="bio">${esc(d.biography)}</p>` : ""}
      ${cv ? `<p><a class="btn block" href="${esc(cv)}" target="_blank" rel="noopener">📄 Opisyal na CV (PDF) ↗</a></p>` : ""}
      <div class="notice">
        Pinagkunan: <a href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener">${esc(o.source)}</a>
        ${safeUrl(o.profile_url) ? ` · <a href="${esc(o.profile_url)}" target="_blank" rel="noopener">Opisyal na profile ↗</a>` : ""}
        <br>Huling na-update: ${fmtDate(datasetDate(o.dataset, o._file))}
      </div>`;

    $("#cmp").addEventListener("click", () => {
      const slot = state.compare[0] ? 1 : 0;
      state.compare[slot] = o;
      saveCompare();
      location.hash = "#/ihambing";
    });
    $("#pick").addEventListener("click", () => {
      const slot = BALLOT_SLOTS.find((s) => s.hint?.(o)) || BALLOT_SLOTS[BALLOT_SLOTS.length - 1];
      if (addToBallot(slot.key, o)) toast(`Idinagdag sa ${slot.label}`);
      viewProfile(dataset, id);
    });
  }

  function datasetDate(ds, file) {
    if (ds === "barangay" && file && state.brgyIndex) return state.brgyIndex.files.find((f) => f.file === file)?.scraped_at;
    return state.manifest?.datasets?.find((d) => d.key === ds)?.scraped_at;
  }

  // Compare
  function saveCompare() {
    try { sessionStorage.setItem("pili.compare", JSON.stringify(state.compare.map((o) => (o ? key(o) : null)))); } catch {}
  }
  function restoreCompare() {
    try {
      const keys = JSON.parse(sessionStorage.getItem("pili.compare") || "[]");
      state.compare = [0, 1].map((i) => (keys[i] && state.byKey.get(keys[i])) || null);
    } catch {}
  }

  function viewCompare() {
    if (!state.loading && !hasData()) { view.innerHTML = noData(); return; }
    const [a, b] = state.compare;
    const slot = (o, i) => o
      ? `<button class="slot" data-slot="${i}">${avatar(o)}<b>${esc(o.name)}</b><small>${esc(levelLabel(o))}</small><small>Palitan</small></button>`
      : `<button class="slot" data-slot="${i}"><span class="avatar">＋</span><b>Pumili</b><small>ng opisyal</small></button>`;
    let table = "";
    if (a && b) {
      const fields = [
        ["Posisyon", levelLabel], ["Partido", (o) => o.party], ["Distrito", (o) => o.district],
        ["Lugar", (o) => place(o, false)], ["Pinagkunan", (o) => o.source],
      ];
      const shared = Object.keys(a.details || {}).filter((k) => b.details?.[k] && !/^line\d|href|photo|image|img|^id$|_id$|slug|position_raw|biography|resume|created_at|updated_at|deleted_at/.test(k));
      shared.slice(0, 12).forEach((k) => fields.push([k.replace(/_/g, " "), (o) => o.details[k]]));
      table = fields.map(([lab, fn]) => {
        const va = fn(a) || "—", vb = fn(b) || "—";
        const same = va !== "—" && va === vb;
        return `<div class="cmp-row"><div class="lbl">${esc(lab)}</div><div class="vals"><div class="${same ? "same" : ""}">${esc(va)}</div><div class="${same ? "same" : ""}">${esc(vb)}</div></div></div>`;
      }).join("");
    }
    view.innerHTML = `
      <div class="section-label">Ihambing</div>
      <p class="meta" style="margin-top:-4px">Ihambing ang dalawang opisyal nang magkatabi.</p>
      <div class="compare">${slot(a, 0)}<span class="vs">vs</span>${slot(b, 1)}</div>
      ${table || '<div class="empty">Pumili ng dalawang opisyal para ihambing.</div>'}
      ${a || b ? '<button class="btn block" id="clear-cmp">I-reset</button>' : ""}`;
    view.querySelectorAll("[data-slot]").forEach((btn) => btn.addEventListener("click", async () => {
      const o = await pickOfficial("Pumili ng opisyal na ihahambing");
      if (!o) return;
      state.compare[+btn.dataset.slot] = o;
      saveCompare();
      viewCompare();
    }));
    $("#clear-cmp")?.addEventListener("click", () => { state.compare = [null, null]; saveCompare(); viewCompare(); });
  }

  // Ballot (Pili Ko 2028) — stored only on this device.
  function getBallot() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); } catch { return {}; }
  }
  function setBallot(b) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(b)); } catch { toast("Hindi ma-save sa device na ito"); }
  }
  function addToBallot(slotKey, o) {
    const b = getBallot();
    const slot = BALLOT_SLOTS.find((s) => s.key === slotKey);
    const arr = b[slotKey] || [];
    if (arr.includes(key(o))) { toast("Nasa listahan na"); return false; }
    if (arr.length >= slot.max) { toast(`Puno na ang ${slot.label} (${slot.max})`); return false; }
    b[slotKey] = [...arr, key(o)];
    setBallot(b);
    return true;
  }

  async function viewPili() {
    const days = Math.max(0, Math.ceil((ELECTION_DAY - Date.now()) / 86400000));
    const b = getBallot();
    // Make sure barangay picks are resolvable.
    for (const k of Object.values(b).flat()) {
      const [ds, ...rest] = k.split("/");
      if (!state.byKey.has(k)) await findOfficial(ds, rest.join("/"));
    }
    const lines = [];
    view.innerHTML = `
      <div class="section-label">Pili Ko 2028</div>
      <div class="countdown">
        <small>Halalan 2028 · ${ELECTION_DAY.toLocaleDateString("fil-PH", { month: "long", day: "numeric", year: "numeric", timeZone: "Asia/Manila" })}</small>
        <div class="big">${fmtNum(days)} araw</div>
        <small>na natitira · ★ Gamitin ang iyong boto nang matalino</small>
      </div>
      ${BALLOT_SLOTS.map((s) => {
        const picks = (b[s.key] || []).map((k) => state.byKey.get(k) || { name: "(hindi na makita)", position: "", _k: k });
        picks.forEach((o) => lines.push(`${s.label}: ${o.name}`));
        return `<div class="card">
          <div class="slot-head"><b>${s.label}</b><span class="meta">${picks.length} / ${s.max}</span></div>
          ${picks.map((o, i) => `<div class="pick-row">${o.id ? avatar(o) : ""}<div class="who"><b>${esc(o.name)}</b><span>${esc(levelLabel(o))}</span></div><button class="x" data-rm="${s.key}:${i}" aria-label="Alisin">✕</button></div>`).join("")}
          ${picks.length < s.max ? `<button class="add" data-add="${s.key}">＋ Dagdag</button>` : ""}
        </div>`;
      }).join("")}
      <div class="btn-row"><button class="btn" id="share">Ibahagi</button><button class="btn" id="reset">I-clear</button></div>
      <p class="notice">Ang listahang ito ay naka-save lamang sa device mo — hindi ito ipinapadala kahit saan. Opisyal na listahan ng mga kandidato para sa 2028 ay ilalabas ng COMELEC pagkatapos ng filing ng COC.</p>`;

    view.querySelectorAll("[data-add]").forEach((btn) => btn.addEventListener("click", async () => {
      const s = BALLOT_SLOTS.find((x) => x.key === btn.dataset.add);
      const o = await pickOfficial(`Idagdag sa ${s.label}`, s.hint);
      if (o && addToBallot(s.key, o)) viewPili();
    }));
    view.querySelectorAll("[data-rm]").forEach((btn) => btn.addEventListener("click", () => {
      const [k, i] = btn.dataset.rm.split(":");
      const bb = getBallot();
      bb[k].splice(+i, 1);
      setBallot(bb);
      viewPili();
    }));
    $("#share").addEventListener("click", async () => {
      const text = `Pili Ko 2028 🇵🇭\n${lines.join("\n") || "(wala pa)"}\n— via Pili.PH`;
      try {
        if (navigator.share) await navigator.share({ title: "Pili Ko 2028", text });
        else { await navigator.clipboard.writeText(text); toast("Nakopya sa clipboard"); }
      } catch {}
    });
    $("#reset").addEventListener("click", () => { if (confirm("Burahin ang buong listahan?")) { setBallot({}); viewPili(); } });
  }

  // Stats + sources
  function viewAko() {
    const ds = state.manifest?.datasets || [];
    const counts = {};
    state.officials.forEach((o) => (counts[o.level] = (counts[o.level] || 0) + 1));
    const partyBars = (level, title) => {
      const m = {};
      state.officials.filter((o) => o.level === level).forEach((o) => { const p = o.party || "Hindi nakatala"; m[p] = (m[p] || 0) + 1; });
      const entries = Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 12);
      if (!entries.length) return "";
      const max = entries[0][1];
      return `<div class="section-label">${title}</div><div class="card">${entries.map(([p, n]) => `<div class="bar"><span class="lab" title="${esc(p)}">${esc(p)}</span><span class="track"><span class="fill" style="width:${(n / max) * 100}%;display:block"></span></span><span class="n">${n}</span></div>`).join("")}</div>`;
    };
    view.innerHTML = `
      <div class="section-label">Mga Bilang</div>
      <div class="stats">
        <div class="stat"><b>${fmtNum(counts.senate)}</b><span>Senador</span></div>
        <div class="stat"><b>${fmtNum(counts.house)}</b><span>Kinatawan sa Kamara</span></div>
        <div class="stat"><b>${fmtNum((counts.mayor || 0) + (counts.vice_mayor || 0) + (counts.councilor || 0) + (counts.governor || 0))}</b><span>Opisyal ng LGU</span></div>
        <div class="stat"><b>${fmtNum(state.brgyIndex?.count)}</b><span>Opisyal ng Barangay</span></div>
      </div>
      ${partyBars("senate", "Senado ayon sa partido")}
      ${partyBars("house", "Kamara ayon sa partido")}
      <div class="section-label">Mga pinagkukunan ng datos</div>
      <div class="card"><table class="kv">
        ${ds.map((d) => `<tr><th><a href="${esc(safeUrl(d.source_url))}" target="_blank" rel="noopener">${esc(d.source)}</a></th><td>${fmtNum(d.count)} tala<br><span class="meta">${d.scraped_at ? "Na-update " + fmtDate(d.scraped_at) : "Hinihintay pa"}</span></td></tr>`).join("") || "<tr><td>Wala pang datos.</td></tr>"}
      </table></div>
      <div class="section-label">Tungkol sa Pili.PH</div>
      <div class="card">
        <p style="margin-top:0">Ang Pili.PH ay isang independiyenteng directory ng mga halal na opisyal ng Pilipinas. Lahat ng impormasyon ay kinokopya nang awtomatiko mula sa opisyal na mga website ng Senado, Kamara, PSA, at DILG, at regular na ina-update.</p>
        <p class="meta" style="margin-bottom:0">Hindi kaanib ng anumang ahensya ng gobyerno, partido, o kandidato. May mali? Tingnan ang opisyal na pinagkunan na naka-link sa bawat profile.</p>
      </div>`;
  }

  // ------------------------------------------------------------ picker
  function pickOfficial(title, hint) {
    const dlg = $("#picker"), input = $("#picker-q"), list = $("#picker-list");
    $("#picker-title").textContent = title;
    input.value = "";
    return new Promise((resolve) => {
      let chosen = null;
      const draw = () => {
        const terms = norm(input.value).split(/\s+/).filter(Boolean);
        const pool = [...state.officials, ...[...state.brgyFiles.values()].flat()];
        let items = pool.filter((o) => terms.every((t) => o._s.includes(t)));
        if (!terms.length && hint) items = items.filter(hint);
        list.innerHTML = items.slice(0, 80).map((o) => `<li>${row(o).replace('<a class="row" href=', '<a class="row" data-k="' + esc(key(o)) + '" href=')}</li>`).join("") || '<li class="empty">Walang tugma.</li>';
      };
      list.onclick = (e) => {
        const a = e.target.closest("[data-k]");
        if (!a) return;
        e.preventDefault();
        chosen = state.byKey.get(a.dataset.k);
        dlg.close();
      };
      input.oninput = draw;
      dlg.onclose = () => resolve(chosen);
      draw();
      dlg.showModal();
      input.focus();
    });
  }

  // ------------------------------------------------------------ router
  function setTitle(sub) {
    $("#topbar-sub").textContent = sub || "Philippines Officials Directory";
    document.title = sub ? `${sub} · Pili.PH` : "Pili.PH — Philippine Officials Directory";
  }

  function render() {
    const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const tab = parts[0] === "o" ? "" : parts[0] || "home";
    document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    document.querySelectorAll(".tabbar a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    $("#back").hidden = parts[0] !== "o";
    setTitle({ hanap: "Hanapin", ihambing: "Ihambing", pili: "Pili Ko 2028", ako: "Datos at Stats" }[tab]);
    switch (parts[0]) {
      case "o": return viewProfile(parts[1], parts.slice(2).join("/"));
      case "hanap": return viewHanap();
      case "ihambing": return viewCompare();
      case "pili": return viewPili();
      case "ako": return viewAko();
      default: return viewHome();
    }
  }

  $("#back").addEventListener("click", () => (history.length > 1 ? history.back() : (location.hash = "#/")));
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
  render();
  load();

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
})();
