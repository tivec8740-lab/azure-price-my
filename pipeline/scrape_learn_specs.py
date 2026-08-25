#!/usr/bin/env python3
"""
azure-price-my — Learn specs scraper (gap filler)

For every priced VM SKU that still lacks specs after the seed + manual entries,
find its family page on Microsoft Learn and transcribe the size tables:
  - "vCPUs (Qty.) and Memory for each size"
  - "Local (temp) storage info for each size"  (absent => tempDisk 0/None)
  - "Remote (uncached) storage info ..."       -> Max data disks
  - Feature support table                       -> Premium storage supported?

Only fetches each family page once per run. Results merge into data/specs.json.
Run AFTER build_specs.py: python3 pipeline/scrape_learn_specs.py
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

MYT = timezone(timedelta(hours=8))

OVERVIEW_URL = "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview"

# Families we deliberately do NOT chase (retired v1 gens / non-VM oddities)
SKIP_PREFIXES = ("Standard_A0", "Standard_A1", "Standard_A10", "Standard_A11",
                 "Standard_D1", "Standard_D2", "Standard_D3", "Standard_D4", "Standard_D5",
                 "Standard_D11", "Standard_D12", "Standard_D13", "Standard_D14",
                 "Standard_DS1", "Standard_DS2", "Standard_DS3", "Standard_DS4", "Standard_DS5",
                 "Standard_DS11", "Standard_DS12", "Standard_DS13", "Standard_DS14",
                 "Standard_F1", "Standard_F2", "Standard_F4", "Standard_F8", "Standard_F16",
                 "Standard_G1", "Standard_G2", "Standard_G3", "Standard_G4", "Standard_G5",
                 "Standard_GS1", "Standard_GS2", "Standard_GS3", "Standard_GS4", "Standard_GS5",
                 "Standard_L4s", "Standard_L8s", "Standard_L16s", "Standard_L32s",
                 "Standard_SQLG", "Standard_NM")


def strip_tags(seg: str) -> str:
    t = re.sub(r"<[^>]+>", "|", seg)
    return re.sub(r"\|+", "|", t)


def parse_tables(md: str) -> dict:
    """Extract per-size spec dict from a raw markdown size page."""
    specs = {}

    def grab(header_kw: str, col_index: int, key: str):
        """Parse the markdown table that directly follows header_kw.
        Stops at the first non-matching line AFTER the table starts, so we
        never bleed into a following unrelated table."""
        i = md.find(header_kw)
        if i == -1:
            return
        started = False
        for raw in md[i:].splitlines():
            line = raw.strip()
            m = re.match(r"\|\s*(Standard_[A-Za-z0-9_\-]+[a-z0-9])\s*\|(.+)\|", line)
            if m:
                started = True
                cells = [c.strip().replace(",", "") for c in m.group(2).split("|")]
                if len(cells) <= col_index:
                    continue
                try:
                    num = float(cells[col_index])
                except ValueError:
                    continue
                specs.setdefault(m.group(1), {})[key] = (
                    int(num) if float(num).is_integer() and key != "memoryGB" else num
                )
            elif started:
                break

    grab("vCPUs (Qty.) and Memory", 0, "vCPUs")     # first data col after name
    grab("vCPUs (Qty.) and Memory", 1, "memoryGB")  # second data col
    grab("Temp Disk Size (GiB)", 1, "tempDiskGB")   # cols: Qty | Size GiB | ...
    grab("Max Remote Storage Disks", 0, "maxDataDisks")

    # premium storage support from the feature-support table
    i = md.find("| Premium Storage |")
    supported = True
    if i > -1:
        seg = md[i:i + 120]
        supported = "Not Supported" not in seg

    # Plausibility guard: drop rows whose vCPU/RAM disagree wildly (parser noise)
    def plausible(s):
        v, mem = s.get("vCPUs"), s.get("memoryGB")
        if v is None or mem is None:
            return False
        ratio = mem / max(v, 1)
        return 0.5 <= ratio <= 64  # Azure families run ~1-16 GiB/vCPU; H-series up to ~8

    return {k: v for k, v in specs.items() if plausible(v)}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "azure-price-my/0.3"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "ignore")


def discover_family_urls() -> list:
    """List every size-family doc as raw markdown from MicrosoftDocs/azure-compute-docs.
    Much more complete + stable than parsing the rendered overview page."""
    req = urllib.request.Request(
        "https://api.github.com/repos/MicrosoftDocs/azure-compute-docs/git/trees/main?recursive=1",
        headers={"User-Agent": "azure-price-my/0.3", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tree = json.loads(r.read().decode())
    urls = []
    for item in tree.get("tree", []):
        p = item.get("path", "")
        if p.startswith("articles/virtual-machines/sizes/") and p.endswith("-series.md"):
            urls.append("https://raw.githubusercontent.com/MicrosoftDocs/azure-compute-docs/main/" + p)
    return sorted(urls)


def main() -> int:
    pricing = json.load(open("data/pricing_myr.json"))
    specs_doc = json.load(open("data/specs.json"))
    have = {r["armSkuName"] for r in specs_doc["rows"]}
    priced = sorted({r["armSkuName"] for r in pricing["rows"]
                     if r["category"] == "Compute (VM)" and r["priceType"] == "Consumption"})
    missing = [x for x in priced
               if x not in have and not x.startswith(SKIP_PREFIXES) and " " not in x]
    print(f"{len(missing)} SKUs to chase")
    if not missing:
        print("nothing to do — specs fully covered for eligible SKUs")
        return 0

    added = {}
    pages = 0
    seen_names = {}
    for url in discover_family_urls():
        if len(added) >= len(missing):
            break
        try:
            html = fetch(url)
        except Exception as e:
            print(f"! {url}: {e}")
            continue
        pages += 1
        time.sleep(0.4)
        page = parse_tables(html)
        # remember which names each page defines so we can attribute 'series'
        slug = url.rsplit("/", 1)[-1].replace("-series", "")
        for name, spec in page.items():
            seen_names[name] = slug
            if name in missing and name not in added:
                added[name] = {"series": slug, **spec}
        if pages % 10 == 0:
            print(f"  …{pages} pages, recovered {len(added)}")

    print(f"scraped {pages} family pages; recovered {len(added)} of {len(missing)}")

    # Canonical constrained-core map from Microsoft's own constrained-vcpu.md:
    # | Standard_M8-2ms | 2 | M8ms |  → M8ms hardware with vCPU overridden to 2.
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/MicrosoftDocs/azure-compute-docs/main/articles/virtual-machines/constrained-vcpu.md",
            headers={"User-Agent": "azure-price-my/0.3"})
        cvcpu = urllib.request.urlopen(req, timeout=40).read().decode()
        by_name = {r["armSkuName"]: r for r in specs_doc["rows"] + [{"armSkuName": k, **v} for k, v in added.items()]}
        derived = {}
        for line in cvcpu.splitlines():
            m = re.match(r"\|\s*(Standard_[A-Za-z0-9_\-]+)\s*\|\s*(\d+)\s*\|\s*(Standard_[A-Za-z0-9_\-]+)\s*\|", line)
            if not m:
                continue
            sku, vcpus, base = m.group(1), int(m.group(2)), m.group(3)
            if sku in by_name or sku not in missing:
                continue
            src = by_name.get(base)
            if not src and (base + "2") in by_name:
                src = by_name[base + "2"]   # renamed base
            if not src:
                continue
            spec = dict(src)
            spec["vCPUs"] = vcpus
            spec["note"] = f"constrained core of {base}"
            derived[sku] = spec
        if derived:
            print(f"derived {len(derived)} constrained cores via constrained-vcpu.md")
            added.update({k: v for k, v in derived.items() if k not in added})
    except Exception as e:
        print(f"! constrained-vcpu.md fetch failed: {e}")

    # Doc-rename aliases: Azure renames sizes (E104id_v5 -> E104id_v52); the API keeps
    # the legacy name. If <sku>+'2' has specs, inherit it.
    by_name = {r["armSkuName"]: r for r in specs_doc["rows"] + [{"armSkuName": k, **v} for k, v in added.items()]}
    renamed = {}
    for sku in missing:
        alt = sku + "2"
        if alt in by_name:
            spec = dict(by_name[alt])
            spec["note"] = f"renamed from {alt} in docs"
            renamed[sku] = spec
    if renamed:
        print(f"aliased {len(renamed)} doc-renamed SKUs")
        added.update({k: v for k, v in renamed.items() if k not in added})

    # Retired original A / D / F / G families: transcribe published archived specs
    # (resource size). Source: Microsoft "previous-generations" docs.
    RETIRED_SPECS = {  # name: (vCPUs, RAM_GB, temp_disk_GB)
        "Standard_A0": (1, 0.768, 20), "Standard_A1": (1, 1.75, 70), "Standard_A2": (2, 3.5, 135),
        "Standard_A3": (4, 7.0, 285), "Standard_A4": (8, 14.0, 605),
        "Standard_A5": (2, 14.0, 135), "Standard_A6": (4, 28.0, 285), "Standard_A7": (8, 56.0, 605),
        "Standard_A8": (8, 56.0, 382), "Standard_A9": (16, 112.0, 382), "Standard_A10": (8, 56.0, 382),
        "Standard_A11": (16, 112.0, 382),
        "Standard_D1": (1, 3.5, 50), "Standard_D2": (2, 7.0, 100), "Standard_D3": (4, 14.0, 200),
        "Standard_D4": (8, 28.0, 400), "Standard_D11": (2, 14.0, 100), "Standard_D12": (4, 28.0, 200),
        "Standard_D13": (8, 56.0, 400), "Standard_D14": (16, 112.0, 800),
        "Standard_DS1": (1, 3.5, 7), "Standard_DS2": (2, 7.0, 14), "Standard_DS3": (4, 14.0, 28),
        "Standard_DS4": (8, 28.0, 56), "Standard_DS11": (2, 14.0, 28), "Standard_DS12": (4, 28.0, 56),
        "Standard_DS13": (8, 56.0, 112), "Standard_DS14": (16, 112.0, 224),
        "Standard_F1": (1, 2.0, 16), "Standard_F2": (2, 4.0, 32), "Standard_F4": (4, 8.0, 64),
        "Standard_F8": (8, 16.0, 128), "Standard_F16": (16, 32.0, 256),
        "Standard_G1": (2, 28.0, 285), "Standard_G2": (4, 56.0, 605), "Standard_G3": (8, 112.0, 1195),
        "Standard_G4": (16, 224.0, 1245), "Standard_G5": (32, 448.0, 1335),
        "Standard_GS1": (2, 28.0, 56), "Standard_GS2": (4, 56.0, 112), "Standard_GS3": (8, 112.0, 224),
        "Standard_GS4": (16, 224.0, 448), "Standard_GS5": (32, 448.0, 896),
    }
    retired_added = {}
    for sku, (v, ram, tmp) in RETIRED_SPECS.items():
        if sku in missing:
            retired_added[sku] = {
                "series": "retired", "vCPUs": v, "memoryGB": ram,
                "tempDiskGB": tmp, "premiumStorage": False, "maxDataDisks": None,
                "note": "retired classic size",
            }
    if retired_added:
        print(f"added {len(retired_added)} retired classic specs")
        added.update({k: v for k, v in retired_added.items() if k not in added})
    if derived:
        print(f"derived {len(derived)} constrained-core SKUs")
        added.update({k: v for k, v in derived.items() if k not in added})
    if added:
        have_names = {r["armSkuName"] for r in specs_doc["rows"]}
        merged = specs_doc["rows"] + [
            {"armSkuName": k, **{kk: vv for kk, vv in v.items() if kk != "armSkuName"}}
            for k, v in added.items() if k not in have_names
        ]
        # dedupe by armSkuName (last wins), then sort
        dedup = {}
        for r in merged:
            dedup[r["armSkuName"]] = r
        merged = list(dedup.values())
        now = datetime.now(MYT)
        out = {
            "meta": {
                "generatedAt": now.isoformat(timespec="seconds"),
                "source": "Claude seed + manual + Microsoft Learn scrape",
                "note": "Specs are region-independent.",
            },
            "rows": sorted(merged, key=lambda s: s["armSkuName"]),
        }
        with open("data/specs.json.tmp", "w") as f:
            json.dump(out, f, separators=(",", ":"))
        os.replace("data/specs.json.tmp", "data/specs.json")
        print(f"DONE: {len(merged)} total spec rows")
    else:
        print("nothing new to merge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
