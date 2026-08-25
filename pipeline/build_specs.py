#!/usr/bin/env python3
"""
azure-price-my — specs builder (v1 seed mode)
Extracts the Specs sheet from the Claude Desktop workbook into data/specs.json.
The xlsx is a raw zip of XML; parse with stdlib only (no pandas/openpyxl on this box).

Run once at setup, or whenever the seed workbook is refreshed:
  python3 pipeline/build_specs.py
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

SEED = "pipeline/seed/claude_specs_seed.xlsx"
MYT = timezone(timedelta(hours=8))
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def col_to_idx(ref: str) -> int:
    m = re.match(r"([A-Z]+)", ref)
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + ord(ch) - 64
    return idx - 1


def read_sheet(z: zipfile.ZipFile, target: str) -> list:
    root = ET.fromstring(z.read(target))
    rows = []
    for row in root.iter("{%s}row" % NS["m"]):
        vals = {}
        for c in row:
            ref = c.get("r") or ""
            i = col_to_idx(ref) if ref else len(vals)
            v = c.find("m:v", NS)
            is_node = c.find("m:is", NS)
            if v is not None:
                vals[i] = v.text or ""
            elif is_node is not None:
                vals[i] = "".join(t.text or "" for t in is_node.iter("{%s}t" % NS["m"]))
        if vals:
            width = max(vals) + 1
            rows.append([vals.get(i, "") for i in range(width)])
    return rows


def main() -> int:
    z = zipfile.ZipFile(SEED)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.get("Id"): rel.get("Target") for rel in rels}

    target = None
    for s in wb.find("m:sheets", NS):
        if s.get("name") == "Specs":
            t = relmap[s.get(RELNS)].lstrip("/")
            target = t if t.startswith("xl/") else "xl/" + t
            break
    if not target:
        sys.exit("Specs sheet not found in seed workbook")

    rows = read_sheet(z, target)
    header, body = rows[0], rows[1:]

    # Rename aliases: Azure docs renamed some sizes but the pricing API keeps
    # the legacy armSkuName. Alias maps priced-SKU -> documented-SKU hardware.
    ALIASES = {
        "Standard_B1ls": "Standard_B1ls2",  # bv1-series rename in Learn docs
    }

    # Manually verified specs for series missing from the seed scrape.
    # Source: Microsoft Learn size pages (transcribed verbatim).
    MANUAL_SPECS = {
        # av2-series (learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/av2-series)
        "Standard_A1_v2":  {"series": "av2-series", "vCPUs": 1, "memoryGB": 2,  "tempDiskGB": 10, "premiumStorage": False, "maxDataDisks": 2},
        "Standard_A2_v2":  {"series": "av2-series", "vCPUs": 2, "memoryGB": 4,  "tempDiskGB": 20, "premiumStorage": False, "maxDataDisks": 4},
        "Standard_A4_v2":  {"series": "av2-series", "vCPUs": 4, "memoryGB": 8,  "tempDiskGB": 40, "premiumStorage": False, "maxDataDisks": 8},
        "Standard_A8_v2":  {"series": "av2-series", "vCPUs": 8, "memoryGB": 16, "tempDiskGB": 80, "premiumStorage": False, "maxDataDisks": 16},
        "Standard_A2m_v2": {"series": "av2-series", "vCPUs": 2, "memoryGB": 16, "tempDiskGB": 20, "premiumStorage": False, "maxDataDisks": 4},
        "Standard_A4m_v2": {"series": "av2-series", "vCPUs": 4, "memoryGB": 32, "tempDiskGB": 40, "premiumStorage": False, "maxDataDisks": 8},
        "Standard_A8m_v2": {"series": "av2-series", "vCPUs": 8, "memoryGB": 64, "tempDiskGB": 80, "premiumStorage": False, "maxDataDisks": 16},
    }

    specs = []
    for r in body:
        d = dict(zip(header, r + [""] * (len(header) - len(r))))
        try:
            sku = d["armSkuName"].strip()
            if not sku:
                continue
            specs.append({
                "armSkuName": sku,
                "series": d.get("series", ""),
                "vCPUs": int(float(d.get("vCPUs") or 0)),
                "memoryGB": float(d.get("MemoryGB") or 0),
                # '' -> null (unknown), '0'/'None' -> 0
                "tempDiskGB": int(float(d["TempDiskGB"])) if str(d.get("TempDiskGB", "")).strip() else None,
                "premiumStorage": d.get("PremiumStorageSupported", "").strip() == "Supported",
                "maxDataDisks": int(d["MaxDataDisks"]) if str(d.get("MaxDataDisks", "")).strip().isdigit() else None,
            })
        except (ValueError, KeyError) as e:
            print(f"  skip {d.get('armSkuName', '?')}: {e}")

    # Emit alias rows (priced name inherits documented hardware)
    by_name = {s["armSkuName"]: s for s in specs}
    for priced, documented in ALIASES.items():
        if priced not in by_name and documented in by_name:
            clone = dict(by_name[documented])
            clone["armSkuName"] = priced
            specs.append(clone)

    # Merge manual specs for SKUs the seed lacks
    added = 0
    by_name = {s["armSkuName"] for s in specs}
    for sku, spec in MANUAL_SPECS.items():
        if sku not in by_name:
            entry = {"armSkuName": sku, **spec}
            specs.append(entry)
            added += 1
    if added:
        print(f"  + {added} manual specs merged")

    now = datetime.now(MYT)
    out = {
        "meta": {
            "generatedAt": now.isoformat(timespec="seconds"),
            "source": f"Claude Desktop workbook seed ({len(specs)} SKUs)",
            "note": "Specs are region-independent; refresh only when new series launch.",
        },
        "rows": sorted(specs, key=lambda s: s["armSkuName"]),
    }
    import os
    with open("data/specs.json.tmp", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace("data/specs.json.tmp", "data/specs.json")
    print(f"DONE: {len(specs)} SKUs written to data/specs.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
