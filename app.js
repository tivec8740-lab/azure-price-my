/* azure-price-my — client app (Option B: one region + vs-market cheapest) */
"use strict";

const state = {
  rows: [],
  filtered: [],
  page: 0,
  perPage: 50,
  sortKey: "armSkuName",
  sortDir: 1,
  currency: "MYR",
  region: null,
  regions: [],
  bySku: new Map(),   // sku -> (ptype|term) -> {region -> meter}
  specMap: new Map(),
};

const $ = (id) => document.getElementById(id);

// friendly labels keyed by arm region name
const REGION_LABELS = {
  southeastasia: "Southeast Asia (SG)",
  malaysiawest: "Malaysia West",
  eastasia: "East Asia (HK)",
  japaneast: "Japan East (Tokyo)",
  australiaeast: "Australia East (SYD)",
};
const regionShort = (arm) => {
  const SHORT = {
    southeastasia: "SG", malaysiawest: "MYW", eastasia: "HK",
    japaneast: "Tokyo", australiaeast: "SYD", centralindia: "IN",
    southindia: "IN-S", koreacentral: "KR", westeurope: "EU", eastus: "US-E",
  };
  return SHORT[arm] || arm.slice(0, 3).toUpperCase();
};

const fmt = (n, dp = 4) =>
  n === null || n === undefined ? '<span class="muted">—</span>' : Number(n).toFixed(dp);

/* ---------- data ---------- */
async function loadData() {
  const [pricing, specs] = await Promise.all([
    fetch(`data/pricing_${state.currency.toLowerCase()}.json`).then((r) => r.json()),
    fetch("data/specs.json").then((r) => r.json()),
  ]);
  $("updated").textContent =
    `Updated ${pricing.meta.generatedAt.replace("T", " · ")} (MYT) · ${pricing.meta.rowCount.toLocaleString()} price points · ${pricing.meta.currency}`;

  state.regions = pricing.meta.regions;
  populateRegionSelect();

  state.specMap = new Map(specs.rows.map((s) => [s.armSkuName, s]));

  // index: sku|region|ptype|term -> {unitPrice, category, productName} (cheapest meter)
  const priceIdx = new Map();
  for (const r of pricing.rows) {
    const term = r.reservationTerm || r.savingsPlanTerm || "";
    const key = `${r.armSkuName}|${r.armRegionName}|${r.priceType}|${term}`;
    const prev = priceIdx.get(key);
    if (!prev || r.unitPrice < prev.unitPrice)
      priceIdx.set(key, { unitPrice: r.unitPrice, category: r.category, productName: r.productName });
  }

  // group by sku so region prices can be compared
  state.bySku = new Map();
  for (const [key] of priceIdx) {
    const [sku, region, ptype, term] = key.split("|");
    if (!state.bySku.has(sku)) state.bySku.set(sku, new Map());  // (ptype|term) -> {region->meter}
    const inner = state.bySku.get(sku);
    const pk = `${ptype}|${term}`;
    if (!inner.has(pk)) inner.set(pk, new Map());
    const m = priceIdx.get(key);
    inner.get(pk).set(region, m);
  }

  rebuildRows();
  applyFilters();
}

/* Build the visible row set for the currently-selected price type across all regions */
function rebuildRows() {
  const __pt = $("priceType").value.split("|");
  const ptype = __pt[0], term = __pt[1] || "";
  const pk = `${ptype}|${term}`;
  state.rows = [];
  for (const [sku, inner] of state.bySku) {
    const regionMap = inner.get(pk);
    if (!regionMap) continue;
    const sp = state.specMap.get(sku) || null;
    let cheapest = null, cheapestRegion = null;
    for (const [arm, m] of regionMap) {
      if (!cheapest || m.unitPrice < cheapest) { cheapest = m.unitPrice; cheapestRegion = arm; }
    }
    const example = regionMap.values().next().value;
    const row = {
      armSkuName: sku,
      series: sp ? sp.series : "",
      vCPUs: sp ? sp.vCPUs : null,
      memoryGB: sp ? sp.memoryGB : null,
      tempDiskGB: sp ? sp.tempDiskGB : null,
      category: example.category,
      productName: example.productName,
      regionPrice: {},
      cheapest: cheapest ?? null,
      cheapestRegion: cheapestRegion ?? null,
    };
    for (const [arm, m] of regionMap) row.regionPrice[arm] = m.unitPrice;
    state.rows.push(row);
  }
  buildSeriesList();
  resetRows();   // sets sel/save from current region
}

/* Recompute the selected-region column + save% for current state.region */
function resetRows() {
  const region = state.region;
  $("thSel").textContent =
    region ? `${regionShort(region)} /hr` : "Region /hr";
  for (const r of state.rows) {
    const sel = r.regionPrice[region];
    r.sel = sel ?? null;
    r.save = sel && r.cheapest ? (1 - r.cheapest / sel) * 100 : null;
  }
}

function populateRegionSelect() {
  const sel = $("region");
  sel.innerHTML = state.regions
    .map((arm) => `<option value="${arm}">${REGION_LABELS[arm] || arm}</option>`)
    .join("");
  state.region = sel.value; // first region (southeastasia)
}

/* ---------- filtering + sort + render ---------- */
function applyFilters() {
  const q = $("search").value.trim().toLowerCase();
  const cat = $("category").value;
  const ser = $("series").value;
  const minCpu = parseFloat($("minCpu").value) || 0;
  const minRam = parseFloat($("minRam").value) || 0;

  state.filtered = state.rows.filter(
    (r) =>
      (cat === "all" || r.category.startsWith(cat)) &&
      (!ser || r.series === ser) &&
      (!q || r.armSkuName.toLowerCase().includes(q)) &&
      (r.vCPUs === null || r.vCPUs >= minCpu) &&
      (r.memoryGB === null || r.memoryGB >= minRam)
  );

  const k = state.sortKey;
  state.filtered.sort((a, b) => {
    let x = a[k], y = b[k];
    if (k === "armSkuName" || k === "series" || k === "cheapestRegion")
      return state.sortDir * String(x ?? "").localeCompare(String(y ?? ""));
    x = x === null ? Infinity : x;
    y = y === null ? Infinity : y;
    return state.sortDir * (x - y);
  });
  state.page = Math.min(state.page, Math.max(0, Math.ceil(state.filtered.length / state.perPage) - 1));
  render();
}

function render() {
  const start = state.page * state.perPage;
  const slice = state.filtered.slice(start, start + state.perPage);
  $("tbody").innerHTML = slice
    .map((r) => {
      const badge = r.category.startsWith("Database") ? '<span class="badge">DB</span>' : "";
      /* by default sort by save% descending is most useful, but honor user sort */
      const saveCell =
        r.save === null || r.save < 0.001
          ? '<span class="muted">—</span>'
          : `<span class="diff-neg">${r.save.toFixed(1)}%</span>`; // green = saving available
      const bestCell =
        r.cheapestRegion === state.region
          ? `<span class="muted">${regionShort(r.cheapestRegion)}</span>`
          : `<span class="diff-neg"><b>${regionShort(r.cheapestRegion)}</b></span>`;
      return `<tr>
        <td class="sku"><code>${r.armSkuName}</code>${badge}</td>
        <td>${r.vCPUs ?? '<span class="muted">—</span>'}</td>
        <td>${r.memoryGB ?? '<span class="muted">—</span>'}</td>
        <td>${r.tempDiskGB ?? '<span class="muted">None</span>'}</td>
        <td>${fmt(r.sel)}</td>
        <td>${bestCell}</td>
        <td>${fmt(r.cheapest)}</td>
        <td>${saveCell}</td>
      </tr>`;
    })
    .join("");

  const pages = Math.max(1, Math.ceil(state.filtered.length / state.perPage));
  $("pageInfo").textContent = `page ${state.page + 1} / ${pages}`;
  $("count").textContent = `${state.filtered.length.toLocaleString()} SKUs`;
  $("prev").disabled = state.page === 0;
  $("next").disabled = state.page >= pages - 1;
}

function buildSeriesList() {
  const sels = [...new Set(state.rows.map((r) => r.series).filter(Boolean))].sort();
  $("series").innerHTML =
    '<option value="">All series</option>' +
    sels.map((s) => `<option value="${s}">${s}</option>`).join("");
}

/* ---------- events ---------- */
let deb;
$("search").addEventListener("input", () => {
  clearTimeout(deb);
  deb = setTimeout(applyFilters, 180);
});
for (const id of ["category", "series", "minCpu", "minRam"]) {
  $(id).addEventListener("change", () => { state.page = 0; applyFilters(); });
}
$("priceType").addEventListener("change", () => {
  state.page = 0;
  rebuildRows();     // row set depends on the price type
  applyFilters();
});
$("region").addEventListener("change", (e) => {
  state.region = e.target.value;
  state.page = 0;
  dataLoaded ? (resetRows(), applyFilters()) : null;
});
$("currency").addEventListener("change", (e) => {
  state.currency = e.target.value;
  state.rows = [];
  state.page = 0;
  loadData().catch(showErr);
});
document.querySelectorAll("th[data-sort]").forEach((th) =>
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    state.sortDir = key === state.sortKey ? -state.sortDir : 1;
    state.sortKey = key;
    applyFilters();
  })
);
$("prev").addEventListener("click", () => { state.page--; render(); window.scrollTo({ top: 0 }); });
$("next").addEventListener("click", () => { state.page++; render(); window.scrollTo({ top: 0 }); });

function showErr(e) {
  $("tbody").innerHTML = `<tr><td colspan="8">⚠️ Failed to load data: ${e.message}</td></tr>`;
}
let dataLoaded = false;
loadData().then(() => { dataLoaded = true; }).catch(showErr);