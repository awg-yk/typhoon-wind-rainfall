#!/usr/bin/env python3
"""Download JRA-3Q sea-level pressure (prmsl-msl-an-gauss, i.e. the field
used to draw a "pressure pattern" weather chart), cropped to a Japan-area
bounding box, for every month touched by a landfallJP storm's track.

Default method ("full"): download the whole-globe monthly file over plain
HTTPS from GDEX's static file server, crop it to the bounding box locally
with xarray, write the ~5MB result, and delete the ~84MB original. So ~15GB
crosses the wire for a full run but only ~900MB is ever kept, and peak disk
use is one full file at a time.

That is deliberately the dumbest possible approach, because every clever
one failed against this server:

  - NCSS (THREDDS NetCDF Subset Service), which crops server-side: worked
    for a handful of months, timed out for most even at a 120s timeout
    (~8% success across a full run). Retrying later did not help.
  - OPeNDAP (--method opendap, still available below), which reads byte
    ranges out of the stored file: measured a clean 13.5s / 4.8MB for one
    month in isolation, so it looked ideal. But 4 concurrent processes made
    nginx return "504 Gateway Time-out" for nearly everything; dropping to
    serial still 504'd; splitting each month into 5-day chunks still 504'd;
    and finally even the initial metadata open -- a tiny request whose size
    no amount of chunking affects -- began failing on every attempt. At that
    point the service simply was not usable from here.

The static file server, by contrast, never failed once in any of this: it
does no per-request computation, it just serves bytes. Hence trading
bandwidth for reliability.

Requires: pip install xarray netCDF4

Dataset is d640000 (historical, Sep 1947 onward) or d640001 (near-real-time,
from Dec 2023 onward). This script tries d640000 first for every month and
falls back to d640001 only for months d640001 can actually cover, since the
exact month where d640000's coverage currently ends isn't fixed (JRA-3Q
keeps extending it) but d640001's start date is fixed.

Which months are needed is computed straight from this repo's own data
(data/index.json's landfallJP storms + their data/storms/<code>.json track
date range), not a hardcoded list, so it stays correct as that data changes.

Usage:
  python3 scripts/download_jra3q_pressure.py                # sea-level pressure only
  python3 scripts/download_jra3q_pressure.py --include-surface-pressure
  python3 scripts/download_jra3q_pressure.py --north 55 --south 10 --west 110 --east 165
  python3 scripts/download_jra3q_pressure.py --workers 3    # parallel; the static server is fine with it
  python3 scripts/download_jra3q_pressure.py --method opendap   # only if OPeNDAP recovers
  python3 scripts/download_jra3q_pressure.py --dry-run      # just print the month list/count
"""
import argparse
import calendar
import concurrent.futures
import contextlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
OUT_DIR = ROOT / "data" / "raw_jra3q"

STATIC_BASE = "https://osdf-director.osg-htc.org/ncar/gdex/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
OPENDAP_BASE = "https://tds.gdex.ucar.edu/thredds/dodsC/files/g/{dataset}/anl_surf/{yyyymm}/jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.nc"
DATASETS = ["d640000", "d640001"]  # try historical first, then near-real-time
D640001_STARTS = (2023, 12)  # d640001 only covers Dec 2023 onward -- skip it
# entirely for earlier months instead of wasting a request that can only fail.
VARIABLES = [("0_3_1", "prmsl-msl")]  # sea-level pressure ("pressure pattern")
SURFACE_PRESSURE = ("0_3_0", "pres-sfc")

# Default bounding box: covers Japan and its approach paths.
DEFAULT_BBOX = {"north": 50, "south": 15, "west": 115, "east": 155}

WORKERS = 2      # The static file server handles concurrency fine (unlike the
# THREDDS services). Kept low anyway since each worker holds an ~84MB download
# plus an xarray crop in memory/disk. --workers > 1 uses PROCESSES, not
# threads: netCDF4/HDF5 isn't thread-safe and a threaded run deadlocked.
PASSES = 3       # whole-list retry passes for anything that failed
PASS_SLEEP_SEC = 15
RETRIES = 3      # attempts per month within one pass
RETRY_SLEEP_SEC = 5        # base for exponential backoff (5s, 10s, 20s, ...)
REQUEST_SPACING_SEC = 0.2
HTTP_TIMEOUT_SEC = 300     # generous: these are ~84MB files
DOWNLOAD_CHUNK_BYTES = 1 << 20

# --method opendap only: read each month in slices this many days long.
CHUNK_DAYS = 5
CHUNK_ATTEMPTS = 5
OPEN_ATTEMPTS = 5
CHUNK_SPACING_SEC = 0.3


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


def build_url(base, dataset, var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return base.format(dataset=dataset, yyyymm=yyyymm, var_code=var_code,
                        var_name=var_name, lastday=lastday)


def output_filename(var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return f"jra3q.anl_surf.{var_code}.{var_name}-an-gauss.{yyyymm}0100_{yyyymm}{lastday}18.japan.nc"


def summarize_error(e):
    """One-line, human-readable reason. The raw OSError from netCDF4 embeds
    the whole URL and the server's HTML error page, which is unreadable in a
    log; the actual cause is usually just the HTTP status."""
    text = str(e)
    for code, label in (("504", "server timeout (504)"),
                        ("503", "server unavailable (503)"),
                        ("502", "bad gateway (502)"),
                        ("500", "server error (500)"),
                        ("404", "not found (404)")):
        if code in text:
            return label
    return f"{type(e).__name__}: {text.replace(chr(10), ' ')[:100]}"


@contextlib.contextmanager
def quiet_stderr():
    """Silence the netCDF C library's direct-to-fd-2 chatter.

    On a DAP error it dumps the server's whole HTML error page plus a parser
    'syntax error, unexpected WORD_WORD' line straight to file descriptor 2,
    bypassing Python -- several unreadable lines per failure. The Python-level
    exception still carries the information we report.
    """
    saved_fd = os.dup(2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(devnull_fd)
        os.close(saved_fd)


def with_retries(fn, describe, attempts, base_sleep):
    """Call fn(), retrying with exponential backoff. Returns fn()'s value.

    Raises the last exception if every attempt fails."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            with quiet_stderr():
                return fn()
        except Exception as e:  # noqa: BLE001 - any failure here is retryable
            last = e
            if attempt < attempts:
                wait = base_sleep * (2 ** (attempt - 1))
                print(f"      {describe}: {summarize_error(e)} "
                      f"(attempt {attempt}/{attempts}, retrying in {wait}s)", flush=True)
                time.sleep(wait)
            else:
                print(f"      {describe}: {summarize_error(e)} "
                      f"(attempt {attempt}/{attempts}, giving up)", flush=True)
    raise last


def crop_to_bbox(ds, var_key, bbox):
    """Select var_key over bbox. JRA-3Q's lat axis runs north -> south, so the
    slice has to match that direction or .sel() silently returns nothing."""
    lat_vals = ds["lat"].values
    lat_slice = slice(bbox["north"], bbox["south"]) if lat_vals[0] > lat_vals[-1] \
        else slice(bbox["south"], bbox["north"])
    boxed = ds[[var_key]].sel(lat=lat_slice, lon=slice(bbox["west"], bbox["east"]))
    if boxed[var_key].sizes.get("lat", 0) == 0 or boxed[var_key].sizes.get("lon", 0) == 0:
        raise ValueError(f"empty selection for bbox {bbox}")
    return boxed


def download_file(url, dest):
    """Stream a URL to dest. Raises on HTTP error or empty body."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; typhoon-wind-rainfall/1.0)"})
    total = 0
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp, dest.open("wb") as f:
        while True:
            block = resp.read(DOWNLOAD_CHUNK_BYTES)
            if not block:
                break
            f.write(block)
            total += len(block)
    if total == 0:
        raise OSError("empty response body")
    return total


def fetch_via_full_download(url, var_key, bbox, out_path):
    """Download the whole-globe monthly file, crop locally, keep only the crop.

    Writes the crop to a temp path and renames on success, so an interrupted
    run can't leave a half-written file a later pass mistakes for a finished
    download. The ~84MB original is always removed, success or not.
    """
    import xarray as xr

    tmp_path = out_path.with_suffix(".tmp.nc")
    full_path = out_path.with_suffix(".full.tmp.nc")
    try:
        download_file(url, full_path)
        ds = xr.open_dataset(full_path)
        try:
            crop_to_bbox(ds, var_key, bbox).load().to_netcdf(tmp_path)
        finally:
            ds.close()
        tmp_path.replace(out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        full_path.unlink(missing_ok=True)


def fetch_via_opendap(url, var_key, bbox, out_path, chunk_days):
    """Read only the bbox over OPeNDAP, in chunk_days slices along time.

    Kept as an option in case the THREDDS service recovers; see the module
    docstring for why it is not the default.
    """
    import xarray as xr

    tmp_path = out_path.with_suffix(".tmp.nc")
    ds = None
    try:
        ds = with_retries(lambda: xr.open_dataset(url), "open", OPEN_ATTEMPTS, RETRY_SLEEP_SEC)
        boxed = crop_to_bbox(ds, var_key, bbox)
        n_times = boxed.sizes["time"]
        steps_per_chunk = max(1, chunk_days * 4)  # JRA-3Q is 6-hourly
        pieces = []
        for start in range(0, n_times, steps_per_chunk):
            stop = min(start + steps_per_chunk, n_times)
            piece = with_retries(
                lambda s=start, e=stop: boxed.isel(time=slice(s, e)).load(),
                f"times {start}-{stop - 1}/{n_times}",
                CHUNK_ATTEMPTS, RETRY_SLEEP_SEC)
            pieces.append(piece)
            time.sleep(CHUNK_SPACING_SEC)
        combined = xr.concat(pieces, dim="time") if len(pieces) > 1 else pieces[0]
        combined.to_netcdf(tmp_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        if ds is not None:
            ds.close()
    tmp_path.replace(out_path)


def try_month(dataset, var_code, var_name, y, m, bbox, out_path, method, chunk_days):
    var_key = f"{var_name}-an-gauss"
    if method == "opendap":
        url = build_url(OPENDAP_BASE, dataset, var_code, var_name, y, m)
        fn = lambda: fetch_via_opendap(url, var_key, bbox, out_path, chunk_days)  # noqa: E731
    else:
        url = build_url(STATIC_BASE, dataset, var_code, var_name, y, m)
        fn = lambda: fetch_via_full_download(url, var_key, bbox, out_path)  # noqa: E731

    for attempt in range(1, RETRIES + 1):
        try:
            with quiet_stderr():
                fn()
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False  # not in this dataset -- caller tries the next one
            print(f"    {y:04d}-{m:02d} {dataset}: {summarize_error(e)} "
                  f"(attempt {attempt}/{RETRIES})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"    {y:04d}-{m:02d} {dataset}: {summarize_error(e)} "
                  f"(attempt {attempt}/{RETRIES})", flush=True)
        if attempt < RETRIES:
            time.sleep(RETRY_SLEEP_SEC * (2 ** (attempt - 1)))
    return False


def fetch_job(job):
    """Worker entry point: fetch one (month, variable).

    Module-level (not a closure) so it can be pickled for ProcessPoolExecutor,
    and takes its config in the job tuple for the same reason.
    """
    y, m, var_code, var_name, out_dir_str, bbox, method, chunk_days = job
    out_dir = Path(out_dir_str)
    out_path = out_dir / output_filename(var_code, var_name, y, m)
    if out_path.exists() and out_path.stat().st_size > 0:
        return job, True
    for dataset in DATASETS:
        if dataset == "d640001" and (y, m) < D640001_STARTS:
            continue
        if try_month(dataset, var_code, var_name, y, m, bbox, out_path, method, chunk_days):
            return job, True
    return job, False


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
    ap.add_argument("--method", choices=("full", "opendap"), default="full",
                     help="'full' (default) downloads the whole-globe file and crops it locally -- "
                          "more bandwidth but the static server is reliable. 'opendap' crops "
                          "server-side, which is far less traffic but has been failing.")
    ap.add_argument("--chunk-days", type=int, default=CHUNK_DAYS,
                     help=f"--method opendap only: days of data per request (default {CHUNK_DAYS})")
    ap.add_argument("--workers", type=int, default=WORKERS,
                     help=f"concurrent months, as processes (default {WORKERS})")
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
    print(f"method: {args.method}, bbox: {bbox}")
    print(f"saving to: {out_dir}")
    if args.method == "full":
        print(f"note: downloads ~84MB per month and keeps only the ~5MB crop "
              f"(~{total_files * 84 / 1024:.0f}GB transferred, ~{total_files * 5 / 1024:.1f}GB kept)")
    if args.dry_run:
        for y, m in months:
            print(f"  {y:04d}-{m:02d}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear temp files left behind by an interrupted earlier run, so they
    # can't end up in a zip of the output directory looking like results.
    for stale in out_dir.glob("*.tmp.nc"):
        stale.unlink()

    pending = [(y, m, var_code, var_name, str(out_dir), bbox, args.method, args.chunk_days)
               for (y, m) in months
               for var_code, var_name in variables]

    started = time.time()
    for pass_no in range(1, args.passes + 1):
        if not pending:
            break
        if pass_no > 1:
            print(f"\n--- pass {pass_no}/{args.passes}: retrying {len(pending)} failed "
                  f"(waiting {PASS_SLEEP_SEC}s first) ---", flush=True)
            time.sleep(PASS_SLEEP_SEC)
        else:
            print(f"\n--- pass {pass_no}/{args.passes}: {len(pending)} files, "
                  f"{args.workers} at a time ---", flush=True)

        still_failed = []
        done_in_pass = 0
        total_in_pass = len(pending)

        def report(job, ok):
            nonlocal done_in_pass
            y, m, _vc, var_name = job[:4]
            done_in_pass += 1
            elapsed = time.time() - started
            eta = (elapsed / done_in_pass) * (total_in_pass - done_in_pass) / 60
            status = "ok" if ok else "failed"
            print(f"[{done_in_pass}/{total_in_pass}] {y:04d}-{m:02d} {var_name}: {status} "
                  f"({elapsed/60:.1f} min elapsed, ~{eta:.0f} min left)", flush=True)
            if not ok:
                still_failed.append(job)

        if args.workers <= 1:
            for job in pending:
                job, ok = fetch_job(job)
                report(job, ok)
                time.sleep(REQUEST_SPACING_SEC)
        else:
            # Processes, not threads: netCDF4/HDF5 is not thread-safe and a
            # threaded run deadlocked (workers each created a tiny temp file
            # and then hung indefinitely).
            with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
                for job, ok in pool.map(fetch_job, pending):
                    report(job, ok)
        pending = still_failed

    print()
    if pending:
        print(f"{len(pending)} failed after {args.passes} pass(es):")
        for job in pending:
            y, m, _vc, var_name = job[:4]
            print(f"  {y:04d}-{m:02d} {var_name}")
        print("Re-run the same command to retry just these (files already downloaded are skipped).")
    else:
        print(f"All files downloaded in {(time.time()-started)/60:.1f} min.")


if __name__ == "__main__":
    main()
