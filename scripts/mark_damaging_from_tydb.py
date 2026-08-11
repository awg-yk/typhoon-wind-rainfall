#!/usr/bin/env python3
"""Set damaging: true in data/index.json for storms that have real (nonzero)
TYDB damage data but aren't already flagged landfallJP or damaging.

data/index.json's damaging flag was originally seeded from the Digital
Typhoon disaster database's death/missing ranking (data/damage_storm_codes.json,
70 storms). fetch_tydb_damage.py --all later found TYDB has real damage
tables for many more storms outside that set (455 total with an actual
nonzero damage table, per scripts/list_damage_gaps.py's has_real_damage_table()
-- see there for what counts as "real": a total or prefecture row with at
least one nonzero field, not just an empty/all-zero table).

Without this flag, those storms are invisible under the default
"上陸・通過や被害のあった台風のみ" filter in the frontend (index.html's
f.landfallOnly check), and are skipped by default (--codes-less) runs of
fetch_amedas_obsdl.py/download_jra3q_pressure.py/build_pressure_json.py.

Usage:
  python3 scripts/mark_damaging_from_tydb.py           # apply and write index.json
  python3 scripts/mark_damaging_from_tydb.py --dry-run # just report what would change
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "index.json"
DAMAGE_DIR = ROOT / "data" / "tydb_damage"


def row_has_nonzero(row):
    return any((row.get(k) or 0) != 0 for k in row if k not in ("pref", "source"))


def has_real_damage_table(code):
    p = DAMAGE_DIR / f"{code}.json"
    if not p.exists():
        return False
    d = json.loads(p.read_text(encoding="utf-8"))
    total = d.get("total")
    if total and row_has_nonzero(total):
        return True
    return any(row_has_nonzero(row) for row in (d.get("prefectures") or []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = ap.parse_args()

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    real_damage_codes = sorted(p.stem for p in DAMAGE_DIR.glob("*.json") if has_real_damage_table(p.stem))

    newly_marked = []
    for code in real_damage_codes:
        meta = index.get(code)
        if meta is None:
            continue  # shouldn't happen -- tydb_damage codes come from index.json's own keys
        if meta.get("landfallJP") or meta.get("damaging"):
            continue
        newly_marked.append(code)
        if not args.dry_run:
            meta["damaging"] = True

    print(f"{len(real_damage_codes)} storms with real TYDB damage data")
    print(f"{len(newly_marked)} newly marked damaging=true: {', '.join(newly_marked)}")

    if not args.dry_run and newly_marked:
        # data/index.json is stored compact (no indentation/spaces) -- match that
        # so the diff is just the added "damaging":true fields, not a reformat.
        INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {INDEX_PATH}")


if __name__ == "__main__":
    main()
