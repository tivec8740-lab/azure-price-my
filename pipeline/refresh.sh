#!/usr/bin/env bash
# azure-price-my nightly refresh. No-op (silent success) when data unchanged.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 pipeline/fetch_pricing.py >/tmp/apm_fetch.log 2>&1 || { echo "FETCH FAILED:"; tail -20 /tmp/apm_fetch.log; exit 1; }

# Only commit+push when the data actually changed (avoids empty deploys).
if ! git diff --quiet -- data/ | grep -q . || git status --porcelain | grep -q '^ M data/'; then
  git add data/pricing_*.json data/last_updated.json
  git commit -qm "chore: refresh pricing data via Azure Retail API"
  git pull --rebase --autostash -q origin main && git push -q origin main
  echo "Refreshed and deployed: $(head -c 100 data/last_updated.json)"
else
  echo "No price changes since last refresh — nothing to deploy."
fi