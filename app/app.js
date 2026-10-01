/* Pili.PH — Philippine officials directory.
 * Static app: reads JSON produced by /scraper into app/data/.
 * No data is invented here; every field shown comes from a scraped source.
 * Interface text lives in i18n.js (Tagalog / English).
 */
(() => {
  "use strict";

  const REPO_URL = "https://github.com/IvanAyao/Pili_App_PH";
  // Leave empty to keep an email address off the public site; reports then
  // go to GitHub Issues only.
  const CONTACT_EMAIL = "";
  const ELECTION_DAY = new Date("2028-05-08T07:00:00+08:00"); // 2nd Monday of May 2028
  const PAGE = 60;
  const STORE_KEY = "pili.ballot.v1";
  const LANG_KEY = "pili.lang";

  // ---------------------------------------------------------------- i18n
  const DICT = window.PILI_I18N;
  let lang = (() => {
    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved && DICT[saved]) return saved;
    } catch {}
    return /^en\b/i.test(navigator.language || "") ? "en" : "tl";
  })();
  const t = (k, vars = {}) => {
    const s = DICT[lang][k] ?? DICT.tl[k] ?? k;
    return s.replace(/\{(\w+)\}/g, (_, v) => (v in vars ? vars[v] : `{${v}}`));
  };

  function applyStatic() {
    document.documentElement.lang = lang === "en" ? "en" : "fil";
    document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    $("#lang").textContent = lang === "en" ? "TL" : "EN"; // shows the language you can switch to
  }

  function setLang(next) {
    if (!DICT[next] || next === lang) return;
    lang = next;
    try { localStorage.setItem(LANG_KEY, lang); } catch {}
    applyStatic();
    render();
  }

  const EXEC_LEVELS = new Set(["president", "vice_president"]);
  const LEVEL_KEYS = ["president", "vice_president", "senate", "house", "governor", "vice_governor", "board_member", "mayor", "vice_mayor", "councilor",
    "punong_barangay", "kagawad", "sk_chair", "sk_kagawad", "barangay_secretary", "barangay_treasurer", "other"];
  const FILTERS = [
    ["all", () => true],
    ["exec", (o) => EXEC_LEVELS.has(o.level)],
    ["senate", (o) => o.level === "senate"],
    ["house", (o) => o.level === "house"],
    ["gov", (o) => o.level === "governor" || o.level === "vice_governor"],
    ["mayor", (o) => o.level === "mayor" || o.level === "vice_mayor"],
    ["council", (o) => o.level === "councilor" || o.level === "board_member"],
    ["brgy", (o) => o.dataset === "barangay"],
  ];
  const BALLOT_SLOTS = [
    { key: "president", max: 1 },
    { key: "vp", max: 1 },
    { key: "senate", max: 12, hint: (o) => o.level === "senate" },
    { key: "rep", max: 1, hint: (o) => o.level === "house" },
    { key: "mayor", max: 1, hint: (o) => o.level === "mayor" },
    { key: "local", max: 10 },
  ];
  const slotLabel = (s) => t(`slot_${s.key}`);

  // ------------------------------------------------------------------ state
  const state = {
    manifest: null,
    officials: [],           // senate + house + lgu (always loaded)
    pastExec: [],            // former Presidents and Vice Presidents (history page)
    byKey: new Map(),        // `${dataset}/${id}` -> official
    lgus: [],
    brgyIndex: null,
    brgyFiles: new Map(),    // file -> records (lazy)
    filter: "all",
    island: "",
    filtersOpen: false,
    sort: "name",
    scope: "term",
    sector: "",
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
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(t("locale"), { year: "numeric", month: "long", day: "numeric" }) : "—");
  const fmtNum = (n) => Number(n || 0).toLocaleString("en-PH");
  const initials = (name) => name.split(/\s+/).filter((w) => /^[A-Za-zÀ-ÿÑñ]/.test(w)).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  // A bare "1st" (DILG lists) reads better as "1st District".
  const districtText = (o) => (o._dist && /^\s*(\d+\s*(st|nd|rd|th)?|lone)\s*$/i.test(o.district || "") ? districtLabel(o._dist) : o.district);
  const place = (o, withDistrict = true) => [o.barangay && `Brgy. ${o.barangay}`, o.lgu, withDistrict && districtText(o), o.province, o.region].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", ");
  // Positions come from the sources as published; the level name is only a fallback.
  const isPast = (o) => EXEC_LEVELS.has(o.level) && o.current === false;
  const levelLabel = (o) => (EXEC_LEVELS.has(o.level) ? t(isPast(o) ? `lvl_past_${o.level}` : `lvl_${o.level}`) : o.position || (LEVEL_KEYS.includes(o.level) ? t(`lvl_${o.level}`) : o.level));
  // Where data comes from: government (.gov.ph) sites are "official"; other
  // public publishers (Wikipedia, civic open data) are "public"; privately
  // run sources would be "private".
  const typeOf = (x) => x?.source_type
    || (/\.gov\.ph(\/|$)/i.test((() => { try { return new URL(x?.source_url || "").hostname + "/"; } catch { return ""; } })()) ? "official" : "public");
  const typeLabel = (tp) => t(`type_${tp}`);
  const typeBadge = (tp, extra = "") => `<span class="badge src-${String(tp).replace("+", "-")}">${tp === "official" ? "✓ " : ""}${typeLabel(tp)}${extra}</span>`;

  function avatar(o, cls = "") {
    const img = safeUrl(o.photo);
    return `<span class="avatar ${cls}">${img ? `<img src="${esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}<span>${esc(initials(o.name))}</span></span>`;
  }
  // When the photo loads it covers the initials; if it fails we remove it.
  document.addEventListener("load", (e) => { if (e.target.matches?.(".avatar img")) e.target.nextElementSibling?.remove(); }, true);

  function row(o, i, right) {
    return `<a class="row" href="#/o/${encodeURIComponent(o.dataset)}/${encodeURIComponent(o.id)}">
      ${i != null ? `<span class="num">${i + 1}</span>` : ""}
      ${avatar(o)}
      <span class="who"><b>${esc(o.name)}</b><span>${esc(levelLabel(o))}${place(o) ? " · " + esc(place(o)) : ""}</span></span>
      ${right ?? (o.party ? `<span class="tag">${esc(o.party)}</span>` : "")}
    </a>`;
  }

  // Bill counts per senator: all filed, as main author, as co-author. Only
  // senators have bill data, so sorting by these limits the list to them.
  const termSpan = (x) => `${fmtDate(x.start)} – ${x.end ? fmtDate(x.end) : t("present")}`;
  const careerSpan = (c) => `${(c.start || "").slice(0, 4) || "?"}–${c.end ? c.end.slice(0, 4) : t("present")}`;

  // Consecutive term (1-3) of a local official, from Wikipedia's term column
  // or OpenHalalan's election history; anything else is left unstated.
  const TERM_LIMITED_LEVELS = new Set(["governor", "vice_governor", "board_member", "mayor", "vice_mayor", "councilor", "punong_barangay", "kagawad"]);
  const termOf = (o) => {
    const n = parseInt(o.details?.term, 10);
    return TERM_LIMITED_LEVELS.has(o.level) && n >= 1 && n <= 3 ? n : 0;
  };
  const tidyName = (s) => String(s).replace(/\b([A-Za-zÀ-ÿÑñ])([A-Za-zÀ-ÿÑñ'.-]*)/g, (m, a, b) => a.toUpperCase() + b.toLowerCase());

  // Terms: bill data covers the Senate from the 13th Congress (2004); the
  // sitting Congress is still in progress, so averages use completed ones.
  const currentCongress = () => state.billsSource?.congress || 20;
  const congressStart = (n) => (n <= 8 ? 1987 : 1992 + 3 * (n - 9));
  const congressYears = (n) => state.billsSource?.congresses?.[n]?.years || `${congressStart(n)}–${n === 8 ? 1992 : congressStart(n) + 3}`;
  const congressName = (n) => t("congress_n", { n, nth: ordinal(n) });
  function perCongress(o) {
    const senate = new Set(o.service?.senate_congresses || []);
    const done = (o.bill_terms || []).filter((x) => x.congress !== currentCongress() && senate.has(x.congress));
    return done.length ? Math.round(done.reduce((sum, x) => sum + x.filed, 0) / done.length) : null;
  }
  const billStats = (o) => {
    const bills = o.bills || [];
    const co = bills.filter((b) => b.coauthored).length;
    return { bills: o.bills_count ?? bills.length, main: bills.length - co, co,
      bills_all: o.bills_all ?? bills.length, law_all: o.law_all ?? 0, avg: perCongress(o),
      main_all: (o.bill_terms || []).reduce((sum, x) => sum + x.main, 0) };
  };
  const serviceText = (o) => (o.service?.first_senate_year
    ? `${t("senator_since", { y: o.service.first_senate_year })} · ${t(o.service.senate_terms === 1 ? "term_one" : "terms_n", { n: o.service.senate_terms })}`
    : "");
  // [20, 19, 17, 16] -> "2016–2022, 2025–present" style ranges.
  function congressRanges(list) {
    const cur = currentCongress();
    const runs = [];
    [...list].sort((a, b) => a - b).forEach((c) => {
      const last = runs[runs.length - 1];
      if (last && c === last[1] + 1) last[1] = c; else runs.push([c, c]);
    });
    return runs.map(([a, b]) => `${congressStart(a)}–${b >= cur ? t("present") : congressStart(b) + 3}`).join(", ");
  }
  // Sorting starts with this term (the sitting Congress, the same period for
  // every senator); "whole career" switches to totals since 2004 and adds
  // bills that became law.
  const SORTS = ["name", "filed", "main", "law"];
  const sortKey = () => (state.scope === "career"
    ? { filed: "bills_all", main: "main_all", law: "law_all" }[state.sort]
    : { filed: "bills", main: "main" }[state.sort]);
  // Sectors group bills by the Senate committee they were referred to.
  const sectorKeys = () => state.billsSource?.sectors || [];
  const SORT_INDEX = { filed: 0, main: 1, law: 2 };
  const sectorCount = (o, sector, scope = state.scope, sort = state.sort) => o.bill_sectors?.[scope]?.[sector]?.[SORT_INDEX[sort]] ?? 0;
  const rankValue = (o) => (state.sector ? sectorCount(o, state.sector) : billStats(o)[sortKey()]);
  const billsHref = (o, scope = state.scope, sector = state.sector) =>
    `#/bills/${encodeURIComponent(o.id)}${scope === "career" || sector ? `/${scope}` : ""}${sector ? `/${sector}` : ""}`;
  const scopeSeg = (scope, attr) => `<div class="scope-seg" role="group" aria-label="${esc(t("period"))}">${["term", "career"].map((k) =>
    `<button type="button" ${attr}="${k}" aria-pressed="${k === scope}">${t(`scope_${k}`)}</button>`).join("")}</div>`;

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (el.hidden = true), 2400);
  }

  async function getJSON(path) {
    const res = await fetch(`data/${path}`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  }

  // ------------------------------------------------------------ location
  // Island group, region, province and city come from geo.js, since most
  // sources only give a province (or a city in its place).
  const GEO = window.PILI_GEO;
  function withLoc(o) {
    o._loc = GEO.locate(o);
    o._dist = districtOf(o);
    return o;
  }
  const locWords = (o) => [o.province, o.lgu, o.region, o._loc.province, o._loc.city, o._loc.region,
    o._loc.island && t(`island_${o._loc.island}`), o._loc.island];
  // "Agusan del Sur–1st", "1St", "Pasig at-large" -> "1", "1", "lone"
  function districtOf(o) {
    const d = String(o.district || "");
    if (!d || /nationwide|party-?list/i.test(d)) return "";
    if (/at-?large|\blone\b/i.test(d)) return "lone";
    const m = d.match(/(\d+)\s*(?:st|nd|rd|th)?(?:\s*district)?\s*$/i);
    return m ? String(+m[1]) : "";
  }
  const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 >> 3 ^ 1) && n % 10] || "th");
  const districtLabel = (k) => (k === "lone" ? t("district_lone") : t("district_n", { n: k, nth: ordinal(+k) }));

  function addRecords(records, dataset) {
    for (const r of records || []) {
      const o = withLoc({ ...r, dataset });
      o._s = norm([r.name, r.position, r.party, r.district, r.barangay, ...locWords(o)].join(" "));
      state.byKey.set(key(o), o);
      // Former Presidents and VPs are on their own page, not in the directory.
      (isPast(o) ? state.pastExec : state.officials).push(o);
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
    const tasks = ["executive", "senate", "house", "lgu"].filter((k) => ds[k]?.count).map(async (k) => {
      try {
        const doc = await getJSON(ds[k].file);
        addRecords(doc.records, k);
        if (k === "lgu") state.lgus = doc.lgus || [];
        if (k === "senate") state.billsSource = doc.bills_source || null;
      } catch (e) {
        console.warn(e);
      }
    });
    if (ds.barangay?.count) {
      tasks.push(getJSON(ds.barangay.file).then((d) => (state.brgyIndex = d)).catch(console.warn));
    }
    await Promise.all(tasks);
    const order = ["president", "vice_president", "senate", "house", "governor", "vice_governor", "mayor", "vice_mayor", "board_member", "councilor"];
    state.officials.sort((a, b) => (order.indexOf(a.level) + 1 || 99) - (order.indexOf(b.level) + 1 || 99) || a.name.localeCompare(b.name));
    restoreCompare();
    state.loading = false;
    render();
  }

  async function loadBrgyFile(file) {
    if (state.brgyFiles.has(file)) return state.brgyFiles.get(file);
    const doc = await getJSON(file);
    const recs = doc.records.map((r) => {
      const o = withLoc({ ...r, dataset: "barangay", _file: file });
      o._s = norm([r.name, r.position, r.barangay, ...locWords(o)].join(" "));
      return o;
    });
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
      <b>${t("no_data_title")}</b><br>${t("no_data_body")}
      <p class="meta">${t("no_data_sources")} <a href="#/ako">${t("tab_ako")}</a>.</p></div>`;
  }

  // --------------------------------------------------------------- views
  // Search box with a Filter button; the filters live in a panel that opens
  // below it, and the ones in use show as removable tags.
  const FILTER_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4"/></svg>';
  function searchBar({ id, value, placeholder, label, count, open, panelId }) {
    return `<div class="searchbar">
      <input class="search" id="${id}" type="search" placeholder="${esc(placeholder)}" value="${esc(value)}" aria-label="${esc(label)}">
      <button type="button" class="filter-btn${count ? " on" : ""}" id="${id}-filter" aria-expanded="${open}" aria-controls="${panelId}">
        ${FILTER_ICON}<span class="fb-text">${t("filter_btn")}</span>${count ? `<span class="fb-count">${count}</span>` : ""}
      </button>
    </div>`;
  }
  const filterTags = (tags) => (tags.length
    ? `<div class="filter-tags">${tags.map(([k, text]) => `<button type="button" class="ftag" data-rm="${esc(k)}" aria-label="${esc(t("remove_filter", { f: text }))}">${esc(text)} <span aria-hidden="true">✕</span></button>`).join("")}<button type="button" class="link-btn" data-rm="*">${t("clear_filters")}</button></div>`
    : "");
  const panelFoot = (panelId) => `<div class="fp-foot"><button type="button" class="link-btn" data-fp-reset>${t("clear_filters")}</button><button type="button" class="btn primary" data-fp-done="${panelId}">${t("show_results")}</button></div>`;
  function wireSearch(id, { get, set, rerender, toggle }) {
    const input = $("#" + id);
    input.addEventListener("input", () => {
      set(input.value);
      const pos = input.selectionStart;
      Promise.resolve(rerender()).then(() => { const i2 = $("#" + id); i2.focus(); i2.setSelectionRange(pos, pos); });
    });
    $(`#${id}-filter`).addEventListener("click", () => { toggle(); rerender(); });
  }

  function viewHome() {
    const f = FILTERS.find((x) => x[0] === state.filter) || FILTERS[0];
    const q = norm(state.q).trim();
    const terms = q.split(/\s+/).filter(Boolean);
    let list = state.officials.filter(f[1]).filter((o) => !state.island || o._loc.island === state.island)
      .filter((o) => terms.every((w) => o._s.includes(w)));
    const bySort = state.sort !== "name";
    if (bySort) {
      const val = (o) => rankValue(o) ?? -1;
      list = list.filter((o) => o.level === "senate")
        .sort((a, b) => val(b) - val(a) || a.name.localeCompare(b.name));
    }
    const brgyNote = state.filter === "brgy";

    const tags = [];
    if (state.filter !== "all") tags.push(["f", t(`f_${state.filter}`)]);
    if (state.island) tags.push(["island", t(`island_${state.island}`)]);
    if (bySort) tags.push(["sort", `${t(`sort_${state.sort}`)} · ${t(`scope_${state.scope}`)}`]);
    if (bySort && state.sector) tags.push(["sector", t(`sec_${state.sector}`)]);
    // Sectors with bills in this period, busiest first, with totals across senators.
    const senators = state.officials.filter((o) => o.level === "senate");
    const sectorTotals = bySort ? sectorKeys().map((k) => [k, senators.reduce((sum, o) => sum + sectorCount(o, k), 0)])
      .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]) : [];
    const sectorSelect = () => `<label class="sector-pick"><span>${t("sector")}</span><select class="select" id="sector-select">
      <option value="">${t("all_sectors")}</option>${sectorTotals.map(([k, n]) => `<option value="${k}" ${k === state.sector ? "selected" : ""}>${esc(t(`sec_${k}`))} (${fmtNum(n)})</option>`).join("")}</select></label>`;
    view.innerHTML = `
      ${searchBar({ id: "q", value: state.q, placeholder: t("search_ph"), label: t("search_label"), count: tags.length, open: state.filtersOpen, panelId: "home-filters" })}
      <div class="filter-panel" id="home-filters" ${state.filtersOpen ? "" : "hidden"}>
        <div class="fp-label">${t("position")}</div>
        <div class="chips wrap" role="group" aria-label="${esc(t("position"))}">${FILTERS.map(([k]) => `<button class="chip" data-f="${k}" aria-pressed="${k === state.filter}">${t(`f_${k}`)}</button>`).join("")}</div>
        <div class="fp-label">${t("island")}</div>
        <div class="chips wrap" role="group" aria-label="${esc(t("island"))}">${["", ...GEO.islands].map((k) => `<button class="chip" data-island="${k}" aria-pressed="${k === state.island}">${t(k ? `island_${k}` : "island_all")}</button>`).join("")}</div>
        <a class="fp-more" href="#/hanap">📍 ${t("more_place")}</a>
        <div class="fp-label">${t("sort_by")}</div>
        <div class="chips wrap" role="group" aria-label="${esc(t("sort_by"))}">${SORTS.filter((k) => k !== "law" || state.scope === "career").map((k) => `<button class="chip" data-sort="${k}" aria-pressed="${k === state.sort}">${t(`sort_${k}`)}</button>`).join("")}</div>
        <div class="fp-label">${t("period")}</div>
        ${scopeSeg(state.scope, "data-scope")}
        ${bySort ? `<div class="fp-label">${t("sector")}</div>
        <div class="chips wrap" role="group" aria-label="${esc(t("sector"))}"><button class="chip" data-sector="" aria-pressed="${!state.sector}">${t("all_sectors")}</button>${sectorTotals.map(([k, n]) => `<button class="chip" data-sector="${k}" aria-pressed="${k === state.sector}">${esc(t(`sec_${k}`))} <span class="chip-n">${fmtNum(n)}</span></button>`).join("")}</div>` : ""}
        <p class="meta fp-hint">${t("sort_hint")}</p>
        ${panelFoot("home-filters")}
      </div>
      ${state.filtersOpen ? "" : filterTags(tags)}
      <div class="quick">
        <a href="#/ihambing"><span class="qi">⚖️</span><b>${t("quick_compare")}</b><small>${t("quick_compare_sub")}</small></a>
        <a href="#/pili"><span class="qi">🗳️</span><b>${t("quick_list")}</b><small>${t("quick_list_sub")}</small></a>
        <a href="#/ako"><span class="qi">📊</span><b>${t("quick_stats")}</b><small>${t("quick_stats_sub")}</small></a>
      </div>
      <div id="results"></div>`;

    const results = $("#results");
    if (state.loading) {
      results.innerHTML = `<div class="section-label">${t("loading")}</div>` + '<div class="skeleton"></div>'.repeat(6);
    } else if (!hasData()) {
      results.innerHTML = noData();
    } else if (brgyNote) {
      results.innerHTML = `<div class="empty"><span class="ei">🏘️</span>${t("brgy_note", { n: fmtNum(state.brgyIndex?.count) })}<br>${t("brgy_note2", { link: `<a href="#/hanap">${t("tab_hanap")}</a>` })}</div>`;
    } else {
      // Ranked rows: the name opens the profile, the number opens the bills by term.
      const rankRow = (o, i) => {
        const v = rankValue(o);
        return `<div class="row rank-row"><span class="num">${i + 1}</span>
          <a class="rank-main" href="#/o/senate/${encodeURIComponent(o.id)}">${avatar(o)}<span class="who"><b>${esc(o.name)}</b><span>${esc(serviceText(o) || levelLabel(o))}</span></span></a>
          <a class="bill-count" href="${billsHref(o)}" aria-label="${esc(t("open_bills", { name: o.name }))}"><b>${v == null ? "—" : fmtNum(v)}</b><small>${t(`count_${sortKey()}`)}</small></a>
        </div>`;
      };
      results.innerHTML = `${bySort ? `${scopeSeg(state.scope, "data-scope")}${sectorSelect()}` : ""}<div class="section-label">${bySort ? esc(`${t(`sort_${state.sort}`)} · ${t(`scope_${state.scope}`)}${state.sector ? ` · ${t(`sec_${state.sector}`)}` : ""}`) : esc(t(`f_${f[0]}`))}${state.island ? " · " + esc(t(`island_${state.island}`)) : ""} · ${t("n_officials", { n: fmtNum(list.length) })}</div>
        ${f[0] === "exec" && !bySort ? `<p><a class="btn block" href="#/pangulo">${t("exec_history_link")}</a></p>` : ""}
        ${bySort ? `<div class="notice rank-note"><b>${t("rank_caveat_title")}</b> ${t(`period_${sortKey()}`, { d: fmtDate(state.billsSource?.as_of) })} ${t("rank_caveat")}${state.sector ? ` ${t("sector_note")}${state.sector === "transport" ? ` ${t("transport_note")}` : ""}` : ""}</div>${billsNote()}` : ""}
        <div class="list${bySort ? " ranked" : ""}">${list.slice(0, state.shown).map((o, i) => (bySort ? rankRow(o, i) : row(o))).join("") || `<div class="empty">${t("no_match", { q: esc(state.q) })}</div>`}</div>
        ${list.length > state.shown ? `<button class="btn more" id="more">${t("show_more", { n: fmtNum(list.length - state.shown) })}</button>` : ""}`;
    }

    wireSearch("q", { set: (v) => { state.q = v; state.shown = PAGE; }, rerender: viewHome, toggle: () => (state.filtersOpen = !state.filtersOpen) });
    view.querySelectorAll("[data-scope]").forEach((b) => b.addEventListener("click", () => {
      state.scope = b.dataset.scope;
      if (state.scope === "term" && state.sort === "law") state.sort = "filed";
      if (state.sort === "name") { state.sort = "filed"; state.filter = "senate"; }
      state.shown = PAGE;
      viewHome();
    }));
    const pickSector = (k) => { state.sector = k; state.shown = PAGE; viewHome(); };
    view.querySelectorAll(".chip[data-sector]").forEach((b) => b.addEventListener("click", () => pickSector(b.dataset.sector)));
    $("#sector-select")?.addEventListener("change", (e) => pickSector(e.target.value));
    view.querySelectorAll(".chip[data-sort]").forEach((b) => b.addEventListener("click", () => {
      state.sort = b.dataset.sort;
      if (state.sort !== "name") state.filter = "senate";
      state.shown = PAGE;
      viewHome();
    }));
    const clearHome = (k) => {
      if (k === "sort" || k === "*") { state.sort = "name"; state.scope = "term"; state.sector = ""; }
      if (k === "sector") state.sector = "";
      if (k === "f" || k === "*") state.filter = "all";
      if (k === "island" || k === "*") { state.island = ""; HANAP_ORDER.forEach((kk) => (hanap[kk] = "")); }
      state.shown = PAGE;
      viewHome();
    };
    view.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => clearHome(b.dataset.rm)));
    view.querySelector("[data-fp-reset]")?.addEventListener("click", () => clearHome("*"));
    view.querySelector("[data-fp-done]")?.addEventListener("click", () => { state.filtersOpen = false; viewHome(); });
    view.querySelectorAll(".chip[data-f]").forEach((b) => b.addEventListener("click", () => {
      state.filter = b.dataset.f;
      if (!["senate", "all"].includes(state.filter)) state.sort = "name";
      state.shown = PAGE;
      viewHome();
    }));
    view.querySelectorAll(".chip[data-island]").forEach((b) => b.addEventListener("click", () => {
      state.island = b.dataset.island;
      if (hanap.island !== state.island) HANAP_ORDER.forEach((k) => (hanap[k] = ""));
      hanap.island = state.island;
      state.shown = PAGE;
      viewHome();
    }));
    $("#more")?.addEventListener("click", () => { state.shown += PAGE * 2; viewHome(); });
  }

  // Find by place: island group -> region -> province -> city/municipality
  // -> district -> barangay, plus a free-text search.
  const hanap = { island: "", region: "", province: "", lgu: "", district: "", barangay: "", q: "", open: false };
  const HANAP_ORDER = ["island", "region", "province", "lgu", "district", "barangay"];
  async function viewHanap() {
    if (state.loading) { view.innerHTML = '<div class="skeleton"></div>'.repeat(4); return; }
    if (!hasData()) { view.innerHTML = noData(); return; }
    const h = hanap;
    const brgyFiles = (state.brgyIndex?.files || []).map((f) => ({ ...f, _loc: GEO.locate({ province: f.province, region: f.region, lgu: f.province ? "" : (f.lgus || [])[0] }) }));

    // Each step narrows the pool the next dropdown is built from.
    const steps = {
      island: (o) => !h.island || o._loc.island === h.island,
      region: (o) => !h.region || o._loc.region === h.region,
      province: (o) => !h.province || o._loc.province === h.province,
      lgu: (o) => !h.lgu || o._loc.city === h.lgu,
      district: (o) => !h.district || o._dist === h.district,
      barangay: (o) => !h.barangay || o.barangay === h.barangay,
    };
    const upTo = (k) => (o) => HANAP_ORDER.slice(0, HANAP_ORDER.indexOf(k)).every((s) => steps[s](o));

    let brgyRecs = [];
    const files = brgyFiles.filter((f) => upTo("lgu")(f) && h.province);
    if (files.length) {
      view.innerHTML = '<div class="skeleton"></div>'.repeat(4);
      brgyRecs = (await Promise.all(files.map((f) => loadBrgyFile(f.file).catch(() => [])))).flat();
    }
    const pool = [...state.officials.filter((o) => o.level !== "senate" && o._loc.island), ...brgyRecs];
    const values = (k, get) => new Set([...pool, ...(k === "province" || k === "region" ? brgyFiles : [])].filter(upTo(k)).map(get).filter(Boolean));
    const regions = values("region", (o) => o._loc.region);
    const provinces = values("province", (o) => o._loc.province);
    const lgus = values("lgu", (o) => o._loc.city);
    const districts = h.province ? values("district", (o) => o._dist) : new Set();
    const brgys = values("barangay", (o) => o.barangay);

    const terms = norm(h.q).split(/\s+/).filter(Boolean);
    const anyFilter = HANAP_ORDER.some((k) => h[k]) || terms.length;
    const list = anyFilter ? pool.filter((o) => HANAP_ORDER.every((k) => steps[k](o)) && terms.every((w) => o._s.includes(w))) : [];

    const sorted = (set, by) => [...set].sort(by || ((a, b) => a.localeCompare(b)));
    const opt = (items, cur, all, label = (v) => v) => `<option value="">${esc(all)}</option>` + items.map((v) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label(v))}</option>`).join("");
    const regionOrder = GEO.regionsOf("");
    const brgyNote = !brgyFiles.length ? t("no_brgy_data") : h.province ? t("all_brgys") : t("pick_province_first");

    const placeTags = HANAP_ORDER.filter((k) => h[k]).map((k) => [k,
      k === "island" ? t(`island_${h.island}`) : k === "district" ? districtLabel(h.district) : k === "barangay" ? `Brgy. ${h.barangay}` : h[k]]);
    view.innerHTML = `
      ${searchBar({ id: "place-q", value: h.q, placeholder: t("place_search_ph"), label: t("place_search_ph"), count: placeTags.length, open: h.open, panelId: "place-filters" })}
      <div class="filter-panel" id="place-filters" ${h.open ? "" : "hidden"}>
      <div class="fp-label">${t("island")}</div>
      <div class="chips wrap" role="group" aria-label="${esc(t("island"))}">${["", ...GEO.islands].map((k) => `<button class="chip" data-island="${k}" aria-pressed="${k === h.island}">${t(k ? `island_${k}` : "island_all")}</button>`).join("")}</div>
      <div class="place-grid">
        <label><span>${t("region")}</span><select class="select" data-k="region">${opt(sorted(regions, (a, b) => regionOrder.indexOf(a) - regionOrder.indexOf(b)), h.region, t("all_regions"))}</select></label>
        <label><span>${t("province")}</span><select class="select" data-k="province">${opt(sorted(provinces), h.province, t("all_provinces"))}</select></label>
        <label><span>${t("lgu")}</span><select class="select" data-k="lgu" ${lgus.size ? "" : "disabled"}>${opt(sorted(lgus), h.lgu, t("all_lgus"))}</select></label>
        <label><span>${t("district")}</span><select class="select" data-k="district" ${districts.size ? "" : "disabled"}>${opt(sorted(districts, (a, b) => (a === "lone" ? -1 : b === "lone" ? 1 : a - b)), h.district, h.province ? t("all_districts") : t("pick_province_district"), districtLabel)}</select></label>
        <label class="wide"><span>${t("barangay")}</span><select class="select" data-k="barangay" ${brgys.size ? "" : "disabled"}>${opt(sorted(brgys), h.barangay, brgys.size ? t("all_brgys") : brgyNote)}</select></label>
      </div>
      ${panelFoot("place-filters")}
      </div>
      ${h.open ? "" : filterTags(placeTags)}
      ${anyFilter ? `<div class="place-head"><div class="section-label">${t("n_officials", { n: fmtNum(list.length) })}</div></div>
        <div class="list">${list.slice(0, 400).map((o) => row(o)).join("") || `<div class="empty">${t("none_here")}</div>`}</div>${list.length > 400 ? `<p class="meta">${t("first_400")}</p>` : ""}`
        : `<div class="empty"><span class="ei">📍</span>${t("hanap_hint")}<br><br>${t("hanap_senators", { link: `<a href="#/">${t("tab_home")}</a>` })}</div>`}`;

    view.querySelectorAll("select[data-k]").forEach((sel) => sel.addEventListener("change", () => {
      const k = sel.dataset.k;
      h[k] = sel.value;
      HANAP_ORDER.slice(HANAP_ORDER.indexOf(k) + 1).forEach((kk) => (h[kk] = ""));
      // Picking a province fills in its region and island group.
      if (k === "province" && h.province) {
        const any = [...pool, ...brgyFiles].find((o) => o._loc.province === h.province);
        if (any) { h.island = any._loc.island; h.region = any._loc.region || h.region; }
      }
      if (k === "region" && h.region) h.island = GEO.islandOfRegion(h.region) || h.island;
      state.island = h.island;
      viewHanap();
    }));
    view.querySelectorAll(".chip[data-island]").forEach((b) => b.addEventListener("click", () => {
      HANAP_ORDER.forEach((k) => (h[k] = ""));
      h.island = b.dataset.island;
      state.island = h.island;
      viewHanap();
    }));
    wireSearch("place-q", { set: (v) => (h.q = v), rerender: viewHanap, toggle: () => (h.open = !h.open) });
    // Removing a place also clears the narrower ones under it.
    const clearPlace = (k) => {
      const from = k === "*" ? 0 : HANAP_ORDER.indexOf(k);
      HANAP_ORDER.slice(from).forEach((kk) => (h[kk] = ""));
      state.island = h.island;
      viewHanap();
    };
    view.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => clearPlace(b.dataset.rm)));
    view.querySelector("[data-fp-reset]")?.addEventListener("click", () => clearPlace("*"));
    view.querySelector("[data-fp-done]")?.addEventListener("click", () => { h.open = false; viewHanap(); });
  }

  async function viewProfile(dataset, id) {
    view.innerHTML = '<div class="skeleton" style="height:180px"></div>';
    const o = await findOfficial(dataset, id);
    if (!o) {
      view.innerHTML = `<div class="empty"><span class="ei">🤷</span>${t("not_found")}<br><a href="#/">${t("back_to_list")}</a></div>`;
      return;
    }
    setTitle(o.name);
    const rows = [
      [t("position"), levelLabel(o)],
      [t("party"), o.party],
      [t("district"), districtText(o)],
      [t("barangay"), o.barangay],
      [t("lgu"), o.lgu],
      [t("province"), o.province],
      [t("region"), o.region],
      [t("contact"), o.contact],
    ];
    // Local officials: consecutive term and whether the three-term limit
    // stops them running for the same post in 2028.
    const term = termOf(o);
    if (term) {
      rows.push([t("term_label"), t("term_nth", { n: term, nth: ordinal(term) })]);
      rows.push([t("in_2028"), term >= 3 ? t("term_limited") : t("can_run_again")]);
    }
    if (o.details?.full_name) rows.push([t("full_name"), tidyName(o.details.full_name)]);
    if (o.dataset === "barangay") rows.push([t("in_office"), t("brgy_term")]);
    if (EXEC_LEVELS.has(o.level)) {
      if (o.ordinal) rows.push([t("exec_order"), t("exec_nth", { n: o.ordinal, nth: ordinal(+o.ordinal || 0) })]);
      if (o.details?.term) rows.push([t(isPast(o) ? "exec_years" : "term_label"), o.details.term]);
      if ((o.terms || []).length > 1) rows.push([t("exec_terms"), o.terms.map(termSpan).join("; ")]);
      if (!isPast(o)) rows.push([t("in_2028"), o.level === "president" ? t("pres_not_eligible")
        : (o.successive_terms || 1) >= 2 ? t("vp_limit") : t("vp_can_run")]);
    }
    if (o.service?.first_senate_year) {
      rows.push([t("cmp_since"), `${o.service.first_senate_year} (${congressName(o.service.first_senate_congress)})`]);
      rows.push([t("cmp_terms"), `${o.service.senate_terms} · ${congressRanges(o.service.senate_congresses)}`]);
    }
    const d = o.details || {};
    if (d.address) rows.push([t("office"), d.address]);
    const skip = new Set(["title", "position_raw", "address", "biography", "resume", "created_at", "updated_at", "deleted_at", "wikipedia_revision", "copied_on", "published_via", "term", "term_source", "term_years", "elected", "full_name"]);
    const extra = Object.entries(d).filter(([k, v]) => v && !skip.has(k) && !(k === "prior_experience" && o.career) && !/^line\d|href|photo|image|img|^id$|_id$|slug/.test(k) && !rows.some(([, rv]) => rv === v));
    const pretty = (k) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    const cv = safeUrl(d.resume);
    const inBallot = Object.values(getBallot()).some((arr) => arr.includes(key(o)));
    const nAch = cleanAch(o.achievements).length;

    view.innerHTML = `<div class="profile-layout"><div class="profile-side">
      <div class="profile-head">
        ${avatar(o, "lg")}
        <h1>${esc(o.name)}</h1>
        <p>${esc(levelLabel(o))}</p>
        <div class="badges">
          ${o.party ? `<span class="badge">${esc(o.party)}</span>` : ""}
          ${typeBadge(typeOf(o), /saved copy/i.test(o.source) ? t("type_copy") : "")}
        </div>
      </div>
      <div class="btn-row">
        <button class="btn" id="cmp">${t("compare_btn")}</button>
        <button class="btn primary" id="pick">${inBallot ? t("in_ballot") : t("add_ballot")}</button>
      </div></div><div class="profile-main">
      <div class="section-label">${t("info")}</div>
      <table class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("")}
        ${extra.slice(0, 20).map(([k, v]) => `<tr><th>${esc(pretty(k))}</th><td>${esc(v)}</td></tr>`).join("")}</table>
      ${o.summary ? `<div class="section-label">${t("exec_summary")}</div><p class="bio">${esc(o.summary)}</p>
        <p class="meta">${t("exec_summary_src")} <a href="${esc(safeUrl(o.summary_source))}" target="_blank" rel="noopener">${t("wikipedia_article")} ↗</a></p>` : ""}
      ${o.laws_note === "before_data" ? `<div class="section-label">${t("laws_title_past")}</div><p class="meta">${t("laws_before_data")}</p>` : ""}
      ${(o.career || []).length ? `<div class="section-label">${t("career_title")}</div>
        <ol class="career">${[...o.career].reverse().map((c) => `<li><b>${esc(c.title)}</b>${c.place ? ` · ${esc(c.place)}` : ""}<span class="meta">${esc(careerSpan(c))}</span></li>`).join("")}</ol>` : ""}
      ${o.laws_signed != null ? `<div class="section-label">${isPast(o) ? t("laws_title_past") : t("laws_title", { y: (o.laws_from || "").slice(0, 4) })}</div>
        <div class="service">
          <div class="service-item"><b>${fmtNum(o.laws_signed)}</b><span>${t("laws_signed")}</span></div>
          <div class="service-item"><b>${fmtNum(o.laws_lapsed)}</b><span>${t("laws_lapsed")}</span></div>
        </div>
        <p class="meta">${isPast(o) ? t("laws_note_past", { a: fmtDate(o.laws_from), b: fmtDate(o.laws_to) }) : t("laws_note", { d: fmtDate(o.laws_as_of) })}${o.laws_note === "partial" ? ` ${t("laws_partial")}` : ""}</p>
        <p><a class="btn block" href="#/laws/${encodeURIComponent(o.id)}">${t("see_laws", { n: fmtNum(o.laws_signed + o.laws_lapsed) })}</a></p>` : ""}
      ${nAch ? `<div class="section-label">${t("achievements_n", { n: nAch })}</div>${groupAchievements(o.achievements).map(([g, items]) => `<div class="ach-group">${esc(t(g))} · ${items.length}</div><ul class="bullets">${items.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`).join("")}` : ""}
      ${(o.bills || []).length ? `<div class="section-label">${t("bills_n", { n: fmtNum(o.bills_count || o.bills.length) })}</div>
        <p class="meta bill-split">${t("bill_split", { main: fmtNum(billStats(o).main), co: fmtNum(billStats(o).co) })} · <a href="#/" data-rank-link>${t("see_ranking")}</a></p>
        ${o.bills_file ? `<div class="btn-row"><a class="btn" href="#/bills/${encodeURIComponent(o.id)}">${t("see_term_bills", { n: fmtNum(o.bills_count) })}</a><a class="btn" href="#/bills/${encodeURIComponent(o.id)}/career">${t("see_all_terms", { n: fmtNum(o.bills_all) })}</a></div>` : ""}
        ${billsNote()}
        <details class="bills-more"${o.bills.length <= 10 ? " open" : ""}><summary>${t("see_bills", { n: fmtNum(o.bills.length) })}</summary>
        <ul class="bills">${o.bills.map((b) => `<li>${safeUrl(b.url) ? `<a href="${esc(b.url)}" target="_blank" rel="noopener">` : ""}<b>${esc(b.number || "")}</b> ${esc(b.title || "")}${safeUrl(b.url) ? "</a>" : ""}${b.coauthored ? `<span class="meta"> · ${t("coauthor")}</span>` : ""}${b.status ? `<span class="meta"> · ${esc(b.status)}</span>` : ""}${b.date ? `<span class="meta"> · ${t("filed", { d: esc(b.date) })}</span>` : ""}</li>`).join("")}</ul></details>` : ""}
      ${d.biography ? `<div class="section-label">${t("biography")}</div><p class="bio">${esc(d.biography)}</p>` : ""}
      ${cv ? `<p><a class="btn block" href="${esc(cv)}" target="_blank" rel="noopener">${t("official_cv")}</a></p>` : ""}
      <div class="notice">
        ${t("source")}: <a href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener">${esc(o.source)}</a> (${typeLabel(typeOf(o))})
        ${safeUrl(o.profile_url) ? ` · <a href="${esc(o.profile_url)}" target="_blank" rel="noopener">${/wikipedia\.org/.test(o.profile_url) ? t("wikipedia_article") : t("official_profile")} ↗</a>` : ""}
        ${/openhalalan/i.test(o.source) ? `<br>${t("oh_note")}` : ""}
        <br>${t("last_updated")}: ${fmtDate(datasetDate(o.dataset, o._file))}${d.copied_on ? ` · ${t("copied_on", { d: fmtDate(d.copied_on) })}` : ""}
        <br><a href="#/report/${encodeURIComponent(o.dataset)}/${encodeURIComponent(o.id)}">⚑ ${t("report_this")}</a>
      </div></div></div>`;

    view.querySelector("[data-rank-link]")?.addEventListener("click", (e) => {
      e.preventDefault();
      Object.assign(state, { sort: "filed", scope: "term", sector: "", filter: "senate", island: "", q: "", shown: PAGE });
      location.hash = "#/";
    });
    $("#cmp").addEventListener("click", () => {
      const slot = state.compare[0] ? 1 : 0;
      state.compare[slot] = o;
      saveCompare();
      location.hash = "#/ihambing";
    });
    $("#pick").addEventListener("click", () => {
      const slot = BALLOT_SLOTS.find((s) => s.hint?.(o)) || BALLOT_SLOTS[BALLOT_SLOTS.length - 1];
      if (addToBallot(slot.key, o)) toast(t("added_to", { slot: slotLabel(slot) }));
      viewProfile(dataset, id);
    });
  }

  // Every bill a senator filed, by term (Congress) and year, from the
  // per-senator file written by the scraper.
  const billsView = { id: "", q: "", show: "all", sector: "" };
  async function viewBills(id, scope = "term", sector = "") {
    view.innerHTML = '<div class="skeleton" style="height:160px"></div>'.repeat(2);
    const o = await findOfficial("senate", id);
    if (!o || !o.bills_file) {
      view.innerHTML = `<div class="empty"><span class="ei">🤷</span>${t("not_found")}<br><a href="#/">${t("back_to_list")}</a></div>`;
      return;
    }
    if (billsView.id !== id) Object.assign(billsView, { id, q: "", show: "all" });
    billsView.sector = sector;
    if (scope === "term" && billsView.show === "law") billsView.show = "all";
    setTitle(t("bills_page_title"));
    let doc;
    try { doc = await getJSON(o.bills_file); } catch (e) {
      view.innerHTML = `<div class="empty">${t("no_data_short")}</div>`;
      return;
    }
    const career = scope === "career";
    const s = o.service || {};
    const cur = currentCongress();
    const asOf = fmtDate(doc.as_of);
    const byCongress = new Map(doc.terms.map((x) => [x.congress, x]));
    // Every Senate Congress, newest first, including service before the data starts.
    const congresses = [...new Set([...(s.senate_congresses || []), ...doc.terms.map((x) => x.congress)])].sort((a, b) => b - a);
    const first = state.billsSource?.first_congress || 13;
    const totals = doc.terms.reduce((acc, x) => ({ filed: acc.filed + x.filed, main: acc.main + x.main, law: acc.law + x.law }), { filed: 0, main: 0, law: 0 });
    const now = byCongress.get(cur) || { filed: 0, main: 0, bills: [] };
    const shownTerms = career ? doc.terms : doc.terms.filter((x) => x.congress === cur);
    // With a sector chosen, the per-term table counts only that sector's bills.
    const inSector = (b) => !billsView.sector || (b.sector || "other") === billsView.sector;
    const termCount = (x) => (billsView.sector ? {
      filed: x.bills.filter(inSector).length,
      main: x.bills.filter((b) => inSector(b) && b.role === "main").length,
      law: x.bills.filter((b) => inSector(b) && b.law).length,
    } : x);
    const sectorCounts = new Map();
    shownTerms.forEach((x) => x.bills.forEach((b) => sectorCounts.set(b.sector || "other", (sectorCounts.get(b.sector || "other") || 0) + 1)));
    const stat = (v, label) => `<div class="service-item"><b>${v}</b><span>${label}</span></div>`;

    view.innerHTML = `
      <div class="bills-head">
        <a class="bills-who" href="#/o/senate/${encodeURIComponent(o.id)}">${avatar(o)}<span><b>${esc(o.name)}</b><span>${esc(levelLabel(o))}</span></span></a>
        ${scopeSeg(scope, "data-bscope")}
        <div class="service">
          ${stat(s.first_senate_year || "—", t("cmp_since"))}
          ${stat(s.senate_terms ?? "—", t("cmp_terms"))}
          ${career ? stat(fmtNum(totals.filed), t("count_bills_all")) + stat(fmtNum(totals.law), t("col_law"))
            : stat(fmtNum(now.filed), t("filed_this_term")) + stat(fmtNum(now.main), t("col_main"))}
        </div>
        <p class="meta">${t("in_senate")}: ${esc(congressRanges(s.senate_congresses || []))}${(s.house_congresses || []).length ? ` · ${t("house_note", { list: esc(congressRanges(s.house_congresses)) })}` : ""}</p>
      </div>
      <div class="notice">${career ? t("bills_page_note", { first: congressName(first), y: congressStart(first) }) : t("term_view_note", { d: asOf })}</div>
      ${billsNote()}
      ${career ? `<div class="section-label">${t("per_term")}${billsView.sector ? ` · ${esc(t(`sec_${billsView.sector}`))}` : ""}</div>
      <div class="table-wrap"><table class="terms">
        <thead><tr><th>${t("col_term")}</th><th class="n">${t("col_filed")}</th><th class="n">${t("col_main")}</th><th class="n">${t("col_law")}</th></tr></thead>
        <tbody>${congresses.map((c) => {
          const raw = byCongress.get(c);
          const x = raw && { ...raw, ...termCount(raw) };
          const note = `<small>${esc((x && x.years) || congressYears(c))}${c === cur ? ` · ${t("in_progress", { d: asOf })}` : ""}</small>`;
          return x
            ? `<tr><td><button type="button" class="link-btn" data-jump="${c}">${congressName(c)}</button>${note}</td><td class="n">${fmtNum(x.filed)}</td><td class="n">${fmtNum(x.main)}</td><td class="n">${c === cur ? "—" : fmtNum(x.law)}</td></tr>`
            : `<tr class="nodata"><td>${congressName(c)}${note}</td><td colspan="3">${c < first ? t("no_bill_data", { y: congressStart(first) }) : "0"}</td></tr>`;
        }).join("")}</tbody>
      </table></div>` : ""}
      <div class="bills-tools">
        <input class="search" id="bills-q" type="search" placeholder="${esc(t("bills_search_ph"))}" value="${esc(billsView.q)}" aria-label="${esc(t("bills_search_ph"))}">
        <div class="chips wrap" role="group">${(career ? ["all", "main", "law"] : ["all", "main"]).map((k) => `<button class="chip" data-show="${k}" aria-pressed="${k === billsView.show}">${t(`bills_filter_${k}`)}</button>`).join("")}</div>
        <label class="sector-pick"><span>${t("sector")}</span><select class="select" id="bills-sector">
          <option value="">${t("all_sectors")}</option>${[...sectorCounts].sort((a, b) => b[1] - a[1]).map(([k, n]) => `<option value="${k}" ${k === billsView.sector ? "selected" : ""}>${esc(t(`sec_${k}`))} (${fmtNum(n)})</option>`).join("")}</select></label>
        ${billsView.sector ? `<p class="meta">${t("sector_note")}${billsView.sector === "transport" ? ` ${t("transport_note")}` : ""}</p>` : ""}
      </div>
      <div id="bill-sections"></div>
      ${career ? "" : `<p><a class="btn block" href="${billsHref(o, "career", billsView.sector)}">${t("see_career", { n: fmtNum(totals.filed), l: fmtNum(totals.law) })}</a></p>`}`;

    const drawSections = () => {
      const terms = norm(billsView.q).split(/\s+/).filter(Boolean);
      const keep = (b) => (billsView.show === "all" || (billsView.show === "main" ? b.role === "main" : b.law))
        && (!billsView.sector || (b.sector || "other") === billsView.sector)
        && terms.every((w) => norm(`${b.number} ${b.title} ${b.status}`).includes(w));
      const filtering = terms.length || billsView.show !== "all" || billsView.sector;
      $("#bill-sections").innerHTML = shownTerms.map((x, i) => {
        const bills = x.bills.filter(keep);
        if (filtering && !bills.length) return "";
        const years = new Map();
        bills.forEach((b) => {
          const y = (b.date || "").slice(0, 4) || t("no_date");
          if (!years.has(y)) years.set(y, []);
          years.get(y).push(b);
        });
        return `<details class="term" id="term-${x.congress}"${i === 0 || filtering ? " open" : ""}>
          <summary><b>${congressName(x.congress)}</b> <span class="meta">${esc(x.years || congressYears(x.congress))}</span><span class="term-count">${t(bills.length === 1 ? "n_bill_one" : "n_bills_short", { n: fmtNum(bills.length) })}</span></summary>
          ${[...years].map(([y, list]) => `<div class="year-head">${esc(y)} · ${t(list.length === 1 ? "n_bill_one" : "n_bills_short", { n: fmtNum(list.length) })}</div>
            <ul class="bills">${list.map((b) => `<li>${safeUrl(b.url) ? `<a href="${esc(b.url)}" target="_blank" rel="noopener">` : ""}<b>${esc(b.number)}</b> ${esc(b.title)}${safeUrl(b.url) ? "</a>" : ""}
              <span class="bill-meta">${b.law ? `<span class="badge src-official">✓ ${t("law_badge")}</span> ` : ""}${b.role === "co" ? `<span class="meta">${t("role_co")} · </span>` : ""}<span class="meta">${t("filed", { d: esc(b.date || "—") })}${b.status && !b.law ? ` · ${esc(b.status)}` : ""}</span>${b.committee ? `<span class="meta bill-committee">${t("committee_x", { c: esc(b.committee) })}</span>` : ""}</span></li>`).join("")}</ul>`).join("")}
        </details>`;
      }).join("") || `<div class="empty">${career || now.filed ? t("no_match_short") : t("no_term_bills")}</div>`;
    };
    drawSections();
    $("#bills-q").addEventListener("input", (e) => { billsView.q = e.target.value; drawSections(); });
    $("#bills-sector").addEventListener("change", (e) => {
      history.replaceState(null, "", billsHref(o, scope, e.target.value));
      viewBills(id, scope, e.target.value);
    });
    view.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => {
      billsView.show = b.dataset.show;
      view.querySelectorAll("[data-show]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      drawSections();
    }));
    view.querySelectorAll("[data-bscope]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.bscope === scope) return;
      location.hash = billsHref(o, b.dataset.bscope, billsView.sector);
    }));
    view.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
      const el = $(`#term-${b.dataset.jump}`);
      if (el) { el.open = true; el.scrollIntoView({ behavior: "smooth", block: "start" }); }
    }));
  }

  // Laws of a President's term (Republic Acts dated from the day the term began).
  const lawsView = { q: "", show: "all" };
  async function viewLaws(id) {
    view.innerHTML = '<div class="skeleton" style="height:160px"></div>';
    const o = state.byKey.get(`executive/${id}`);
    if (!o) { view.innerHTML = `<div class="empty">${t("not_found")}</div>`; return; }
    setTitle(t("laws_page_title"));
    let doc;
    try { doc = await getJSON("laws.json"); } catch { view.innerHTML = `<div class="empty">${t("no_data_short")}</div>`; return; }
    const from = o.laws_from || o.details?.took_office || "";
    const to = o.laws_to || "";
    const all = doc.laws.filter((l) => l.date && l.date >= from && (!to || l.date < to)).reverse();
    view.innerHTML = `
      <div class="bills-head">
        <a class="bills-who" href="#/o/executive/${encodeURIComponent(o.id)}">${avatar(o)}<span><b>${esc(o.name)}</b><span>${esc(levelLabel(o))} · ${esc(o.details?.term || "")}</span></span></a>
      </div>
      <div class="notice">${to ? t("laws_page_note_past", { a: fmtDate(from), b: fmtDate(to) }) : t("laws_page_note", { d: fmtDate(from), as: fmtDate(doc.as_of) })}</div>
      <div class="bills-tools">
        <input class="search" id="laws-q" type="search" placeholder="${esc(t("laws_search_ph"))}" value="${esc(lawsView.q)}" aria-label="${esc(t("laws_search_ph"))}">
        <div class="chips wrap" role="group">${["all", "signed", "lapsed"].map((k) => `<button class="chip" data-lshow="${k}" aria-pressed="${k === lawsView.show}">${t(`laws_filter_${k}`)}</button>`).join("")}</div>
      </div>
      <div id="law-list"></div>`;
    const draw = () => {
      const terms = norm(lawsView.q).split(/\s+/).filter(Boolean);
      const list = all.filter((l) => (lawsView.show === "all" || (lawsView.show === "lapsed") === l.lapsed)
        && terms.every((w) => norm(`${l.ra} ${l.title}`).includes(w)));
      const years = new Map();
      list.forEach((l) => { const y = l.date.slice(0, 4); if (!years.has(y)) years.set(y, []); years.get(y).push(l); });
      $("#law-list").innerHTML = [...years].map(([y, ls]) => `<div class="year-head">${esc(y)} · ${t("n_laws", { n: fmtNum(ls.length) })}</div>
        <ul class="bills">${ls.map((l) => `<li>${safeUrl(l.url) ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">` : ""}<b>RA ${esc(l.ra)}</b> ${esc(l.title)}${safeUrl(l.url) ? "</a>" : ""}
          <span class="bill-meta">${l.lapsed ? `<span class="badge src-public">${t("laws_lapsed_badge")}</span> ` : ""}<span class="meta">${esc(fmtDate(l.date))} · ${esc(l.bill)}</span></span></li>`).join("")}</ul>`).join("")
        || `<div class="empty">${t("no_match_short")}</div>`;
    };
    draw();
    $("#laws-q").addEventListener("input", (e) => { lawsView.q = e.target.value; draw(); });
    view.querySelectorAll("[data-lshow]").forEach((b) => b.addEventListener("click", () => {
      lawsView.show = b.dataset.lshow;
      view.querySelectorAll("[data-lshow]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw();
    }));
  }

  function billsNote() {
    const b = state.billsSource;
    if (!b) return "";
    const src = `<a href="${esc(safeUrl(b.url))}" target="_blank" rel="noopener">${esc(b.name)}</a>`;
    return `<p class="notice" style="margin:0 0 8px">${typeBadge(b.source_type || "public")} ${t("bills_note", { src, d: fmtDate(b.as_of) })}</p>`;
  }

  function datasetDate(ds, file) {
    if (ds === "barangay" && file && state.brgyIndex) return state.brgyIndex.files.find((f) => f.file === file)?.scraped_at;
    return state.manifest?.datasets?.find((d) => d.key === ds)?.scraped_at;
  }

  // Time in office and laws per year, for comparing terms of different length.
  const daysIn = (o) => (o.terms || []).reduce((n, x) => n + ((x.end ? Date.parse(x.end) : Date.now()) - Date.parse(x.start)) / 86400000, 0);
  const yearsIn = (o) => { const d = daysIn(o); return d ? t("n_years", { n: (d / 365.25).toFixed(1) }) : ""; };
  function lawsPerYear(o) {
    if (o.laws_signed == null || !o.laws_from) return "";
    const days = ((o.laws_to ? Date.parse(o.laws_to) : Date.parse(o.laws_as_of || Date.now())) - Date.parse(o.laws_from)) / 86400000;
    return days > 180 ? `${((o.laws_signed + o.laws_lapsed) / (days / 365.25)).toFixed(0)}${o.laws_note === "partial" ? " *" : ""}` : "";
  }

  // Every President and Vice President, newest first; pick two to compare.
  const histView = { office: "president", pick: [] };
  function viewExecHistory() {
    const all = [...state.officials.filter((o) => EXEC_LEVELS.has(o.level)), ...state.pastExec];
    if (!all.length) { view.innerHTML = `<div class="empty">${t("no_data_short")}</div>`; return; }
    const list = all.filter((o) => o.level === histView.office)
      .sort((a, b) => (b.details?.took_office || "").localeCompare(a.details?.took_office || ""));
    const card = (o) => {
      const k = key(o), on = histView.pick.includes(k);
      const laws = o.laws_signed != null ? t("hist_laws", { n: fmtNum(o.laws_signed + o.laws_lapsed) }) + (o.laws_note === "partial" ? " *" : "")
        : o.laws_note === "before_data" || o.level === "president" ? t("hist_no_laws") : "";
      return `<li class="hist${on ? " picked" : ""}">
        <a class="row" href="#/o/executive/${encodeURIComponent(o.id)}">${avatar(o)}
          <span class="who"><b>${o.ordinal ? `${esc(t("exec_nth", { n: o.ordinal, nth: ordinal(+o.ordinal || 0) }))} · ` : ""}${esc(o.name)}</b>
          <span>${esc(o.details?.term || "")}${o.current === false ? "" : ` · ${t("hist_current")}`}${o.party ? ` · ${esc(o.party)}` : ""}${yearsIn(o) ? ` · ${esc(yearsIn(o))}` : ""}${laws ? ` · ${esc(laws)}` : ""}</span>
          ${o.summary ? `<span class="hist-sum">${esc(o.summary.length > 220 ? o.summary.slice(0, 220).replace(/\s+\S*$/, "") + "…" : o.summary)}</span>` : ""}</span></a>
        <button class="chip" data-hpick="${esc(k)}" aria-pressed="${on}">${on ? "✓ " : "＋ "}${t("hist_pick")}</button></li>`;
    };
    view.innerHTML = `
      <div class="section-label">${t("exec_history_title")}</div>
      <p class="meta" style="margin-top:-4px">${t("hist_lead")}</p>
      <div class="chips" role="group">${["president", "vice_president"].map((k) => `<button class="chip" data-office="${k}" aria-pressed="${k === histView.office}">${t(`hist_${k}`)}</button>`).join("")}</div>
      <div class="hist-bar"><span>${t("hist_picked", { n: histView.pick.length })}</span>
        <button class="btn primary" id="hist-go" ${histView.pick.length === 2 ? "" : "disabled"}>${t("hist_compare")}</button></div>
      <ul class="list hist-list">${list.map(card).join("")}</ul>
      <div class="notice">${t("hist_note")}</div>`;
    view.querySelectorAll("[data-office]").forEach((b) => b.addEventListener("click", () => { histView.office = b.dataset.office; viewExecHistory(); }));
    view.querySelectorAll("[data-hpick]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.hpick;
      histView.pick = histView.pick.includes(k) ? histView.pick.filter((x) => x !== k) : [...histView.pick, k].slice(-2);
      viewExecHistory();
    }));
    $("#hist-go").addEventListener("click", () => {
      state.compare = histView.pick.map((k) => state.byKey.get(k));
      histView.pick = [];
      saveCompare();
      location.hash = "#/ihambing";
    });
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

  // Achievements from official bios mix laws, awards, probes and past posts;
  // group them so profiles and comparisons stay like-for-like. Groups are
  // i18n keys.
  const ACH_GROUPS = [
    ["ach_laws", /\b(republic act|r\.?a\.? ?\d|act of \d{4}|\blaw\b|laws\b|authored|co-?author|sponsor|filed|\bbill\b|bills\b)/i],
    ["ach_awards", /\b(award|awardee|honoree|honou?r|best|outstanding|fellow|commended|finalist|medal|recogni|toym|hall of fame|honoris|most inspiring|10 outstanding)/i],
    ["ach_probes", /\b(investigat|hearing|irregularit|alleged|scam|probe|expos|anomal)/i],
    ["ach_posts", /\b(chair|member|leader|vice|deputy|spokesperson|officer|columnist|anchor|producer|newscaster|writer|disc jockey|publisher|president|secretary|director|head|mayor|governor|councilor|representative)/i],
  ];
  const cleanAch = (list) => (list || [])
    .map((x) => String(x).replace(/\s*<?\s*b?r\s*\/>\s*/gi, " ").replace(/^[\s\-–*•]+/, "").trim())
    .filter((x) => x && !/:\s*$/.test(x));
  function groupAchievements(list) {
    const groups = new Map([...ACH_GROUPS.map(([g]) => [g, []]), ["ach_other", []]]);
    for (const item of cleanAch(list)) {
      const hit = ACH_GROUPS.find(([, rx]) => rx.test(item));
      groups.get(hit ? hit[0] : "ach_other").push(item);
    }
    return [...groups].filter(([, items]) => items.length);
  }

  // Side-by-side lists: achievements, prior roles, bills.
  const achievementsOf = (o) => cleanAch(o.achievements);
  const priorRolesOf = (o) => (o.details?.prior_experience || "").split(/\s*;\s*/).filter(Boolean);
  const billsOf = (o) => (o.bills || []).map((b) => [b.number, b.title].filter(Boolean).join(" · "));

  function compareLists(a, b) {
    const achGroup = (g) => (o) => (groupAchievements(o.achievements).find(([k]) => k === g) || [, []])[1];
    const groupKeys = [...ACH_GROUPS.map(([g]) => g), "ach_other"];
    const anyAch = achievementsOf(a).length || achievementsOf(b).length;
    const sections = [
      { label: t("cmp_ach_total"), of: achievementsOf, always: true, countOnly: anyAch, none: t("cmp_no_ach") },
      ...groupKeys.map((g) => ({ label: t("cmp_ach_group", { g: t(g) }), of: achGroup(g), none: t("none") })),
      { label: t("cmp_prior"), of: priorRolesOf, none: t("none_recorded") },
      { label: t("cmp_bills"), of: billsOf, none: t("none_recorded"), bills: true },
    ];
    const hasBills = billsOf(a).length || billsOf(b).length;
    return sections.map(({ label, of, always, none, countOnly, bills }) => {
      const la = of(a), lb = of(b);
      if (!la.length && !lb.length && !always) return "";
      const nrm = (x) => x.toLowerCase().replace(/\s+/g, " ").trim();
      const inA = new Set(la.map(nrm)), inB = new Set(lb.map(nrm));
      const col = (list, other) => list.length
        ? `<ul class="cmp-list">${list.slice(0, 30).map((x) => `<li class="${other.has(nrm(x)) ? "same" : ""}">${esc(x)}</li>`).join("")}</ul>${list.length > 30 ? `<p class="meta">${t("n_more", { n: list.length - 30 })}</p>` : ""}`
        : `<p class="meta cmp-none">${none}</p>`;
      const count = (list) => `<span class="cmp-count">${list.length}</span>`;
      return `<div class="cmp-row cmp-lists">
        <div class="lbl">${esc(label)}</div>
        ${bills && hasBills ? billsNote() : ""}
        <div class="vals"><div>${count(la)}</div><div>${count(lb)}</div></div>
        ${countOnly ? "" : `<details class="cmp-more"${la.length + lb.length <= 6 ? " open" : ""}><summary>${t("see_list")}</summary><div class="vals lists"><div>${col(la, inB)}</div><div>${col(lb, inA)}</div></div></details>`}
      </div>`;
    }).join("");
  }

  function viewCompare() {
    if (!state.loading && !hasData()) { view.innerHTML = noData(); return; }
    const [a, b] = state.compare;
    const slot = (o, i) => o
      ? `<button class="slot" data-slot="${i}">${avatar(o)}<b>${esc(o.name)}</b><small>${esc(levelLabel(o))}</small><small>${t("change")}</small></button>`
      : `<button class="slot" data-slot="${i}"><span class="avatar">＋</span><b>${t("pick")}</b><small>${t("an_official")}</small></button>`;
    let table = "";
    if (a && b) {
      const fields = [
        [t("position"), levelLabel], [t("party"), (o) => o.party], [t("district"), (o) => o.district],
        [t("place"), (o) => place(o, false)], [t("source"), (o) => `${o.source} (${typeLabel(typeOf(o))})`],
      ];
      if (EXEC_LEVELS.has(a.level) || EXEC_LEVELS.has(b.level)) {
        fields.push([t("exec_order"), (o) => (o.ordinal ? t("exec_nth", { n: o.ordinal, nth: ordinal(+o.ordinal || 0) }) : "")],
          [t("term_label"), (o) => o.details?.term || ""],
          [t("exec_in_office"), (o) => yearsIn(o)],
          [t("cmp_laws_signed"), (o) => (o.laws_signed != null ? fmtNum(o.laws_signed) : "")],
          [t("cmp_laws_lapsed"), (o) => (o.laws_lapsed != null ? fmtNum(o.laws_lapsed) : "")],
          [t("cmp_laws_per_year"), (o) => lawsPerYear(o)]);
      }
      if (a.service || b.service) {
        fields.push([t("cmp_since"), (o) => (o.service?.first_senate_year ? String(o.service.first_senate_year) : "")],
          [t("cmp_terms"), (o) => (o.service ? String(o.service.senate_terms) : "")],
          [t("cmp_bills_now"), (o) => (o.bills_count != null ? fmtNum(o.bills_count) : "")],
          [t("cmp_bills_all"), (o) => (o.bills_all != null ? fmtNum(o.bills_all) : "")],
          [t("cmp_avg"), (o) => { const v = perCongress(o); return v == null ? (o.service ? t("no_completed") : "") : fmtNum(v); }],
          [t("cmp_law"), (o) => (o.law_all != null ? fmtNum(o.law_all) : "")]);
      }
      const shared = Object.keys(a.details || {}).filter((k) => b.details?.[k] && !/^line\d|href|photo|image|img|^id$|_id$|slug|position_raw|biography|resume|created_at|updated_at|deleted_at|wikipedia_revision|copied_on|published_via|prior_experience|^term|elected|full_name/.test(k));
      shared.slice(0, 12).forEach((k) => fields.push([k === "address" ? t("office") : k.replace(/_/g, " "), (o) => o.details[k]]));
      table = fields.map(([lab, fn]) => {
        const va = fn(a) || "—", vb = fn(b) || "—";
        const same = va !== "—" && va === vb;
        return `<div class="cmp-row"><div class="lbl">${esc(lab)}</div><div class="vals"><div class="${same ? "same" : ""}">${esc(va)}</div><div class="${same ? "same" : ""}">${esc(vb)}</div></div></div>`;
      }).join("");
      table += compareLists(a, b);
      if (a.summary || b.summary) {
        table += `<div class="cmp-row cmp-lists"><div class="lbl">${t("exec_summary")}</div>
          <details class="cmp-more" open><summary>${t("see_list")}</summary><div class="vals lists">${[a, b].map((o) => `<div>${o.summary ? `<p class="cmp-summary">${esc(o.summary)}</p>` : `<p class="meta cmp-none">${t("none_recorded")}</p>`}</div>`).join("")}</div></details>
          <p class="meta">${t("exec_summary_src")}</p></div>`;
      }
    }
    view.innerHTML = `
      <div class="section-label">${t("cmp_title")}</div>
      <p class="meta" style="margin-top:-4px">${t("cmp_lead")}</p>
      <p class="notice">${t("cmp_2028_note")}</p>
      <p><a class="btn block" href="#/pangulo">${t("exec_history_btn")}</a></p>
      <div class="compare">${slot(a, 0)}<span class="vs">vs</span>${slot(b, 1)}</div>
      ${table || `<div class="empty">${t("pick_two")}</div>`}
      ${a || b ? `<button class="btn block" id="clear-cmp">${t("reset")}</button>` : ""}`;
    view.querySelectorAll("[data-slot]").forEach((btn) => btn.addEventListener("click", async () => {
      const o = await pickOfficial(t("pick_to_compare"));
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
    try { localStorage.setItem(STORE_KEY, JSON.stringify(b)); } catch { toast(t("save_failed")); }
  }
  function addToBallot(slotKey, o) {
    const b = getBallot();
    const slot = BALLOT_SLOTS.find((s) => s.key === slotKey);
    const arr = b[slotKey] || [];
    if (arr.includes(key(o))) { toast(t("already_listed")); return false; }
    if (arr.length >= slot.max) { toast(t("slot_full", { slot: slotLabel(slot), n: slot.max })); return false; }
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
    const eday = ELECTION_DAY.toLocaleDateString(t("locale"), { month: "long", day: "numeric", year: "numeric", timeZone: "Asia/Manila" });
    view.innerHTML = `
      <div class="section-label">${t("title_pili")}</div>
      <div class="countdown">
        <small>${t("election", { d: eday })}</small>
        <div class="big">${t("days", { n: fmtNum(days) })}</div>
        <small>${t("days_left")}</small>
      </div>
      <div class="ballot-grid">${BALLOT_SLOTS.map((s) => {
        const picks = (b[s.key] || []).map((k) => state.byKey.get(k) || { name: t("not_found_short"), position: "", _k: k });
        picks.forEach((o) => lines.push(`${slotLabel(s)}: ${o.name}`));
        return `<div class="card">
          <div class="slot-head"><b>${slotLabel(s)}</b><span class="meta">${picks.length} / ${s.max}</span></div>
          ${picks.map((o, i) => `<div class="pick-row">${o.id ? avatar(o) : ""}<div class="who"><b>${esc(o.name)}</b><span>${esc(levelLabel(o))}</span></div><button class="x" data-rm="${s.key}:${i}" aria-label="${esc(t("remove"))}">✕</button></div>`).join("")}
          ${picks.length < s.max ? `<button class="add" data-add="${s.key}">${t("add")}</button>` : ""}
        </div>`;
      }).join("")}</div>
      <div class="btn-row"><button class="btn" id="share">${t("share")}</button><button class="btn" id="reset">${t("clear")}</button></div>
      <p class="notice">${t("ballot_note")}</p>`;

    view.querySelectorAll("[data-add]").forEach((btn) => btn.addEventListener("click", async () => {
      const s = BALLOT_SLOTS.find((x) => x.key === btn.dataset.add);
      const o = await pickOfficial(t("add_to", { slot: slotLabel(s) }), s.hint);
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
      const text = `${t("share_title")} 🇵🇭\n${lines.join("\n") || t("none_yet")}\n${t("share_via")}`;
      try {
        if (navigator.share) await navigator.share({ title: t("share_title"), text });
        else { await navigator.clipboard.writeText(text); toast(t("copied")); }
      } catch {}
    });
    $("#reset").addEventListener("click", () => { if (confirm(t("confirm_clear"))) { setBallot({}); viewPili(); } });
  }

  // Stats + sources
  function viewAko() {
    const ds = state.manifest?.datasets || [];
    const counts = {};
    state.officials.forEach((o) => (counts[o.level] = (counts[o.level] || 0) + 1));
    const partyBars = (level, title) => {
      const m = {};
      state.officials.filter((o) => o.level === level).forEach((o) => { const p = o.party || t("not_recorded"); m[p] = (m[p] || 0) + 1; });
      const entries = Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 12);
      if (!entries.length) return "";
      const max = entries[0][1];
      return `<div class="section-label">${title}</div><div class="card">${entries.map(([p, n]) => `<div class="bar"><span class="lab" title="${esc(p)}">${esc(p)}</span><span class="track"><span class="fill" style="width:${(n / max) * 100}%;display:block"></span></span><span class="n">${n}</span></div>`).join("")}</div>`;
    };
    const lguCount = ["mayor", "vice_mayor", "councilor", "governor", "vice_governor", "board_member"].reduce((s, k) => s + (counts[k] || 0), 0);
    view.innerHTML = `
      <div class="section-label">${t("counts")}</div>
      <div class="stats">
        <div class="stat"><b>${fmtNum(counts.senate)}</b><span>${t("st_senators")}</span></div>
        <div class="stat"><b>${fmtNum(counts.house)}</b><span>${t("st_house")}</span></div>
        <div class="stat"><b>${fmtNum(lguCount)}</b><span>${t("st_lgu")}</span></div>
        <div class="stat"><b>${fmtNum(state.brgyIndex?.count)}</b><span>${t("st_brgy")}</span></div>
      </div>
      <div class="ako-grid"><div>${partyBars("senate", t("senate_by_party"))}</div><div>${partyBars("house", t("house_by_party"))}</div></div>
      <div class="ako-grid"><div>
      <div class="section-label">${t("data_sources")}</div>
      <div class="card"><table class="kv">
        ${ds.map((d) => `<tr><th><a href="${esc(safeUrl(d.source_url))}" target="_blank" rel="noopener">${esc(d.source)}</a><br>${typeBadge(typeOf(d))}</th><td>${d.key === "bills" ? t("n_bills", { n: fmtNum(d.count) }) : t("n_records", { n: fmtNum(d.count) })}<br><span class="meta">${d.key === "bills" && d.as_of ? t("data_as_of", { d: fmtDate(d.as_of) }) : d.scraped_at ? t("updated", { d: fmtDate(d.scraped_at) }) : t("pending")}</span></td></tr>`).join("") || `<tr><td>${t("no_data_short")}</td></tr>`}
      </table></div></div><div>
      <div class="section-label desk-only" aria-hidden="true">&nbsp;</div>
      <div class="card legend">
        <p>${typeBadge("official")} ${t("legend_official")}</p>
        <p>${typeBadge("public")} ${t("legend_public")}</p>
        <p style="margin-bottom:0">${typeBadge("private")} ${t("legend_private")}</p>
      </div>
      <div class="section-label">${t("about")}</div>
      <div class="card">
        <p style="margin-top:0">${t("about_body")}</p>
        <p class="meta" style="margin-bottom:0">${t("about_note")}</p>
      </div>
      <div class="card legal-links">
        <a href="#/privacy">🔒 ${t("privacy_title")}</a>
        <a href="#/report">⚑ ${t("report_title")}</a>
      </div></div></div>`;
  }

  // ------------------------------------------------------------ legal
  function viewPrivacy() {
    setTitle(t("privacy_title"));
    view.innerHTML = `<article class="legal">
      <p class="meta">${t("legal_effective", { d: fmtDate("2026-09-30") })}</p>
      <nav class="legal-toc"><button type="button" class="link-btn" data-go="privacy">${t("privacy_h")}</button> · <button type="button" class="link-btn" data-go="terms">${t("terms_h")}</button></nav>
      <section id="privacy"><h2>${t("privacy_h")}</h2>${t("privacy_html", { gh: "https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement" })}</section>
      <section id="terms"><h2>${t("terms_h")}</h2>${t("terms_html")}</section>
      <p><a class="btn block" href="#/report">⚑ ${t("report_title")}</a></p>
    </article>`;
    view.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => $("#" + b.dataset.go).scrollIntoView({ behavior: "smooth" })));
  }

  // Reports become a pre-filled GitHub issue (public), or text to copy.
  const REPORT_KINDS = ["wrong_info", "outdated", "missing", "bills", "other"];
  async function viewReport(dataset, id) {
    setTitle(t("report_title"));
    const o = dataset && id ? await findOfficial(dataset, id) : null;
    const record = o ? `${o.name} — ${levelLabel(o)}${place(o) ? `, ${place(o)}` : ""}` : "";
    view.innerHTML = `<article class="legal">
      <p>${t("report_lead")}</p>
      <form id="report-form" class="report-form">
        <label><span>${t("report_record")}</span>
          <input class="select" name="record" value="${esc(record)}" placeholder="${esc(t("report_record_ph"))}"></label>
        <label><span>${t("report_kind")}</span>
          <select class="select" name="kind">${REPORT_KINDS.map((k) => `<option value="${k}">${t(`rk_${k}`)}</option>`).join("")}</select></label>
        <label><span>${t("report_details")} *</span>
          <textarea class="select" name="details" rows="5" required placeholder="${esc(t("report_details_ph"))}"></textarea></label>
        <label><span>${t("report_source")}</span>
          <input class="select" name="source" type="url" inputmode="url" placeholder="https://…"></label>
        <p class="notice">${t("report_public_note")}</p>
        <div class="btn-row">
          <button type="submit" class="btn primary">${t("report_send")}</button>
          <button type="button" class="btn" id="report-copy">${t("report_copy")}</button>
        </div>
        ${CONTACT_EMAIL ? `<p><a class="btn block" id="report-mail" href="#">${t("report_email")}</a></p>` : ""}
        <p class="meta">${t("report_after")}</p>
      </form>
    </article>`;
    const form = $("#report-form");
    const compose = () => {
      const f = new FormData(form);
      const kind = t(`rk_${f.get("kind")}`);
      const title = `[${kind}] ${f.get("record") || t("report_general")}`.slice(0, 120);
      const body = [
        `**${t("report_record")}:** ${f.get("record") || "—"}`,
        o ? `**Link:** ${location.origin}${location.pathname}#/o/${o.dataset}/${o.id}` : "",
        o ? `**${t("source")}:** ${o.source} (${o.source_url})` : "",
        `**${t("report_kind")}:** ${kind}`,
        "", `**${t("report_details")}:**`, String(f.get("details") || "").trim(),
        "", `**${t("report_source")}:** ${f.get("source") || "—"}`,
        "", `_${t("report_footer")}_`,
      ].filter((line, i, all) => line !== "" || all[i - 1] !== "").join("\n");
      return { title, body };
    };
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const { title, body } = compose();
      window.open(`${REPO_URL}/issues/new?labels=data-error&title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`, "_blank", "noopener");
    });
    $("#report-copy").addEventListener("click", async () => {
      if (!form.reportValidity()) return;
      const { title, body } = compose();
      try { await navigator.clipboard.writeText(`${title}\n\n${body}`); toast(t("copied")); } catch { toast(t("save_failed")); }
    });
    $("#report-mail")?.addEventListener("click", (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const { title, body } = compose();
      location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
    });
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
        const pool = [...state.officials, ...state.pastExec, ...[...state.brgyFiles.values()].flat()];
        let items = pool.filter((o) => terms.every((w) => o._s.includes(w)));
        if (!terms.length && hint) items = items.filter(hint);
        list.innerHTML = items.slice(0, 80).map((o) => `<li>${row(o).replace('<a class="row" href=', '<a class="row" data-k="' + esc(key(o)) + '" href=')}</li>`).join("") || `<li class="empty">${t("no_match_short")}</li>`;
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

  // ------------------------------------------------------------ cover
  // Shown every time the app is opened or refreshed; Enter continues to the
  // page in the address (home, or a shared profile link).
  function showCover() {
    const cover = $("#cover");
    cover.hidden = false;
    document.body.classList.add("covered");
    $("#enter").focus();
  }
  function enterApp() {
    const cover = $("#cover");
    cover.classList.add("leaving");
    document.body.classList.remove("covered");
    setTimeout(() => { cover.hidden = true; cover.classList.remove("leaving"); $("#view").focus({ preventScroll: true }); }, 250);
  }

  // ------------------------------------------------------------ router
  function setTitle(sub) {
    $("#topbar-sub").textContent = sub || t("tagline");
    document.title = sub ? `${sub} · Pili.PH` : t("app_title");
  }

  function render() {
    const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const tab = ["o", "bills", "laws"].includes(parts[0]) ? "" : parts[0] || "home";
    view.dataset.view = parts[0] === "o" ? "profile" : ["bills", "laws"].includes(parts[0]) ? "bills" : tab;
    document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    document.querySelectorAll(".tabbar a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    $("#back").hidden = !["o", "bills", "laws", "privacy", "report", "pangulo"].includes(parts[0]);
    const titles = { hanap: "title_hanap", ihambing: "title_ihambing", pili: "title_pili", ako: "title_ako", privacy: "privacy_title", report: "report_title", pangulo: "exec_history_title" };
    setTitle(titles[tab] ? t(titles[tab]) : "");
    switch (parts[0]) {
      case "o": return viewProfile(parts[1], parts.slice(2).join("/"));
      case "laws": return viewLaws(parts.slice(1).join("/"));
      case "bills": return viewBills(parts[1], parts[2] === "career" ? "career" : "term", parts[3] || "");
      case "hanap": return viewHanap();
      case "ihambing": return viewCompare();
      case "pangulo": return viewExecHistory();
      case "pili": return viewPili();
      case "ako": return viewAko();
      case "privacy": return viewPrivacy();
      case "report": return viewReport(parts[1], parts.slice(2).join("/"));
      default: return viewHome();
    }
  }

  // The logo returns to the start: a fresh home list behind the cover page.
  $(".brand").addEventListener("click", (e) => {
    e.preventDefault();
    Object.assign(state, { q: "", filter: "all", island: "", shown: PAGE, filtersOpen: false, sort: "name", scope: "term", sector: "" });
    HANAP_ORDER.forEach((k) => (hanap[k] = ""));
    hanap.q = "";
    hanap.open = false;
    if (location.hash === "#/" || !location.hash) render();
    else location.hash = "#/";
    window.scrollTo(0, 0);
    showCover();
  });
  $("#back").addEventListener("click", () => (history.length > 1 ? history.back() : (location.hash = "#/")));
  $("#lang").addEventListener("click", () => setLang(lang === "en" ? "tl" : "en"));
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
  $("#enter").addEventListener("click", enterApp);
  $("#cover-privacy").addEventListener("click", enterApp);
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
  applyStatic();
  showCover();
  render();
  load();

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    // Always check for a new service worker, and reload once when one takes
    // over so visitors never stay on an old version of the app.
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !sessionStorage.getItem("pili.reloaded")) {
        try { sessionStorage.setItem("pili.reloaded", "1"); } catch {}
        location.reload();
      }
    });
    navigator.serviceWorker.register("sw.js", { updateViaCache: "none" })
      .then((reg) => reg.update())
      .catch(() => {});
  }
})();
