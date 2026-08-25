/* azure-price-my — client app */
"use strict";

const state = {
  rows: [],        // joined view rows
  filtered: [],
  page: 0,
  perPage: 50,
  sortKey: "armSkuName",
  sortDir: 1,
};

const $ = (id) => document.getElementById(id);
const fmt = (n, dp = 4) =>
  n === null || n === undefined ? '<span class="muted">—</span>' : Number(n).toFixed(dp);

/* ---------- load data ---------- */
async function loadData() {
  const [pricing, specs] = await Promise.all([
    fetch("data/pricing.json").then((r) => r.json()),
    fetch("data/specs.json").then((r) => r.json()),
  ]);
  $("updated").textContent =
    `Updated ${pricing.meta.generatedAt.replace("T", " · ")} (MYT) · ${pricing.meta.rowCount.toLocaleString()} price points`;

  const specMap = new Map(specs.rows.map((s) => [s.armSkuName, s]));

  // index: sku+region+priceType(+term) -> unitPrice
  const priceIdx = new Map();
  for (const r of pricing.rows) {
    const term = r.reservationTerm || r.savingsPlanTerm || "";
    const key = `${r.armSkuName}|${r.armRegionName}|${r.priceType}|${term}`;
    // keep the cheapest meter per key (VM base compute; skips paid add-ons like Gen5 ops)
    const prev = priceIdx.get(key);
    if (!prev || r.unitPrice < prev.unitPrice) priceIdx.set(key, r);
  }

  const seen = new Set();
  for (const [key, row] of priceIdx) {
    const [sku, region, ptype, term] = key.split("|");
    if (region !== "southeastasia" && region !== "malaysiawest") continue;
    const pairKey = `${sku}|${ptype}|${term}`;
    if (seen.has(pairKey)) continue; // emit one view-row per sku+priceType
    seen.add(pairKey);
    const sea = priceIdx.get(`${sku}|southeastasia|${ptype}|${term}`) || null;
    const myw = priceIdx.get(`${sku}|malaysiawest|${ptype}|${term}`) || null;
    if (!sea && !myw) continue;
    const sp = specMap.get(sku) || null;
    const cat = (sea || myw).category.startsWith("Compute") ? "Compute (VM)" : "Database";
    state.rows.push({
      armSkuName: sku,
      series: sp ? sp.series : "",
      vCPUs: sp ? sp.vCPUs : null,
      memoryGB: sp ? sp.memoryGB : null,
      tempDiskGB: sp ? sp.tempDiskGB : null,
      category: cat,
      sea: sea ? sea.unitPrice : null,
      myw: myw ? myw.unitPrice : null,
      diff: sea && myw ? (myw.unitPrice / sea.unitPrice - 1) * 100 : null,
      productName: (sea || myw).productName,
      _ptype: ptype, _term: term,
    });
  }
  buildSeriesList();
  applyFilters();
}

/* ---------- filtering + sort + render ---------- */
function applyFilters() {
  const q = $("search").value.trim().toLowerCase();
  const cat = $("category").value;
  const ser = $("series").value;
  const [ptype, term] = $("priceType").value.split("|");
  const minCpu = parseFloat($("minCpu").value) || 0;
  const minRam = parseFloat($("minRam").value) || 0;

  state.filtered = state.rows.filter(
    (r) =>
      r._ptype === ptype &&
      (term ? r._term === term : true) &&
      (cat === "all" || r.category === cat) &&
      (!ser || r.series === ser) &&
      (!q || r.armSkuName.toLowerCase().includes(q)) &&
      (r.vCPUs === null || r.vCPUs >= minCpu) &&
      (r.memoryGB === null || r.memoryGB >= minRam)
  );

  const k = state.sortKey;
  state.filtered.sort((a, b) => {
    let x = a[k], y = b[k];
    if (k === "armSkuName" || k === "series") return state.sortDir * String(x).localeCompare(String(y));
    x = x === null ? Infinity : x; y = y === null ? Infinity : y;
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
      const badge =
        r.category === "Database"
          ? '<span class="badge">DB</span>'
          : "";
      const diffCell =
        r.diff === null
          ? '<span class="muted">—</span>'
          : `<span class="${r.diff <= 0 ? "diff-neg" : "diff-pos"}">${r.diff > 0 ? "+" : ""}${r.diff.toFixed(1)}%</span>`;
      return `<tr>
        <td class="sku"><code>${r.armSkuName}</code>${badge}</td>
        <td>${r.vCPUs ?? '<span class="muted">—</span>'}</td>
        <td>${r.memoryGB ?? '<span class="muted">—</span>'}</td>
        <td>${r.tempDiskGB ?? '<span class="muted">None</span>'}</td>
        <td>${fmt(r.sea)}</td>
        <td>${fmt(r.myw)}</td>
        <td>${diffCell}</td>
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
  clearTimeout(deb); deb = setTimeout(applyFilters, 180);
});
for (const id of ["category", "series", "priceType", "minCpu", "minRam"]) {
  $(id).addEventListener("change", () => { state.page = 0; applyFilters(); });
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

loadData().catch((e) => {
  $("tbody").innerHTML =
    `<tr><td colspan="7">⚠️ Failed to load data: ${e.message}</td></tr>`;
});
