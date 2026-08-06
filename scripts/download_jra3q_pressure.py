#!/usr/bin/env python3
"""Download JRA-3Q sea-level pressure (prmsl-msl-an-gauss, i.e. the field
used to draw a "pressure pattern" weather chart), cropped to a Japan-area
bounding box, for every month touched by a landfallJP storm's track.

GDEX (NCAR/UCAR) serves JRA-3Q through a THREDDS server with a NetCDF
Subset Service (NCSS), which can crop a request to a lat/lon box server-side
instead of downloading the whole globe. Confirmed against a real request:
the default box below (lat 15-50N, lon 115-155E) shrinks a monthly file from
~84MB (full globe) to ~5MB (Japan area only) -- about 300MB total for all
185 months, vs. ~15GB for the whole-globe files this script downloaded
before switching to NCSS.

NCSS endpoint (one per month, same file this dataset's plain download link
points at, just with query params added):
  https://tds.gdex.ucar.edu/thredds/ncss/grid/files/<dataset>/anl_surf/<YYYYMM>/
    jra3q.anl_surf.<var_code>.<var_name>-an-gauss.<YYYYMM>0100_<YYYYMM><lastday>18.nc
    ?var=<var_name>-an-gauss&north=..&south=..&east=..&west=..
    &time_start=..&time_end=..&accept=netcdf3
where <dataset> is d640000 (historical, Sep 1947 onward) or d640001
(near-real-time, recent months). This script tries d640000 first for every
month and falls back to d640001 on a 404, since the exact month where
d640000's coverage currently ends isn't fixed (JRA-3Q keeps extending it).

Which months are needed is computed straight from this repo's own data
(data/index.json's landfallJP storms + their data/storms/<code>.json track
date range), not a hardcoded list, so it stays correct as that data changes.

Usage:
  python3 scripts/download_jra3q_pressure.py                # sea-level pressure only
  python3 scripts/download_jra3q_pressure.py --include-surface-pressure
  python3 scripts/download_jra3q_pressure.py --north 55 --south 10 --west 110 --east 165
  python3 scripts/download_jra3q_pressure.py --dry-run       # just print the month list/count
"""
import argparse
import calendar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
OUT_DIR = ROOT / "data" / "raw_jra3q"

NCSS_BASE = "https://tds.gdex.ucar.edu/thredds/ncss/grid/files/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
DATASETS = ["d640000", "d640001"]  # try historical first, then near-real-time
VARIABLES = [("0_3_1", "prmsl-msl")]  # sea-level pressure ("pressure pattern")
SURFACE_PRESSURE = ("0_3_0", "pres-sfc")

# Default bounding box: covers Japan and its approach paths. Verified with a
# real request (see module docstring) to shrink files ~94% vs. the full globe.
DEFAULT_BBOX = {"north": 50, "south": 15, "west": 115, "east": 155}

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 5


def needed_year_months():
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    codes = [c for c, m in index.items() if m.get("landfallJP")]
    months = set()
    for code in codes:
        path = STORMS_DIR / f"{code}.json"
        if not path.exists():
            continue
        storm = json.loads(path.read_text(encoding="utf-8"))
        track = storm.get("track", [])
        if not track:
            continue
        start = datetime.fromisoformat(track[0]["time"])
        end = datetime.fromisoformat(track[-1]["time"])
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.add((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return sorted(months)


def build_url(dataset, var_code, var_name, year, month, bbox):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    base = NCSS_BASE.format(dataset=dataset, yyyymm=yyyymm, var_code=var_code,
                             var_name=var_name, lastday=lastday)
    params = {
        "var": f"{var_name}-an-gauss",
        "north": bbox["north"], "south": bbox["south"],
        "west": bbox["west"], "east": bbox["east"],
        "horizStride": 1,
        "time_start": f"{year:04d}-{month:02d}-01T00:00:00Z",
        "time_end": f"{year:04d}-{month:02d}-{lastday:02d}T18:00:00Z",
        "timeStride": 1,
        "accept": "netcdf3",
    }
    return base + "?" + urllib.parse.urlencode(params)


def output_filename(var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return f"jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.japan.nc"


def download_one(url, out_path):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False  # not in this dataset -- caller tries the next one
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SEC)
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SEC)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-surface-pressure", action="store_true",
                     help="also download pres-sfc (surface pressure) alongside prmsl-msl (sea-level pressure)")
    ap.add_argument("--dry-run", action="store_true", help="print the month/file plan without downloading")
    ap.add_argument("--out-dir", default=str(OUT_DIR),
                     help="where to save downloaded files (e.g. a Colab-local or Drive path)")
    ap.add_argument("--north", type=float, default=DEFAULT_BBOX["north"])
    ap.add_argument("--south", type=float, default=DEFAULT_BBOX["south"])
    ap.add_argument("--west", type=float, default=DEFAULT_BBOX["west"])
    ap.add_argument("--east", type=float, default=DEFAULT_BBOX["east"])
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    bbox = {"north": args.north, "south": args.south, "west": args.west, "east": args.east}

    variables = list(VARIABLES)
    if args.include_surface_pressure:
        variables.append(SURFACE_PRESSURE)

    months = needed_year_months()
    total_files = len(months) * len(variables)
    print(f"{len(months)} months needed, {len(variables)} variable(s) -> {total_files} files")
    print(f"bbox: {bbox}")
    print(f"saving to: {out_dir}")
    if args.dry_run:
        for y, m in months:
            print(f"  {y:04d}-{m:02d}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    done = 0
    for y, m in months:
        for var_code, var_name in variables:
            out_path = out_dir / output_filename(var_code, var_name, y, m)
            if out_path.exists():
                ok = True
            else:
                ok = False
                for dataset in DATASETS:
                    url = build_url(dataset, var_code, var_name, y, m, bbox)
                    if download_one(url, out_path):
                        ok = True
                        break
            done += 1
            status = "ok" if ok else "FAILED (not found in any dataset)"
            print(f"[{done}/{total_files}] {y:04d}-{m:02d} {var_name}: {status}")
            if not ok:
                failed.append(f"{y:04d}-{m:02d} {var_name}")

    print()
    if failed:
        print(f"{len(failed)} failed:")
        for f in failed:
            print(f"  {f}")
        print("Re-run the same command to retry just these (files already downloaded are skipped).")
    else:
        print("All files downloaded.")


if __name__ == "__main__":
    main()
