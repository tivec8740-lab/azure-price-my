# Azure Price MY — Operations Reference

Handy troubleshooting + architecture notes for whoever touches this repo (you, Hermes, KiloClaw).

## Architecture
```
Azure Retail Prices API (public, no auth)
   ↓ nightly cron 06:00 MYT (VPS, no_agent, zero tokens)
pipeline/fetch_pricing.py  → data/pricing_<cc>.json  (8 currencies, ~55k rows each)
pipeline/build_specs.py    → data/specs.json  (seed + rename aliases + MANUAL_SPECS)
pipeline/scrape_learn_specs.py → (one-off) fill gaps from MicrosoftDocs/azure-compute-docs
   ↓ git commit only-if-changed + push
GitHub Pages serves static site → visitors' browser does filtering client-side
```

## Files
| Path | Role |
|---|---|
| `index.html` | Controls + headers + footer (donate links, SEO landing, schema) |
| `app.js` | All client logic: load/filter/sort/compare; share-URL param handling |
| `style.css` | Dark theme |
| `data/pricing_<cc>.json` | Per-currency price rows (auto-updated nightly) |
| `data/specs.json` | SKU specs (region-independent) |
| `data/last_updated.json` | Refreshed-at stamp, used by footer |
| `pipeline/fetch_pricing.py` | Nightly fetcher (scope filters + RI×hourly conversion) |
| `pipeline/build_specs.py` | Rebuild specs from seed workbook + aliases + manual |
| `pipeline/scrape_learn_specs.py` | Gap-fill scraper against MS Docs GitHub repo |
| `pipeline/refresh.sh` | Nightly wrapper: fetch → commit-if-changed → push |

## Key gotchas
- **RI conversion**: Azure API gives Reservation as multi-year TOTAL. fetch_pricing divides by 8760 (1y) / 26280 (3y) / 43800 (5y) → hourly, so it compares with PAYG/SP.
- **HARD scope filters** in fetch_pricing `is_excluded()`: windows, spot, low priority, dev/test, dedicated host — remember the **no-space `"DedicatedHost"`** variant (that leaked a set of junk per-physical-host rows once).
- **Specs rename aliases** (`ALIASES` in build_specs.py): Azure docs rename sizes (B1ls→B1ls2, E104id_v5→E104id_v52) but the API keeps legacy names.
- **Share URL**: site reads/writes `?sku=&region=&currency=&period=&priceType=` (priceType has a `|`, URL-encoded `%7C`). `syncUrl()` rewrites it as controls change.
- **Azure Calculator lags** the Retail API for new v6 SKUs / Malaysia West — site may show prices the portal calculator doesn't yet. This is correct (verify against live API if unsure).

## Nightly cron
Hermes cron `azure-price-my nightly refresh` (no_agent) → `~/.hermes/scripts/azure_price_refresh.sh` → `pipeline/refresh.sh`. Runs 06:00 MYT. STAYS SILENT when nothing changed (watchdog behaviour).

## Local test
```bash
python3 -m http.server 8777 --bind 127.0.0.1   # then open http://localhost:8777
```

## Refreshing data manually
```bash
python3 pipeline/fetch_pricing.py        # all 8 currencies (~7 min)
python3 pipeline/build_specs.py          # rebuild specs
python3 pipeline/scrape_learn_specs.py   # fill remaining spec gaps
```

## Disclaimer
Not affiliated with Microsoft/Azure. Prices indicative; always confirm in Azure portal.