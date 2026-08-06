#!/usr/bin/env python3
"""Download JRA-3Q sea-level pressure (prmsl-msl-an-gauss, i.e. the field
used to draw a "pressure pattern" weather chart), cropped to a Japan-area
bounding box, for every month touched by a landfallJP storm's track.

Data comes from GDEX (NCAR/UCAR) over OPeNDAP: the monthly file is opened
remotely with xarray, only the requested lat/lon box is read over the wire,
and that subset is written locally. Measured ~13.5s and ~4.8MB for one
month at the default box (lat 15-50N, lon 115-155E), vs. ~84MB for the
whole-globe file.

Why OPeNDAP and not the THREDDS NetCDF Subset Service (NCSS): NCSS looks
like the natural fit (it crops server-side too) and works for some months,
but in practice it was unusable across a full run -- most months timed out
even at a 120s timeout, giving roughly an 8% success rate, and retrying
later did not help. OPeNDAP reads ranges out of the stored file instead of
materializing a subset server-side, and has been reliable.

Requires: pip install xarray netCDF4

Dataset is d640000 (historical, Sep 1947 onward) or d640001 (near-real-time,
from Dec 2023 onward). This script tries d640000 first for every month and
falls back to d640001 only for months d640001 can actually cover, since the
exact month where d640000's coverage currently ends isn't fixed (JRA-3Q
keeps extending it) but d640001's start date is fixed.

Note the "files/g/<dataset>/..." path segment: an otherwise-identical URL
without the "g/" also resolves for some months but misbehaves for others
(under NCSS it silently returned HTTP 200 with an empty body). Always use
the "g/" path.

Which months are needed is computed straight from this repo's own data
(data/index.json's landfallJP storms + their data/storms/<code>.json track
date range), not a hardcoded list, so it stays correct as that data changes.

Usage:
  python3 scripts/download_jra3q_pressure.py                # sea-level pressure only
  python3 scripts/download_jra3q_pressure.py --include-surface-pressure
  python3 scripts/download_jra3q_pressure.py --north 55 --south 10 --west 110 --east 165
  python3 scripts/download_jra3q_pressure.py --workers 6    # tune concurrency
  python3 scripts/download_jra3q_pressure.py --dry-run      # just print the month list/count
"""
import argparse
import calendar
import concurrent.futures
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
OUT_DIR = ROOT / "data" / "raw_jra3q"

OPENDAP_BASE = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
DATASETS = ["d640000", "d640001"]  # try historical first, then near-real-time
D640001_STARTS = (2023, 12)  # d640001 only covers Dec 2023 onward -- skip it
# entirely for earlier months instead of wasting a request that can only fail.
VARIABLES = [("0_3_1", "prmsl-msl")]  # sea-level pressure ("pressure pattern")
SURFACE_PRESSURE = ("0_3_0", "pres-sfc")

# Default bounding box: covers Japan and its approach paths.
DEFAULT_BBOX = {"north": 50, "south": 15, "west": 115, "east": 155}

WORKERS = 4      # concurrent OPeNDAP reads; modest to stay polite to GDEX
PASSES = 3       # whole-list retry passes for anything that failed
PASS_SLEEP_SEC = 15
RETRIES = 2      # attempts within one pass
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


def build_opendap_url(dataset, var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return OPENDAP_BASE.format(dataset=dataset, yyyymm=yyyymm, var_code=var_code,
                                var_name=var_name, lastday=lastday)


def output_filename(var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return f"jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.japan.nc"


def fetch_subset(url, var_key, bbox, out_path):
    """Open the remote file over OPeNDAP, read only the bbox, write locally.

    Writes to a temp path first and renames on success, so an interrupted
    run can't leave a half-written file that a later pass would mistake for
    a completed download.
    """
    import xarray as xr

    tmp_path = out_path.with_suffix(".tmp.nc")
    ds = None
    try:
        ds = xr.open_dataset(url)
        lat_vals = ds["lat"].values
        # JRA-3Q's lat axis runs north -> south, so the slice has to match
        # that direction or .sel() silently returns an empty selection.
        lat_slice = slice(bbox["north"], bbox["south"]) if lat_vals[0] > lat_vals[-1] \
            else slice(bbox["south"], bbox["north"])
        subset = ds[[var_key]].sel(lat=lat_slice, lon=slice(bbox["west"], bbox["east"]))
        if subset[var_key].size == 0:
            raise ValueError(f"empty selection for bbox {bbox}")
        subset.to_netcdf(tmp_path)
    finally:
        if ds is not None:
            ds.close()
    tmp_path.replace(out_path)


def try_month(dataset, var_code, var_name, y, m, bbox, out_path):
    url = build_opendap_url(dataset, var_code, var_name, y, m)
    var_key = f"{var_name}-an-gauss"
    for attempt in range(1, RETRIES + 1):
        try:
            fetch_subset(url, var_key, bbox, out_path)
            return True
        except Exception as e:
            msg = str(e).replace("\n", " ")[:160]
            print(f"    {y:04d}-{m:02d} {dataset}: {type(e).__name__}: {msg} "
                  f"(attempt {attempt}/{RETRIES})")
            if attempt < RETRIES:
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
    ap.add_argument("--workers", type=int, default=WORKERS,
                     help=f"concurrent OPeNDAP reads (default {WORKERS})")
    ap.add_argument("--passes", type=int, default=PASSES,
                     help=f"whole-list retry passes for failures (default {PASSES})")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    bbox = {"north": args.north, "south": args.south, "west": args.west, "east": args.east}

    try:
        import xarray  # noqa: F401
    except ImportError:
        sys.exit("xarray is required: pip install xarray netCDF4")

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

    def fetch_job(job):
        y, m, var_code, var_name = job
        out_path = out_dir / output_filename(var_code, var_name, y, m)
        if out_path.exists() and out_path.stat().st_size > 0:
            return job, True
        for dataset in DATASETS:
            if dataset == "d640001" and (y, m) < D640001_STARTS:
                continue
            if try_month(dataset, var_code, var_name, y, m, bbox, out_path):
                return job, True
        return job, False

    pending = [(y, m, var_code, var_name)
               for (y, m) in months
               for var_code, var_name in variables]

    started = time.time()
    for pass_no in range(1, args.passes + 1):
        if not pending:
            break
        if pass_no > 1:
            print(f"\n--- pass {pass_no}/{args.passes}: retrying {len(pending)} failed "
                  f"(waiting {PASS_SLEEP_SEC}s first) ---")
            time.sleep(PASS_SLEEP_SEC)
        else:
            print(f"\n--- pass {pass_no}/{args.passes}: {len(pending)} files, "
                  f"{args.workers} at a time ---")

        still_failed = []
        done_in_pass = 0
        total_in_pass = len(pending)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for job, ok in pool.map(fetch_job, pending):
                y, m, var_code, var_name = job
                done_in_pass += 1
                elapsed = time.time() - started
                status = "ok" if ok else "failed"
                print(f"[{done_in_pass}/{total_in_pass}] {y:04d}-{m:02d} {var_name}: {status} "
                      f"({elapsed/60:.1f} min elapsed)")
                if not ok:
                    still_failed.append(job)
        pending = still_failed

    print()
    if pending:
        print(f"{len(pending)} failed after {args.passes} pass(es):")
        for y, m, var_code, var_name in pending:
            print(f"  {y:04d}-{m:02d} {var_name}")
        print("Re-run the same command to retry just these (files already downloaded are skipped).")
    else:
        print(f"All files downloaded in {(time.time()-started)/60:.1f} min.")


if __name__ == "__main__":
    main()
