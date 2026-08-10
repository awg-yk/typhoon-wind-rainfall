#!/usr/bin/env python3
"""List storms that have TYDB damage data (data/tydb_damage/<code>.json,
with an actual damage table -- not a {"notFound": true} placeholder) but
are missing pressure and/or wind/rain observation data.

Run this after widening data/tydb_damage/ coverage (e.g. via
`fetch_tydb_damage.py --all`) to find out which newly-discovered
damage storms still need:
  - data/pressure/<code>.json (JRA-3Q sea-level pressure grid)
  - data/storms_obs/<code>_wind.json / _rain.json (AMeDAS network readings)

so those codes can be fed straight into the existing builders:
  python3 scripts/fetch_amedas_obsdl.py --codes $(python3 scripts/list_damage_gaps.py --kind obs)
  python3 scripts/download_jra3q_pressure.py   # (month-based, not --codes; see its --dry-run)
  python3 scripts/build_pressure_json.py --raw-dir ... --codes $(python3 scripts/list_damage_gaps.py --kind pressure)

"Missing wind/rain" here means no usable value anywhere in the network
file (matching the frontend's dataHasAnyValue()/currentObsSource()
fallback logic) -- a storm whose AMeDAS network genuinely has no
digitized readings for that category (e.g. wind before ~1961) will
still show up here even though there is nothing to fetch; that's a
real historical gap, not a fetch failure.

Usage:
  python3 scripts/list_damage_gaps.py                 # human-readable report
  python3 scripts/list_damage_gaps.py --kind pressure  # comma-separated codes only
  python3 scripts/list_damage_gaps.py --kind wind
  python3 scripts/list_damage_gaps.py --kind rain
  python3 scripts/list_damage_gaps.py --kind obs       # wind or rain missing (union)
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def row_has_nonzero(row):
    return any((row.get(k) or 0) != 0 for k in row if k not in ("pref", "source"))


def has_real_damage_table(code):
    # A storm can have a TYDB page and a "被害の状況" table that TYDB itself
    # fills in as all-zeros (dead_missing/injured/destroyed/... every field
    # 0) -- that page exists, but there is no actual damage to report, so
    # it must not count as a "damage storm" here. ~400 of the 855 storms
    # found by `fetch_tydb_damage.py --all` are exactly this case.
    p = ROOT / "data" / "tydb_damage" / f"{code}.json"
    if not p.exists():
        return False
    d = json.loads(p.read_text(encoding="utf-8"))
    total = d.get("total")
    if total and row_has_nonzero(total):
        return True
    return any(row_has_nonzero(row) for row in (d.get("prefectures") or []))


def has_any_value(path):
    if not path.exists():
        return None  # file doesn't exist at all
    d = json.loads(path.read_text(encoding="utf-8"))
    for station in d.get("values") or []:
        if not station:
            continue
        for v in station:
            if v is not None:
                return True
    return False


def has_legacy(code, key):
    p = ROOT / "data" / "storms" / f"{code}.json"
    if not p.exists():
        return False
    d = json.loads(p.read_text(encoding="utf-8"))
    arr = d.get(key)
    if not arr:
        return False
    for row in arr:
        if row is None:
            continue
        if isinstance(row, list):
            if any(v is not None for v in row):
                return True
        elif row is not None:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["pressure", "wind", "rain", "obs"],
                     help="print only comma-separated codes for this gap (for piping into --codes)")
    args = ap.parse_args()

    damage_dir = ROOT / "data" / "tydb_damage"
    codes = sorted(p.stem for p in damage_dir.glob("*.json") if has_real_damage_table(p.stem))

    missing_pressure, missing_wind, missing_rain = [], [], []
    for code in codes:
        if not (ROOT / "data" / "pressure" / f"{code}.json").exists():
            missing_pressure.append(code)

        wnet = has_any_value(ROOT / "data" / "storms_obs" / f"{code}_wind.json")
        if not (wnet or (wnet is not True and has_legacy(code, "wind"))):
            missing_wind.append(code)

        rnet = has_any_value(ROOT / "data" / "storms_obs" / f"{code}_rain.json")
        if not (rnet or (rnet is not True and has_legacy(code, "rain"))):
            missing_rain.append(code)

    if args.kind == "pressure":
        print(",".join(missing_pressure))
        return
    if args.kind == "wind":
        print(",".join(missing_wind))
        return
    if args.kind == "rain":
        print(",".join(missing_rain))
        return
    if args.kind == "obs":
        print(",".join(sorted(set(missing_wind) | set(missing_rain))))
        return

    print(f"{len(codes)} storms with real TYDB damage data")
    print(f"missing pressure: {len(missing_pressure)}: {', '.join(missing_pressure)}")
    print(f"missing wind:     {len(missing_wind)}: {', '.join(missing_wind)}")
    print(f"missing rain:     {len(missing_rain)}: {', '.join(missing_rain)}")


if __name__ == "__main__":
    main()
