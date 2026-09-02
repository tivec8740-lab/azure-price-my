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
  period: "hour",   // "hour" | "month"
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
  japanwest: "Japan West (Osaka)",
  koreacentral: "Korea Central (Seoul)",
  centralindia: "Central India (Pune)",
  southindia: "South India (Chennai)",
  australiaeast: "Australia East (SYD)",
};
const regionShort = (arm) => {
  const SHORT = {
    southeastasia: "SG", malaysiawest: "MYW", eastasia: "HK",
    japaneast: "Tokyo", japanwest: "Osaka", koreacentral: "KR",
    centralindia: "Pune", southindia: "Chennai", australiaeast: "SYD",
    westeurope: "EU", eastus: "US-E",
  };
  return SHORT[arm] || arm.slice(0, 3).toUpperCase();
};

const CURRENCY_SYMBOLS = {
  MYR: "RM", USD: "$", SGD: "S$", AUD: "A$", EUR: "€", GBP: "£", INR: "₹", JPY: "¥",
};

const fmt = (n, dp = 4) =>
  n === null || n === undefined ? '<span class="muted">—</span>' : Number(n).toFixed(dp);
const fmtRegion = (r) =>
  r.sel === null || r.sel === undefined
    ? '<span class="muted" title="Not offered in this region by Azure">Not offered</span>'
    : fmtPrice(r.sel);

const HOURS_PER_MONTH = 730;   // Azure billing month
// Format a price for the active period + currency.
// Hourly keeps 4dp; monthly is a big number => whole number w/ thousands separators.
const fmtPrice = (n) => {
  if (n === null || n === undefined) return '<span class="muted">—</span>';
  const sym = CURRENCY_SYMBOLS[state.currency] || state.currency + " ";
  const scaled = state.period === "month" ? n * HOURS_PER_MONTH : n;
  if (state.period === "month") {
    return sym + Math.round(scaled).toLocaleString("en-US");
  }
  return sym + Number(scaled).toFixed(4).replace(/\.?0+$/, "");
};

/* ---------- data ---------- */
async function loadData() {
  // Apply shareable URL params to the controls BEFORE fetching/rendering.
  applyParamsFromUrl();

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

  // Apply URL state that must happen AFTER controls are populated/loaded.
  if (state._region) { state.region = state._region; $("region").value = state._region; }
  if (state._period) { state.period = state._period; $("period").value = state._period; }
  if (state._priceType) { $("priceType").value = state._priceType; }
  if (state._sku) { $("search").value = state._sku; }

  rebuildRows();
  applyFilters();
}

/* Parse & stash shareable URL params (?sku=&region=&currency=&period=&priceType=) */
function applyParamsFromUrl() {
  const p = new URLSearchParams(location.search);
  const c = (p.get("currency") || "MYR").toUpperCase();
  if (["MYR","USD","SGD","AUD","EUR","GBP","INR","JPY"].includes(c)) {
    state.currency = c;
    $("currency").value = c;   // keep dropdown in sync with the URL/presented data
  }
  const r = p.get("region");
  if (r) state._region = r;
  const per = p.get("period");
  if (per === "month" || per === "hour") state._period = per;
  const pt = p.get("priceType");
  if (pt) state._priceType = pt;
  const sku = p.get("sku");
  if (sku) state._sku = sku;
}

/* Build a shareable URL from current controls and update address bar (no reload) */
function syncUrl() {
  const p = new URLSearchParams();
  const region = $("region").value;
  const pt = $("priceType").value;
  const sku = $("search").value.trim();
  if (region) p.set("region", region);
  p.set("currency", state.currency);
  if (state.period) p.set("period", state.period);
  if (pt) p.set("priceType", pt);
  if (sku) p.set("sku", sku);
  history.replaceState(null, "", "?" + p.toString());
}
function shareUrl() {
  syncUrl();
  return location.origin + location.pathname + "?" + new URLSearchParams(location.search).toString();
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
  const unit = state.period === "month" ? "/mo" : "/hr";
  // Currency symbol is shown on every price cell; headers stay clean.
  $("thSel").textContent = region ? `${regionShort(region)} ${unit}` : `Region ${unit}`;
  $("thCheap").textContent = `Best ${unit}`;
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
      (r.memoryGB === null || r.memoryGB >= minRam) &&
      (!$("onlySpec").checked || r.vCPUs !== null)
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
        <td>${fmtRegion(r)}</td>
        <td>${bestCell}</td>
        <td>${fmtPrice(r.cheapest)}</td>
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
  deb = setTimeout(() => { applyFilters(); syncUrl(); }, 250);
});
for (const id of ["category", "series", "minCpu", "minRam"]) {
  $(id).addEventListener("change", () => { state.page = 0; applyFilters(); syncUrl(); });
}
$("onlySpec").addEventListener("change", () => { state.page = 0; applyFilters(); syncUrl(); });
$("priceType").addEventListener("change", () => {
  state.page = 0;
  rebuildRows();     // row set depends on the price type
  applyFilters();
  syncUrl();
});
$("period").addEventListener("change", (e) => {
  state.period = e.target.value;
  resetRows();       // re-label headers + recompute (prices scale in fmtPrice)
  applyFilters();
  syncUrl();
});
$("region").addEventListener("change", (e) => {
  state.region = e.target.value;
  state.page = 0;
  dataLoaded ? (resetRows(), applyFilters(), syncUrl()) : null;
});
$("currency").addEventListener("change", (e) => {
  state.currency = e.target.value;
  state.rows = [];
  state.page = 0;
  loadData().catch(showErr).then(syncUrl);
});
$("share").addEventListener("click", async () => {
  const url = shareUrl();
  try {
    await navigator.clipboard.writeText(url);
    $("share").textContent = "✓ Copied!";
  } catch (e) {
    window.prompt("Copy this link:", url);
  }
  setTimeout(() => ($("share").textContent = "🔗 Share"), 1500);
});
// CSV Export - exports currently filtered rows
function exportCsv() {
  if (!state.filtered.length) { alert("No data to export"); return; }
  const sym = CURRENCY_SYMBOLS[state.currency] || state.currency;
  const periodLabel = state.period === "month" ? "per month" : "per hour";
  const regionLabel = state.region ? REGION_LABELS[state.region] || state.region : "Region";
  const headers = ["SKU","Category","Series","vCPU","RAM_GB","TempDisk_GB", regionLabel + " " + periodLabel, "Market Best Region", "Best Price " + periodLabel + " (" + sym + ")", "Save %"];
  const rows = state.filtered.map(r => {
    const selPrice = r.sel === null ? "" : (state.period === "month" ? Math.round(r.sel * HOURS_PER_MONTH) : Number(r.sel).toFixed(4));
    const bestPrice = r.cheapest === null ? "" : (state.period === "month" ? Math.round(r.cheapest * HOURS_PER_MONTH) : Number(r.cheapest).toFixed(4));
    const save = r.save === null ? "" : r.save.toFixed(1);
    return [r.armSkuName, r.category, r.series||"", r.vCPUs??"", r.memoryGB??"", r.tempDiskGB??"", selPrice, r.cheapestRegion?regionShort(r.cheapestRegion):"", bestPrice, save].map(v => `"${String(v).replace(/"/g,'""')}"`).join(",");
  });
  const csv = [headers.map(h=>`"${h}"`).join(",")].concat(rows).join("\n");
  const blob = new Blob([csv], {type: "text/csv;charset=utf-8;"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `azure-price-${state.currency.toLowerCase()}-${state.region||"all"}-${state.period}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
$("exportCsv").addEventListener("click", exportCsv);
// Slider sync for vCPU/RAM filters
function syncSliders() {
  const cpuNum = $("minCpu"), cpuSl = $("cpuSlider");
  const ramNum = $("minRam"), ramSl = $("ramSlider");
  if (cpuNum && cpuSl) {
    cpuSl.addEventListener("input", () => { cpuNum.value = cpuSl.value; state.page=0; applyFilters(); syncUrl(); });
    cpuNum.addEventListener("input", () => { cpuSl.value = cpuNum.value || 0; });
  }
  if (ramNum && ramSl) {
    ramSl.addEventListener("input", () => { ramNum.value = ramSl.value; state.page=0; applyFilters(); syncUrl(); });
    ramNum.addEventListener("input", () => { ramSl.value = ramNum.value || 0; });
  }
  // Dynamically set slider max based on data
  const maxCpu = Math.max(0, ...state.rows.map(r=>r.vCPUs||0));
  const maxRam = Math.max(0, ...state.rows.map(r=>r.memoryGB||0));
  if (maxCpu && cpuSl) cpuSl.max = Math.ceil(maxCpu/8)*8;
  if (maxRam && ramSl) ramSl.max = Math.ceil(maxRam/64)*64;
}

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
loadData().then(() => { dataLoaded = true; try{syncSliders();}catch(e){} }).catch(showErr);