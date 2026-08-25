# azure-price-my

Azure VM & Flexible Database pricing explorer for **Southeast Asia** vs **Malaysia West** — in **MYR**.

Live: https://tivec8740-lab.github.io/azure-price-my/

## What it shows
- ~1,500 VM SKUs + PostgreSQL/MySQL Flexible Server tiers, Linux Standard tier only
- 5 price points each: PAYG, 1Y/3Y Reserved Instances, 1Y/3Y Savings Plans
- Side-by-side region columns with MYW-vs-SEA % difference
- Specs (vCPU / RAM / temp disk) joined per SKU where documented

## Data
- Source: [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (public, unauthenticated), `api-version=2023-01-01-preview`, currency `MYR`
- Refreshed **nightly** from a private pipeline; `data/last_updated.json` carries the stamp
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
