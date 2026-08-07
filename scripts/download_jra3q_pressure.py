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

Built for reliability over speed, because GDEX's THREDDS backend has proved
fragile under any load:
  - Concurrency is off by default (--workers 1). Four parallel processes made
    nginx return "504 Gateway Time-out" for nearly every request. (Threads are
    worse still -- netCDF4/HDF5 isn't thread-safe and a threaded run deadlocked
    outright, which is why --workers > 1 uses processes, not threads.)
  - Each month is read in --chunk-days slices along the time axis rather than
    in one request. Asking for a whole month (~124 6-hourly steps) started
    returning 504s even serially, and even for a month that had downloaded
    fine in one request earlier; smaller requests come back inside the
    gateway timeout.
  - Every chunk is retried independently with exponential backoff, and the
    whole month list is retried over several passes, so transient server
    trouble costs a retry rather than the run.

A full 185-month run therefore takes on the order of an hour. That is the
intended trade.

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
  python3 scripts/download_jra3q_pressure.py --chunk-days 2  # even smaller requests
  python3 scripts/download_jra3q_pressure.py --workers 2    # only if GDEX can take it
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

WORKERS = 1      # SERIAL by default, deliberately. A single OPeNDAP read
# takes ~13.5s and works reliably, but 4 concurrent processes made the
# THREDDS backend fall over -- nginx returned "504 Gateway Time-out" for
# nearly every request. The server can't take the concurrency, so a full run
# is ~185 x 13.5s ~= 42 min and that's simply what it costs. (Threads are
# worse still: netCDF4/HDF5 isn't thread-safe and deadlocked outright, hence
# the process-pool machinery that remains for --workers > 1. Raise it only
# if GDEX's capacity changes.)
PASSES = 3       # whole-list retry passes for anything that failed
PASS_SLEEP_SEC = 15
RETRIES = 2      # month-level attempts within one pass
RETRY_SLEEP_SEC = 5        # base for exponential backoff (5s, 10s, 20s, ...)
REQUEST_SPACING_SEC = 0.5  # small gap between months, to stay polite

# Read each month in time-slices rather than in one request. A whole month is
# ~124 6-hourly steps, which is enough work that GDEX's backend regularly
# exceeds nginx's gateway timeout (504) -- even for a month that had
# previously downloaded fine in one go, once the server got busy. Smaller
# requests come back comfortably inside the timeout.
CHUNK_DAYS = 5             # ~20 time steps per request
CHUNK_ATTEMPTS = 5         # per chunk, with backoff -- be patient, not fast
OPEN_ATTEMPTS = 5          # for the initial metadata open
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


def build_opendap_url(dataset, var_code, var_name, year, month):
    yyyymm = f"{year:04d}{month:02d}"
    lastday = calendar.monthrange(year, month)[1]
    return OPENDAP_BASE.format(dataset=dataset, yyyymm=yyyymm, var_code=var_code,
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

    Raises the last exception if every attempt fails. `describe` is a short
    string used in the progress line so a slow month shows what it's stuck on.
    """
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


def fetch_subset(url, var_key, bbox, out_path, chunk_days=CHUNK_DAYS):
    """Open the remote file over OPeNDAP, read only the bbox, write locally.

    The read is split into chunks of `chunk_days` days along the time axis
    rather than pulling a whole month in one request. A full month (~124
    6-hourly steps) is enough work that GDEX's backend often exceeds nginx's
    gateway timeout and the request dies with a 504; smaller requests come
    back well inside it. Each chunk is retried independently with backoff, so
    one unlucky chunk doesn't cost the whole month's progress.

    Writes to a temp path first and renames on success, so an interrupted
    run can't leave a half-written file that a later pass would mistake for
    a completed download. The temp file is removed if anything fails.
    """
    import xarray as xr

    tmp_path = out_path.with_suffix(".tmp.nc")
    ds = None
    try:
        ds = with_retries(lambda: xr.open_dataset(url), "open", OPEN_ATTEMPTS, RETRY_SLEEP_SEC)
        lat_vals = ds["lat"].values
        # JRA-3Q's lat axis runs north -> south, so the slice has to match
        # that direction or .sel() silently returns an empty selection.
        lat_slice = slice(bbox["north"], bbox["south"]) if lat_vals[0] > lat_vals[-1] \
            else slice(bbox["south"], bbox["north"])
        boxed = ds[[var_key]].sel(lat=lat_slice, lon=slice(bbox["west"], bbox["east"]))
        if boxed[var_key].sizes.get("lat", 0) == 0 or boxed[var_key].sizes.get("lon", 0) == 0:
            raise ValueError(f"empty selection for bbox {bbox}")

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


def try_month(dataset, var_code, var_name, y, m, bbox, out_path, chunk_days):
    url = build_opendap_url(dataset, var_code, var_name, y, m)
    var_key = f"{var_name}-an-gauss"
    for attempt in range(1, RETRIES + 1):
        try:
            fetch_subset(url, var_key, bbox, out_path, chunk_days)
            return True
        except Exception as e:
            print(f"    {y:04d}-{m:02d} {dataset}: {summarize_error(e)} "
                  f"(attempt {attempt}/{RETRIES})", flush=True)
            if attempt < RETRIES:
                time.sleep(RETRY_SLEEP_SEC)
    return False


def fetch_job(job):
    """Worker entry point: fetch one (month, variable).

    Module-level (not a closure) so it can be pickled for ProcessPoolExecutor,
    and takes its config in the job tuple for the same reason.
    """
    y, m, var_code, var_name, out_dir_str, bbox, chunk_days = job
    out_dir = Path(out_dir_str)
    out_path = out_dir / output_filename(var_code, var_name, y, m)
    if out_path.exists() and out_path.stat().st_size > 0:
        return job, True
    for dataset in DATASETS:
        if dataset == "d640001" and (y, m) < D640001_STARTS:
            continue
        if try_month(dataset, var_code, var_name, y, m, bbox, out_path, chunk_days):
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
    ap.add_argument("--workers", type=int, default=WORKERS,
                     help=f"concurrent OPeNDAP reads (default {WORKERS})")
    ap.add_argument("--chunk-days", type=int, default=CHUNK_DAYS,
                     help=f"days of data per OPeNDAP request (default {CHUNK_DAYS}). Lower it if "
                          "the server keeps returning 504s; each request then asks for less work.")
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

    # Clear temp files left behind by an interrupted earlier run, so they
    # can't end up in a zip of the output directory looking like results.
    for stale in out_dir.glob("*.tmp.nc"):
        stale.unlink()

    pending = [(y, m, var_code, var_name, str(out_dir), bbox, args.chunk_days)
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
        # Processes, not threads: netCDF4/HDF5 is not thread-safe, and running
        # concurrent OPeNDAP reads in threads deadlocked in practice (workers
        # each created a ~48-byte temp file and then hung indefinitely). Each
        # process gets its own library state, so they don't contend.
        executor = (concurrent.futures.ProcessPoolExecutor if args.workers > 1
                    else None)
        if executor is None:
            for job in pending:
                job, ok = fetch_job(job)
                y, m, var_code, var_name = job[:4]
                done_in_pass += 1
                elapsed = time.time() - started
                rate = elapsed / done_in_pass
                eta = rate * (total_in_pass - done_in_pass) / 60
                status = "ok" if ok else "failed"
                print(f"[{done_in_pass}/{total_in_pass}] {y:04d}-{m:02d} {var_name}: {status} "
                      f"({elapsed/60:.1f} min elapsed, ~{eta:.0f} min left)", flush=True)
                if not ok:
                    still_failed.append(job)
                time.sleep(REQUEST_SPACING_SEC)
        else:
            with executor(max_workers=args.workers) as pool:
                for job, ok in pool.map(fetch_job, pending):
                    y, m, var_code, var_name = job[:4]
                    done_in_pass += 1
                    elapsed = time.time() - started
                    status = "ok" if ok else "failed"
                    print(f"[{done_in_pass}/{total_in_pass}] {y:04d}-{m:02d} {var_name}: {status} "
                          f"({elapsed/60:.1f} min elapsed)", flush=True)
                    if not ok:
                        still_failed.append(job)
        pending = still_failed

    print()
    if pending:
        print(f"{len(pending)} failed after {args.passes} pass(es):")
        for job in pending:
            y, m, _var_code, var_name = job[:4]
            print(f"  {y:04d}-{m:02d} {var_name}")
        print("Re-run the same command to retry just these (files already downloaded are skipped).")
    else:
        print(f"All files downloaded in {(time.time()-started)/60:.1f} min.")


if __name__ == "__main__":
    main()
