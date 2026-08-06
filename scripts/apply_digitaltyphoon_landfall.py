#!/usr/bin/env python3
"""Replace landfallJP with the authoritative record from NII Digital
Typhoon's "台風の上陸" list (data/raw/digitaltyphoon_landfall.csv, exported
from https://agora.ex.nii.ac.jp/digital-typhoon/disaster/landfall-full/),
which covers 1951-2025 -- better than both prior sources:
  - the JMA best-track '#' marker (only populated from 1991 onward), and
  - scripts/estimate_pre1991_landfall.py's geometric proxy for the years
    before that (calibrated to roughly match the '#' marker's rate, but
    still just an estimate).

A storm is landfallJP=true iff its code appears in the CSV (i.e. it has at
least one 上陸/再上陸/通過 event on record); every other storm is false,
including ones the '#' marker or the geometric estimate had flagged true --
this file is taken as ground truth over both. Each storm's raw 上陸/再上陸/
通過 events (date, prefecture, location) are also attached as
"landfallEvents" for potential future display.

Usage: python3 scripts/apply_digitaltyphoon_landfall.py
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
CSV_PATH = ROOT / "data" / "raw" / "digitaltyphoon_landfall.csv"


def jma_code_from_digitaltyphoon(dt_code):
    """195106 (Digital Typhoon: 4-digit year + 2-digit seq) -> '5106'
    (this repo's storm code: 2-digit year + 2-digit seq, matching the JMA
    best-track id used throughout data/storms/*.json)."""
    year, seq = divmod(dt_code, 100)
    yy = year % 100
    return f"{yy:02d}{seq:02d}"


def main():
    events_by_code = defaultdict(list)
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = jma_code_from_digitaltyphoon(int(row["台風番号"]))
            events_by_code[code].append({
                "type": row["種別"],
                "date": row["年月日"],
                "pref": row["都道府県"],
                "location": row["地点"],
                "time": row["時間"],
            })

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    matched = 0
    unmatched_dt_codes = []
    for code, events in events_by_code.items():
        if code not in index:
            unmatched_dt_codes.append(code)
            continue
        matched += 1

    changed_true = changed_false = 0
    for code, meta in index.items():
        was = meta.get("landfallJP", False)
        now = code in events_by_code
        if now and not was:
            changed_true += 1
        if was and not now:
            changed_false += 1
        meta["landfallJP"] = now
        meta["landfallJPMethod"] = "digitaltyphoon"

        path = STORMS_DIR / f"{code}.json"
        if path.exists():
            storm = json.loads(path.read_text(encoding="utf-8"))
            storm["landfallJP"] = now
            if now:
                storm["landfallEvents"] = events_by_code[code]
            elif "landfallEvents" in storm:
                del storm["landfallEvents"]
            path.write_text(json.dumps(storm, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    total_true = sum(1 for m in index.values() if m["landfallJP"])
    print(f"digitaltyphoon codes: {len(events_by_code)}, matched to a storm: {matched}, "
          f"unmatched (no corresponding storm in data/index.json): {len(unmatched_dt_codes)}")
    if unmatched_dt_codes:
        print("  unmatched:", unmatched_dt_codes)
    print(f"landfallJP flipped true->false: {changed_false}, false->true: {changed_true}")
    print(f"total landfallJP=true: {total_true} / {len(index)}")


if __name__ == "__main__":
    main()
