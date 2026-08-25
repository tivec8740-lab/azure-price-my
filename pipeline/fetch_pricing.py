#!/usr/bin/env python3
"""
azure-price-my — data pipeline
Fetches Azure VM + Flexible DB pricing for a set of APAC regions and currencies
from the public Retail Prices API (no auth). Outputs one file per currency:
  data/pricing_<cc>.json   (e.g. pricing_myr.json, pricing_usd.json)
  data/specs.json          (region-independent, built separately)

Usage: python3 pipeline/fetch_pricing.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta

API = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"
REGIONS = [
    "southeastasia",   # Singapore
    "malaysiawest",    # Malaysia
    "eastasia",        # Hong Kong
    "japaneast",       # Tokyo
    "japanwest",       # Osaka
    "koreacentral",    # Seoul
    "centralindia",    # Pune
    "southindia",      # Chennai
    "australiaeast",   # Sydney
]
CURRENCIES = ["MYR", "USD", "SGD", "AUD", "EUR", "GBP", "INR", "JPY"]
MYT = timezone(timedelta(hours=8))


def fetch_all(filt: str) -> list:
    """Paginate through the retail prices API until NextPageLink is null."""
    params = {"api-version": API_VERSION, "currencyCode": filt["currencyCode"],
              "$filter": filt["$filter"]}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    items, pages = [], 0
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "azure-price-my/0.2"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items.extend(payload.get("Items", []))
        pages += 1
        url = payload.get("NextPageLink")
        if pages > 600:  # safety valve
            raise RuntimeError("pagination exceeded 600 pages — aborting")
        if url:
            time.sleep(0.25)
    if pages % 10 == 0 or True:
        pass
    return items


def is_excluded(item: dict) -> bool:
    blob = " ".join(str(item.get(k, "")) for k in ("productName", "skuName", "meterName")).lower()
    return any(x in blob for x in (
        "windows", "low priority", "spot", "dev/test", "devtest",
        "dedicated host", "dedicatedhost",  # per-physical-host pricing, not per-VM
        "cloudservices", "virtual desktop",
        "basic ", "basic_",  # Basic A-series tier — spec says Standard only
    ))


def in_scope(item: dict) -> bool:
    """VMs (incl. '-series Linux' & Cloud Services variants of VM series) +
    PostgreSQL/MySQL Flexible Server only. VM names always reference a 'series'."""
    name = str(item.get("productName", ""))
    low = name.lower()
    if item.get("serviceFamily") == "Compute":
        if any(x in low for x in (
            "app service", "container", "functions", "logic apps",
            "batch", "vmware", "spring", "openshift", "sap", "arc", "kubernetes",
        )):
            return False
        return low.startswith("virtual machines") or "series" in low or "cloud services" in low
    return low.startswith((
        "azure database for postgresql flexible", "azure database for mysql flexible",
        "az db for postgresql flexible", "az db for mysql flexible",
    ))


def category_of(item: dict) -> str:
    name = str(item.get("productName", "")).lower()
    if item.get("serviceFamily") != "Databases":
        return "Compute (VM)"
    if "burstable" in name:
        return "Database (Burstable)"
    if "general purpose" in name:
        return "Database (General Purpose)"
    if "memory" in name:
        return "Database (Memory Optimized)"
    return "Database (Other/Storage/Backup)"


def flatten(item: dict) -> list:
    rows = [{
        "armSkuName": item.get("armSkuName") or item.get("skuName"),
        "armRegionName": item["armRegionName"],
        "meterName": item.get("meterName"),
        "productName": item.get("productName"),
        "priceType": "Consumption",
        "reservationTerm": "", "savingsPlanTerm": "",
        "unitPrice": round(float(item["unitPrice"]), 6),
        "unitOfMeasure": item.get("unitOfMeasure"),
        "effectiveStartDate": item.get("effectiveStartDate", ""),
    }]
    for sp in item.get("savingsPlan") or []:
        rows.append({**rows[0], "priceType": "SavingsPlan",
                     "savingsPlanTerm": sp.get("term"),
                     "unitPrice": round(float(sp["unitPrice"]), 6)})
    return rows


HOURS_IN_TERM = {"1 Year": 8760, "3 Years": 26280, "5 Years": 43800}


def build_currency_data(currency: str) -> dict:
    rows, seen = [], set()
    for region in REGIONS:
        for family in ("Compute", "Databases"):
            for ptype in ("Consumption", "Reservation"):
                filt = {"currencyCode": currency,
                        "$filter": f"armRegionName eq '{region}' and serviceFamily eq '{family}' and priceType eq '{ptype}'"}
                for item in fetch_all(filt):
                    if not in_scope(item) or is_excluded(item):
                        continue
                    if ptype == "Consumption":
                        flat = flatten(item)
                    else:
                        # Reservation meters from the retail API are quoted as the
                        # TOTAL over the whole term; convert to a per-hour rate so
                        # they compare directly with PAYG / SavingsPlan hourly.
                        term = (item.get("reservationTerm") or "")
                        hours = HOURS_IN_TERM.get(term)
                        total = float(item["unitPrice"])
                        hourly = round(total / hours, 6) if hours else total
                        flat = [{
                            "armSkuName": item.get("armSkuName") or item.get("skuName"),
                            "armRegionName": item["armRegionName"],
                            "meterName": item.get("meterName"),
                            "productName": item.get("productName"),
                            "priceType": "Reservation",
                            "reservationTerm": term,
                            "savingsPlanTerm": "",
                            "unitPrice": hourly,
                            "unitOfMeasure": "1 Hour",
                            "effectiveStartDate": item.get("effectiveStartDate", ""),
                        }]
                    for r in flat:
                        key = (r["armSkuName"], r["armRegionName"], r["meterName"],
                               r["productName"], r["priceType"],
                               r["reservationTerm"], r["savingsPlanTerm"])
                        if key in seen:
                            continue
                        seen.add(key)
                        r["category"] = category_of(item)
                        rows.append(r)

    rows.sort(key=lambda r: (r["armSkuName"] or "", r["armRegionName"] or "",
                             r["category"], r["priceType"]))
    now = datetime.now(MYT)
    return {
        "meta": {
            "generatedAt": now.isoformat(timespec="seconds"),
            "currency": currency,
            "regions": REGIONS,
            "rowCount": len(rows),
            "source": "Azure Retail Prices API (public)",
            "apiVersion": API_VERSION,
        },
        "rows": rows,
    }


def main() -> int:
    summary = {}
    for currency in CURRENCIES:
        data = build_currency_data(currency)
        cc = currency.lower()
        tmp, out = f"data/pricing_{cc}.json.tmp", f"data/pricing_{cc}.json"
        with open(tmp, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, out)
        by_region = Counter(r["armRegionName"] for r in data["rows"])
        vm = sum(1 for r in data["rows"] if r["category"].startswith("Compute"))
        win = sum(1 for r in data["rows"] if "windows" in (r["productName"] or "").lower())
        summary[currency] = len(data["rows"])
        print(f"[{currency}] {len(data['rows'])} rows | regions {dict(by_region)} | VM={vm} DB={len(data['rows'])-vm} Windows={win}")

    with open("data/last_updated.json", "w") as f:
        json.dump({
            "lastUpdated": datetime.now(MYT).isoformat(timespec="seconds"),
            "currencies": CURRENCIES,
            "regions": REGIONS,
            "rowsByCurrency": summary,
        }, f)
    print("DONE:", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())