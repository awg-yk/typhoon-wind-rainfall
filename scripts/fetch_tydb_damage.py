#!/usr/bin/env python3
"""Fetch per-storm damage data from the 防災科研 台風データベース (TYDB,
https://tydb.bosai.go.jp/TYDB/), one page per storm at
https://tydb.bosai.go.jp/TYDB/HTML/<code>.html.

Each page has (when present):
  - a free-text "気象の状況" paragraph, often ending in a damage summary
    sentence (e.g. "死者・行方不明31人、負傷者41人、全壊796棟...")
  - a structured "被害の状況" table, one row per prefecture plus a total
    row -- this is the more reliable figure since it's structured and
    prefecture-broken-down, rather than a hand-written sentence.

The table's damage columns are NOT the same set on every page -- most
storms have 死者・不明者/負傷者/全壊/半壊/一部破損/床上浸水/床下浸水/非住家,
but some add 焼失 (burned), 流失 (washed away), or other categories (e.g.
TY5508, 1955 Typhoon 8, has a 焼失 column between 一部破損 and 床上浸水).
So the table's own header row is read and used to key each row's values
by column name, rather than assuming a fixed column order/count -- an
earlier version of this script hardcoded 8 columns and would have
silently misaligned or dropped values on pages like that one.

NOTE: this cannot be run inside the current sandboxed session -- outbound
access to tydb.bosai.go.jp is blocked by this environment's network
policy. Run it from a machine with normal internet access, or via
notebooks/fetch_tydb_damage_colab.ipynb.

Output: one data/tydb_damage/<code>.json per storm:
  {"title": "...", "weatherText": "...",
   "prefectures": [{"pref": "...", "dead_missing": int|null, ..., "source": "..."}, ...],
   "total": {same shape as a prefecture row, pref/source omitted}}
Damage-category keys vary per storm (see HEADER_KEY_MAP) -- always check
which keys are actually present in a given storm's rows rather than
assuming the common set. A storm with no TYDB page (404) gets
{"notFound": true}.

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

# Known 被害の状況 column headers -> our key. Any header not listed here
# falls back to the raw (stripped) header text as the key, so an unknown
# damage category (a new source's wording, say) is still captured under
# its own key rather than silently dropped or merged into the wrong column.
HEADER_KEY_MAP = {
    "都道府県": "pref",
    "死者・不明者": "dead_missing",
    "死者・行方不明者": "dead_missing",
    "死者・不明": "dead_missing",
    "死者": "dead",
    "行方不明者": "missing",
    "負傷者": "injured",
    "全壊": "destroyed",
    "半壊": "half_destroyed",
    "流失": "washed_away",
    "全焼": "burned",
    "半焼": "half_burned",
    "焼失": "burned",
    "一部破損": "partial_damage",
    "床上浸水": "flooded_above_floor",
    "床下浸水": "flooded_below_floor",
    "非住家": "non_residential",
    "情報元": "source",
}


def header_key(header_text):
    h = header_text.strip()
    return HEADER_KEY_MAP.get(h, h)


def parse_int(cell_text):
    t = cell_text.strip().replace(",", "")
    return int(t) if t else None


def parse_damage_table(table):
    header_row = table.find("tr")
    headers = [th.get_text(strip=True) for th in header_row.find_all("th")]
    if not headers:
        return [], None
    keys = [header_key(h) for h in headers]  # keys[0] is 都道府県's key ('pref')

    prefectures = []
    total = None
    for tr in table.find_all("tr")[1:]:  # skip header row
        cells = tr.find_all("td")
        if not cells:
            continue
        pref = cells[0].get_text(strip=True)
        row = {}
        for key, cell in zip(keys[1:], cells[1:]):
            text = cell.get_text(strip=True)
            row[key] = text if key == "source" else parse_int(text)
        if pref in ("合　計", "合計"):
            total = row
        elif any(v not in (None, "") for k, v in row.items() if k != "source"):
            row["pref"] = pref
            prefectures.append(row)
    return prefectures, total


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

    prefectures, total = [], None
    table_anchor = soup.find("a", attrs={"name": "table"})
    if table_anchor:
        section = table_anchor.find_parent("section")
        table = section.find("table") if section else None
        if table:
            prefectures, total = parse_damage_table(table)

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
