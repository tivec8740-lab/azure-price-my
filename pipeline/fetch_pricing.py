#!/usr/bin/env python3
"""
azure-price-my — Phase 0 pipeline
Fetches Azure VM + Flexible DB pricing (MYR) for southeastasia & malaysiawest
from the public Retail Prices API. No auth. Output: data/pricing.json (+ last_updated.json)

Usage: python3 pipeline/fetch_pricing.py
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"
CURRENCY = "MYR"
REGIONS = ["southeastasia", "malaysiawest"]

# MYT is UTC+8; keep a local stamp too for Hamzani's reading
MYT = timezone(timedelta(hours=8))

QUERIES = []
for region in REGIONS:
    for family in ("Compute", "Databases"):
        for ptype in ("Consumption", "Reservation"):
            QUERIES.append((region, family, ptype))


def fetch_all(filt: str) -> list:
    """Paginate through the retail prices API until NextPageLink is null."""
    params = {
        "api-version": API_VERSION,
        "currencyCode": CURRENCY,
        "$filter": filt,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    items, pages = [], 0
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "azure-price-my/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items.extend(payload.get("Items", []))
        pages += 1
        url = payload.get("NextPageLink")
        if pages > 500:  # safety valve
            raise RuntimeError("pagination exceeded 500 pages — aborting")
        if url:
            time.sleep(0.3)  # be polite to the free API
    print(f"  [{filt[:70]}...] pages={pages} items={len(items)}")
    return items


def is_excluded(item: dict) -> bool:
    blob = " ".join(str(item.get(k, "")) for k in ("productName", "skuName", "meterName")).lower()
    return any(x in blob for x in (
        "windows", "low priority", "spot",
        "dev/test", "devtest", "dedicated host",
        "cloudservices", "virtual desktop",
        "basic ", "basic_",  # Basic A-series tier — spec says Standard only
    ))


def in_scope(item: dict) -> bool:
    """Scope = VMs (incl. '-series Linux' & Cloud Services variants of VM series,
    mirroring the Claude seed workbook) + PostgreSQL/MySQL Flexible Server only.
    VM product names always reference a 'series'; managed services don't."""
    name = str(item.get("productName", ""))
    low = name.lower()
    if item.get("serviceFamily") == "Compute":
        if any(x in low for x in (
            "app service", "container", "functions", "logic apps",
            "batch", "vmware", "spring", "openshift", "sap", "arc",
            "kubernetes",
        )):
            return False
        return (
            low.startswith("virtual machines")
            or "series" in low
            or "cloud services" in low
        )
    # Databases family (covers both 'Azure Database for…' and 'Az DB for…')
    return low.startswith((
        "azure database for postgresql flexible",
        "azure database for mysql flexible",
        "az db for postgresql flexible",
        "az db for mysql flexible",
    ))


def category_of(item: dict) -> str:
    name = item.get("productName", "")
    if item.get("serviceFamily") != "Databases":
        return "Compute (VM)"
    n = name.lower()
    if "burstable" in n:
        return "Database (Burstable)"
    if "general purpose" in n:
        return "Database (General Purpose)"
    if "memory" in n:
        return "Database (Memory Optimized)"
    return "Database (Other/Storage/Backup)"


def flatten(item: dict) -> list:
    """One row per price point: PAYG + each reservation term + each savings-plan term."""
    rows = [{
        "armSkuName": item.get("armSkuName") or item.get("skuName"),
        "armRegionName": item["armRegionName"],
        "meterName": item.get("meterName"),
        "productName": item.get("productName"),
        "priceType": "Consumption",
        "reservationTerm": "",
        "savingsPlanTerm": "",
        "unitPrice": round(float(item["unitPrice"]), 6),
        "unitOfMeasure": item.get("unitOfMeasure"),
        "effectiveStartDate": item.get("effectiveStartDate", ""),
    }]
    for sp in item.get("savingsPlan") or []:
        rows.append({**rows[0],
                     "priceType": "SavingsPlan",
                     "savingsPlanTerm": sp.get("term"),
                     "unitPrice": round(float(sp["unitPrice"]), 6)})
    return rows


def main() -> int:
    all_rows = []
    seen = set()
    for region, family, ptype in QUERIES:
        filt = (f"armRegionName eq '{region}' and serviceFamily eq '{family}' "
                f"and priceType eq '{ptype}'")
        for item in fetch_all(filt):
            # Reservation queries already carry type=Reservation; Consumption
            # queries carry nested savingsPlan arrays.
            if not in_scope(item) or is_excluded(item):
                continue
            if ptype == "Consumption":
                flat = flatten(item)
            else:
                term = (item.get("reservationTerm") or "").replace("1 Year", "1 Year").strip()
                flat = [{
                    "armSkuName": item.get("armSkuName") or item.get("skuName"),
                    "armRegionName": item["armRegionName"],
                    "meterName": item.get("meterName"),
                    "productName": item.get("productName"),
                    "priceType": "Reservation",
                    "reservationTerm": term,
                    "savingsPlanTerm": "",
                    "unitPrice": round(float(item["unitPrice"]), 6),
                    "unitOfMeasure": item.get("unitOfMeasure"),
                    "effectiveStartDate": item.get("effectiveStartDate", ""),
                }]
            for r in flat:
                key = (r["armSkuName"], r["armRegionName"], r["meterName"], r["productName"],
                       r["priceType"], r["reservationTerm"], r["savingsPlanTerm"])
                if key in seen:
                    continue
                seen.add(key)
                r["category"] = category_of(item)
                all_rows.append(r)

    all_rows.sort(key=lambda r: (r["armSkuName"] or "", r["armRegionName"] or "",
                                 r["category"], r["priceType"]))
    now = datetime.now(MYT)
    meta = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "currency": CURRENCY,
        "regions": REGIONS,
        "rowCount": len(all_rows),
        "source": "Azure Retail Prices API (public)",
        "apiVersion": API_VERSION,
    }
    with open("data/pricing.json.tmp", "w") as f:
        json.dump({"meta": meta, "rows": all_rows}, f, separators=(",", ":"))
    import os
    os.replace("data/pricing.json.tmp", "data/pricing.json")

    with open("data/last_updated.json", "w") as f:
        json.dump({"lastUpdated": meta["generatedAt"], "rowCount": len(all_rows)}, f)

    # ---- validation summary ----
    from collections import Counter
    by_region = Counter(r["armRegionName"] for r in all_rows)
    by_ptype = Counter(r["priceType"] for r in all_rows)
    vm = sum(1 for r in all_rows if r["category"].startswith("Compute"))
    db = len(all_rows) - vm
    win = sum(1 for r in all_rows if "windows" in (r["productName"] or "").lower())
    print(f"\nDONE {now.strftime('%Y-%m-%d %H:%M %Z')}: {len(all_rows)} rows")
    print(f"  regions: {dict(by_region)}")
    print(f"  priceTypes: {dict(by_ptype)}  VM={vm} DB={db}  WindowsRows={win}")
    baseline = 10985
    if not (baseline * 0.85 <= len(all_rows) <= baseline * 1.15):
        print(f"  ⚠️ row count outside ±15% of Claude baseline ({baseline}) — inspect before deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
