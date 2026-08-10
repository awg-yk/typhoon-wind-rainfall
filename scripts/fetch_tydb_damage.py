#!/usr/bin/env python3
"""Fetch per-storm damage data from the 防災科研 台風データベース (TYDB,
https://tydb.bosai.go.jp/TYDB/), one page per storm at
https://tydb.bosai.go.jp/TYDB/HTML/<code>.html.

Each page has (when present):
  - a free-text "気象の状況" paragraph, often ending in a damage summary
    sentence (e.g. "死者・行方不明31人、負傷者41人、全壊796棟...")
  - a structured "被害の状況" table, one row per prefecture plus a total
    row, with columns 死者・不明者/負傷者/全壊/半壊/一部破損/床上浸水/
    床下浸水/非住家 and a 情報元 (source) column -- this is the more
    reliable figure since it's structured and prefecture-broken-down,
    rather than a hand-written sentence.

NOTE: this cannot be run inside the current sandboxed session -- outbound
access to tydb.bosai.go.jp is blocked by this environment's network
policy. Run it from a machine with normal internet access, or via
notebooks/fetch_tydb_damage_colab.ipynb.

Output: one data/tydb_damage/<code>.json per storm:
  {"title": "...", "weatherText": "...",
   "prefectures": [{"pref": "...", "dead_missing": int|null, ...,
                     "source": "..."}, ...],
   "total": {same shape as a prefecture row, pref omitted}}
A storm with no TYDB page (404) gets {"notFound": true}.

Usage:
  pip install requests beautifulsoup4
  python3 scripts/fetch_tydb_damage.py --landfall-only
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "index.json"
OUT_DIR = ROOT / "data" / "tydb_damage"

BASE_URL = "https://tydb.bosai.go.jp/TYDB/HTML/{code}.html"
SLEEP_SEC = 0.5

# Order matches the table's columns, left to right, after 都道府県.
PREF_COLUMNS = [
    "dead_missing", "injured", "destroyed", "half_destroyed",
    "partial_damage", "flooded_above_floor", "flooded_below_floor",
    "non_residential",
]


def parse_int(cell_text):
    t = cell_text.strip().replace(",", "")
    return int(t) if t else None


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    h2 = soup.find("h2")
    if h2:
        result["title"] = " ".join(h2.get_text().split())

    weather_anchor = soup.find("a", attrs={"name": "weather"})
    if weather_anchor:
        section = weather_anchor.find_parent("section")
        p = section.find("p") if section else None
        if p:
            result["weatherText"] = " ".join(p.get_text().split())

    prefectures = []
    total = None
    table_anchor = soup.find("a", attrs={"name": "table"})
    if table_anchor:
        section = table_anchor.find_parent("section")
        table = section.find("table") if section else None
        if table:
            for tr in table.find_all("tr")[1:]:  # skip header row
                cells = tr.find_all("td")
                if len(cells) < 9:
                    continue
                pref = cells[0].get_text(strip=True)
                nums = [parse_int(c.get_text()) for c in cells[1:9]]
                source = cells[9].get_text(strip=True) if len(cells) > 9 else ""
                row = dict(zip(PREF_COLUMNS, nums))
                row["source"] = source
                if pref in ("合　計", "合計"):
                    total = row
                elif any(v is not None for v in nums):
                    row["pref"] = pref
                    prefectures.append(row)

    result["prefectures"] = prefectures
    result["total"] = total
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated storm codes, e.g. 5615,5915")
    ap.add_argument("--landfall-only", action="store_true",
                     help="use all landfallJP or damaging storms from data/index.json")
    ap.add_argument("--dry-run", action="store_true", help="print the fetch plan without fetching")
    args = ap.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.landfall_only:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        codes = [c for c, m in index.items() if m.get("landfallJP") or m.get("damaging")]
    else:
        sys.exit("specify --codes or --landfall-only")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    failures = []
    for i, code in enumerate(codes, 1):
        out_path = OUT_DIR / f"{code}.json"
        if out_path.exists():
            print(f"[{i}/{len(codes)}] {code}: already have, skipping")
            continue
        if args.dry_run:
            print(f"[{i}/{len(codes)}] {code}: would fetch {BASE_URL.format(code=code)}")
            continue

        url = BASE_URL.format(code=code)
        try:
            res = session.get(url, timeout=30)
            if res.status_code == 404:
                out_path.write_text(json.dumps({"notFound": True}, ensure_ascii=False), encoding="utf-8")
                print(f"[{i}/{len(codes)}] {code}: 404 (no TYDB page)")
                continue
            res.raise_for_status()
            res.encoding = res.apparent_encoding or "utf-8"
            data = parse_page(res.text)
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            total = data.get("total")
            print(f"[{i}/{len(codes)}] {code}: ok" + (f" (total: {total})" if total else " (no damage table)"))
        except Exception as e:  # noqa: BLE001 - keep going through the rest of the run
            print(f"[{i}/{len(codes)}] {code}: FAILED ({e})")
            failures.append(code)
        time.sleep(SLEEP_SEC)

    if failures:
        print()
        print(f"{len(failures)} failed: {', '.join(failures)}")
        print("Re-run the same command to retry just these (already-successful ones are skipped).")


if __name__ == "__main__":
    main()
