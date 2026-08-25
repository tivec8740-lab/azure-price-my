# azure-price-my

Azure VM & Flexible Database pricing explorer for **Southeast Asia** vs **Malaysia West** — in **MYR**.

Live: https://tivec8740-lab.github.io/azure-price-my/

## What it shows
- ~1,600 VM SKUs + PostgreSQL/MySQL Flexible Server tiers, Linux Standard tier only
- 5 APAC regions: Southeast Asia (SG), Malaysia West, East Asia (HK), Japan East, Australia East
- 2 currencies: MYR + USD
- 5 price points: PAYG, 1Y/3Y Reserved Instances, 1Y/3Y Savings Plans
- Pick your region → see the market-cheapest region, its price, and the **% you could save** vs your region
- Specs (vCPU / RAM / temp disk) joined per SKU where documented

## Data
- Source: [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (public, unauthenticated), `api-version=2023-01-01-preview`
- One file per currency: `data/pricing_myr.json`, `data/pricing_usd.json` (31k price points each)
- Reserved-Instance rates are displayed as the **amortized per-hour** price (API quotes the multi-year total; we divide by 8760/26280/43800 hours). Savings Plans are already per-hour.
- Refreshed **nightly** from a private pipeline; `data/last_updated.json` carries the stamp.
- Specs seeded from Microsoft Learn documentation (legacy series without current docs show prices only)
- Excluded: Windows, Basic tier, Spot, Low-priority, Dev/Test, Dedicated Host

## Repo layout
```
index.html / app.js / style.css   static site (GitHub Pages)
data/                             generated pricing.json + specs.json (auto-updated)
pipeline/fetch_pricing.py         nightly fetcher (stdlib only)
pipeline/build_specs.py           specs builder from seed workbook
pipeline/seed/                    reference workbook
```

## Run the pipeline locally
```bash
python3 pipeline/fetch_pricing.py   # refresh data/pricing.json
python3 pipeline/build_specs.py     # rebuild data/specs.json from seed
python3 -m http.server 8777         # serve, then open http://localhost:8777
```

## Disclaimer
Not affiliated with Microsoft or Azure. Prices are indicative retail rates and may differ
from your invoice — always confirm in the Azure portal.
