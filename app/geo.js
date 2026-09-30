/* Philippine geography used for place filters: island group -> region ->
 * province -> city. Most sources give only a province (or a city standing in
 * for one), so the app derives region and island group from this table.
 * Regions follow the PSA Philippine Standard Geographic Code.
 */
window.PILI_GEO = (() => {
  const R = {
    NCR: "NCR (Metro Manila)",
    CAR: "CAR (Cordillera)",
    I: "Region I (Ilocos Region)",
    II: "Region II (Cagayan Valley)",
    III: "Region III (Central Luzon)",
    IVA: "Region IV-A (CALABARZON)",
    IVB: "MIMAROPA Region",
    V: "Region V (Bicol Region)",
    VI: "Region VI (Western Visayas)",
    NIR: "Negros Island Region (NIR)",
    VII: "Region VII (Central Visayas)",
    VIII: "Region VIII (Eastern Visayas)",
    IX: "Region IX (Zamboanga Peninsula)",
    X: "Region X (Northern Mindanao)",
    XI: "Region XI (Davao Region)",
    XII: "Region XII (SOCCSKSARGEN)",
    XIII: "Region XIII (Caraga)",
    BARMM: "BARMM (Bangsamoro)",
  };
  const ISLAND = {
    luzon: ["NCR", "CAR", "I", "II", "III", "IVA", "IVB", "V"],
    visayas: ["VI", "NIR", "VII", "VIII"],
    mindanao: ["IX", "X", "XI", "XII", "XIII", "BARMM"],
  };
  const PROVINCES = {
    NCR: ["Metro Manila"],
    CAR: ["Abra", "Apayao", "Benguet", "Ifugao", "Kalinga", "Mountain Province"],
    I: ["Ilocos Norte", "Ilocos Sur", "La Union", "Pangasinan"],
    II: ["Batanes", "Cagayan", "Isabela", "Nueva Vizcaya", "Quirino"],
    III: ["Aurora", "Bataan", "Bulacan", "Nueva Ecija", "Pampanga", "Tarlac", "Zambales"],
    IVA: ["Batangas", "Cavite", "Laguna", "Quezon", "Rizal"],
    IVB: ["Marinduque", "Occidental Mindoro", "Oriental Mindoro", "Palawan", "Romblon"],
    V: ["Albay", "Camarines Norte", "Camarines Sur", "Catanduanes", "Masbate", "Sorsogon"],
    VI: ["Aklan", "Antique", "Capiz", "Guimaras", "Iloilo"],
    NIR: ["Negros Occidental", "Negros Oriental", "Siquijor"],
    VII: ["Bohol", "Cebu"],
    VIII: ["Biliran", "Eastern Samar", "Leyte", "Northern Samar", "Samar", "Southern Leyte"],
    IX: ["Zamboanga del Norte", "Zamboanga del Sur", "Zamboanga Sibugay"],
    X: ["Bukidnon", "Camiguin", "Lanao del Norte", "Misamis Occidental", "Misamis Oriental"],
    XI: ["Davao de Oro", "Davao del Norte", "Davao del Sur", "Davao Occidental", "Davao Oriental"],
    XII: ["Cotabato", "Sarangani", "South Cotabato", "Sultan Kudarat"],
    XIII: ["Agusan del Norte", "Agusan del Sur", "Dinagat Islands", "Surigao del Norte", "Surigao del Sur"],
    BARMM: ["Basilan", "Lanao del Sur", "Maguindanao del Norte", "Maguindanao del Sur", "Tawi-Tawi"],
  };
  // Sulu left BARMM after the Supreme Court's 2024 ruling; it is in
  // Mindanao but listed here without a region.
  const NO_REGION = { Sulu: "mindanao" };

  // Cities that sources list in place of a province -> the province (or
  // Metro Manila) they belong to, for filtering.
  const CITIES = {
    "Metro Manila": ["Caloocan", "Las Piñas", "Makati", "Malabon", "Mandaluyong", "Manila", "Marikina", "Muntinlupa",
      "Navotas", "Parañaque", "Pasay", "Pasig", "Pateros", "Quezon City", "San Juan", "Taguig", "Valenzuela"],
    Benguet: ["Baguio"],
    Bulacan: ["San Jose del Monte", "Malolos", "Meycauayan"],
    Pampanga: ["Angeles", "San Fernando"],
    Zambales: ["Olongapo"],
    Rizal: ["Antipolo"],
    Laguna: ["Biñan", "Calamba", "Santa Rosa", "San Pedro", "Cabuyao"],
    Cavite: ["Dasmariñas", "Bacoor", "Imus", "General Trias"],
    Batangas: ["Lipa", "Batangas City"],
    Quezon: ["Lucena"],
    Palawan: ["Puerto Princesa"],
    "Camarines Sur": ["Naga"],
    Iloilo: ["Iloilo City"],
    "Negros Occidental": ["Bacolod"],
    Cebu: ["Cebu City", "Lapu-Lapu", "Lapu-Lapu City", "Mandaue"],
    Leyte: ["Tacloban", "Ormoc"],
    "Zamboanga del Sur": ["Zamboanga City"],
    Basilan: ["Isabela City"],
    "Misamis Oriental": ["Cagayan de Oro"],
    "Lanao del Norte": ["Iligan"],
    "Davao del Sur": ["Davao City"],
    "South Cotabato": ["General Santos"],
    "Agusan del Norte": ["Butuan"],
    "Maguindanao del Norte": ["Cotabato City"],
  };
  // Isabela City is in Basilan but belongs to Region IX.
  const CITY_REGION = { "Isabela City": "IX" };

  const key = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/^city of\s+/, "").replace(/\s+city$/, "").replace(/\s+/g, " ").trim();

  const provRegion = new Map(), cityInfo = new Map();
  Object.entries(PROVINCES).forEach(([r, list]) => list.forEach((p) => provRegion.set(key(p), { name: p, region: r })));
  Object.entries(CITIES).forEach(([prov, list]) => list.forEach((c) => {
    const pr = provRegion.get(key(prov));
    // "Cebu City", "Quezon City" etc. share a name with a province; those
    // are only matched by their full name.
    const k = provRegion.has(key(c)) ? c.toLowerCase() : key(c);
    cityInfo.set(k, { name: c, province: prov, region: CITY_REGION[c] || pr.region });
  }));
  const islandOf = (r) => Object.keys(ISLAND).find((i) => ISLAND[i].includes(r)) || "";
  const regionFromLabel = (label) => {
    const m = String(label || "").match(/\b(NCR|CAR|BARMM|NIR|MIMAROPA|IV-?A|IV-?B|XIII|XII|XI|IX|X|VIII|VII|VI|V|IV|III|II|I)\b/i);
    if (!m) return "";
    const c = m[1].toUpperCase().replace("-", "");
    return c === "MIMAROPA" ? "IVB" : c;
  };

  /* Where a record sits. Returns { island, region, province, city }, with
   * region as its full name; any part may be "". */
  function locate(o) {
    const rawProv = o.province || "", rawLgu = o.lgu || "";
    let city = null, prov = provRegion.get(key(rawProv));
    const exact = cityInfo.get(rawProv.toLowerCase().trim());
    if (exact || (!prov && cityInfo.has(key(rawProv)))) {
      city = exact || cityInfo.get(key(rawProv));
      prov = provRegion.get(key(city.province));
    }
    if (!city && rawLgu) {
      const c = cityInfo.get(rawLgu.toLowerCase().trim()) || cityInfo.get(key(rawLgu));
      if (c && (!prov || key(c.province) === key(prov.name))) city = c;
    }
    let region = city?.region || prov?.region || regionFromLabel(o.region);
    let island = islandOf(region) || NO_REGION[rawProv] || "";
    return {
      island,
      region: R[region] || o.region || "",
      province: prov?.name || (city ? city.province : rawProv),
      city: rawLgu || city?.name || "",
    };
  }

  const regionsOf = (island) => (island ? ISLAND[island] : Object.keys(R)).map((r) => R[r]);
  return { locate, regionsOf, islands: Object.keys(ISLAND), islandOfRegion: (label) => islandOf(regionFromLabel(label)) };
})();
