#!/usr/bin/env python3
"""Download JRA-3Q sea-level pressure (prmsl-msl-an-gauss, i.e. the field
used to draw a "pressure pattern" weather chart), cropped to a Japan-area
bounding box, for every month touched by a landfallJP storm's track.

Two ways to get a cropped file are tried, per month, in order:

1. NCSS (NetCDF Subset Service): GDEX (NCAR/UCAR) serves JRA-3Q through a
   THREDDS server that can crop a request to a lat/lon box server-side.
   Confirmed against a real request: the default box below (lat 15-50N, lon
   115-155E) shrinks a monthly file from ~84MB (full globe) to ~5MB (Japan
   area only). When it works this is much less bandwidth, but in practice
   it has turned out unreliable for less-recently-accessed months: some
   return the correct data immediately, some return HTTP 200 with an EMPTY
   body (see the "files/g/" note below), and some just time out (probably
   the server generating the subset on demand and taking a while, or being
   generated and then failing). NCSS is given a short timeout and few
   retries so a bad month fails fast instead of stalling the whole run.

   Endpoint (one per month, same file the plain download link points at,
   just with query params added):
     https://tds.gdex.ucar.edu/thredds/ncss/grid/files/g/<dataset>/anl_surf/<YYYYMM>/
       jra3q.anl_surf.<var_code>.<var_name>-an-gauss.<YYYYMM>0100_<YYYYMM><lastday>18.nc
       ?var=<var_name>-an-gauss&north=..&south=..&east=..&west=..
       &time_start=..&time_end=..&accept=netcdf3

   IMPORTANT: the "files/g/<dataset>/..." path segment is not optional --
   an otherwise-identical URL without "g/" (files/<dataset>/...) also
   resolves and looks fine for some months (presumably some kind of alias)
   but silently returns HTTP 200 with an EMPTY body for others, with no
   error to signal it. Confirmed month-by-month: 1951-12 succeeded without
   "g/", but 1951-06 came back empty without it and only worked once "g/"
   was added. Always use the "g/" path.

2. Full-globe download + local crop: when NCSS fails or times out, this
   falls back to downloading the whole-globe file from the plain static
   HTTPServer link (which has been reliable throughout, just ~84MB instead
   of ~5MB) and crops it locally with xarray before saving, then discards
   the full-size temp file. Needs `pip install xarray netCDF4`.

where <dataset> is d640000 (historical, Sep 1947 onward) or d640001
(near-real-time, from Dec 2023 onward). This script tries d640000 first for
every month and falls back to d640001 only for months d640001 can actually
cover, since the exact month where d640000's coverage currently ends isn't
fixed (JRA-3Q keeps extending it) but d640001's start date is fixed.

Which months are needed is computed straight from this repo's own data
(data/index.json's landfallJP storms + their data/storms/<code>.json track
date range), not a hardcoded list, so it stays correct as that data changes.

Usage:
  python3 scripts/download_jra3q_pressure.py                # sea-level pressure only
  python3 scripts/download_jra3q_pressure.py --include-surface-pressure
  python3 scripts/download_jra3q_pressure.py --north 55 --south 10 --west 110 --east 165
  python3 scripts/download_jra3q_pressure.py --no-ncss       # skip straight to full+crop
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

NCSS_BASE = "https://tds.gdex.ucar.edu/thredds/ncss/grid/files/g/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
STATIC_BASE = "https://osdf-director.osg-htc.org/ncar/gdex/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
DATASETS = ["d640000", "d640001"]  # try historical first, then near-real-time
D640001_STARTS = (2023, 12)  # d640001 only covers Dec 2023 onward -- skip it
# entirely for earlier months instead of wasting retries on a request that
# can only ever come back empty.
VARIABLES = [("0_3_1", "prmsl-msl")]  # sea-level pressure ("pressure pattern")
SURFACE_PRESSURE = ("0_3_0", "pres-sfc")

# Default bounding box: covers Japan and its approach paths. Verified with a
# real request (see module docstring) to shrink files ~94% vs. the full globe.
DEFAULT_BBOX = {"north": 50, "south": 15, "west": 115, "east": 155}

NCSS_TIMEOUT_SEC = 60
NCSS_RETRIES = 1  # a hung/slow month is unlikely to suddenly speed up on an
# immediate retry, and this script doesn't want to burn many minutes per bad
# month -- fail fast and move on, don't stall the whole run on one file.
FULL_TIMEOUT_SEC = 180
FULL_RETRIES = 3
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


def build_ncss_url(dataset, var_code, var_name, year, month, bbox):
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


def build_static_url(dataset, var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return STATIC_BASE.format(dataset=dataset, yyyymm=yyyymm, var_code=var_code,
                               var_name=var_name, lastday=lastday)


def output_filename(var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return f"jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.japan.nc"


def fetch(url, out_path, timeout, max_retries):
    # A plain urllib.request.urlopen() call (no User-Agent header -- urllib's
    # default is "Python-urllib/x.y") got silent 200-with-empty-body
    # responses from this server in practice, even though the exact same URL
    # worked fine through requests.get() (which sends a browser-like default
    # User-Agent). Sending one here avoids that. Also explicitly treat an
    # empty body as a failure instead of writing a 0-byte "successful" file.
    req_headers = {"User-Agent": "Mozilla/5.0 (compatible; typhoon-wind-rainfall/1.0)"}
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                print(f"    (empty response body, attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(RETRY_SLEEP_SEC)
                continue
            out_path.write_bytes(data)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False  # not in this dataset -- caller tries the next one
            print(f"    (HTTP {e.code}, attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                time.sleep(RETRY_SLEEP_SEC)
        except Exception as e:
            print(f"    ({type(e).__name__}: {e}, attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                time.sleep(RETRY_SLEEP_SEC)
    return False


def crop_netcdf(src_path, dst_path, var_key, bbox):
    """Crop a full-globe netCDF to bbox using xarray, saving only var_key."""
    import xarray as xr

    ds = xr.open_dataset(src_path)
    try:
        lat_vals = ds["lat"].values
        lat_slice = slice(bbox["north"], bbox["south"]) if lat_vals[0] > lat_vals[-1] \
            else slice(bbox["south"], bbox["north"])
        cropped = ds[[var_key]].sel(lat=lat_slice, lon=slice(bbox["west"], bbox["east"]))
        cropped.to_netcdf(dst_path)
    finally:
        ds.close()


def try_ncss(dataset, var_code, var_name, y, m, bbox, out_path):
    url = build_ncss_url(dataset, var_code, var_name, y, m, bbox)
    return fetch(url, out_path, NCSS_TIMEOUT_SEC, NCSS_RETRIES)


def try_full_and_crop(dataset, var_code, var_name, y, m, bbox, out_path):
    url = build_static_url(dataset, var_code, var_name, y, m)
    tmp_path = out_path.with_suffix(".full.tmp.nc")
    try:
        if not fetch(url, tmp_path, FULL_TIMEOUT_SEC, FULL_RETRIES):
            return False
        try:
            crop_netcdf(tmp_path, out_path, f"{var_name}-an-gauss", bbox)
        except ImportError:
            print("    xarray is required for the full-file fallback: pip install xarray netCDF4")
            return False
        except Exception as e:
            print(f"    (crop failed: {type(e).__name__}: {e})")
            return False
        return True
    finally:
        tmp_path.unlink(missing_ok=True)


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
    ap.add_argument("--allow-full-fallback", action="store_true",
                     help="if NCSS fails for a month, fall back to downloading the whole-globe file "
                          "(~84MB vs ~5MB) and cropping it locally. Off by default since a run with "
                          "many failing months would spend a lot of time on full-size downloads; "
                          "failed months are just reported instead so you can decide.")
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
            if out_path.exists() and out_path.stat().st_size > 0:
                ok = True
            else:
                ok = False
                for dataset in DATASETS:
                    if dataset == "d640001" and (y, m) < D640001_STARTS:
                        continue
                    if try_ncss(dataset, var_code, var_name, y, m, bbox, out_path):
                        ok = True
                        break
                    if args.allow_full_fallback and try_full_and_crop(dataset, var_code, var_name, y, m, bbox, out_path):
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
