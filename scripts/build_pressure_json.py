#!/usr/bin/env python3
"""Slice the JRA-3Q monthly Japan-area pressure files (from
scripts/download_jra3q_pressure.py / notebooks/jra3q_colab_download.ipynb)
into one compact JSON per landfallJP (or 'damaging', see
data/damage_storm_codes.json) storm, matching that storm's track period,
for the frontend to load on demand as a new "気圧配置" display mode.

Run this locally where the 185 downloaded .nc files are (they're too big to
ship through this session) -- point --raw-dir at that folder.

Input: monthly files named like
  jra3q.anl_surf.0_3_1.prmsl-msl-an-gauss.<YYYYMM>0100_<YYYYMM><lastday>18.japan.nc
(the <YYYYMM> is pulled out of the filename directly, so exact spelling of
the rest doesn't matter -- tolerant of e.g. hyphens being stripped by a
file-transfer tool).

Output: data/pressure/<code>.json, one per landfallJP storm:
  {"lat": [...], "lon": [...], "times": [...JST ISO strings...],
   "values": [[[hPa int, ...] per lon] per lat] per time]}
Grid is downsampled by --stride (default 2) and values rounded to whole hPa
to keep file size down -- isobar contours don't need full resolution.

Usage:
  python3 scripts/build_pressure_json.py --raw-dir /path/to/185/files
  python3 scripts/build_pressure_json.py --raw-dir ... --codes 1919,1915
  python3 scripts/build_pressure_json.py --raw-dir ... --stride 1  # full res
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
DEFAULT_OUT_DIR = ROOT / "data" / "pressure"

MONTH_RE = re.compile(r"(\d{10})_(\d{10})")
VAR_KEY = "prmsl-msl-an-gauss"


def index_raw_files(raw_dir):
    """yyyymm (str) -> Path, for every monthly file found in raw_dir."""
    by_month = {}
    for p in sorted(raw_dir.glob("*.nc")):
        m = MONTH_RE.search(p.name)
        if not m:
            continue
        by_month[m.group(1)[:6]] = p
    return by_month


def storm_months_jst(track):
    start = datetime.fromisoformat(track[0]["time"]) + timedelta(hours=9)
    end = datetime.fromisoformat(track[-1]["time"]) + timedelta(hours=9)
    months = []
    y, mo = start.year, start.month
    while (y, mo) <= (end.year, end.month):
        months.append(f"{y:04d}{mo:02d}")
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return months, start, end


def build_one(code, by_month, out_dir, stride, ds_cache):
    import numpy as np
    import xarray as xr

    storm = json.loads((STORMS_DIR / f"{code}.json").read_text(encoding="utf-8"))
    track = storm.get("track", [])
    if not track:
        return None, "no track"

    months, start, end = storm_months_jst(track)
    missing = [m for m in months if m not in by_month]
    if missing:
        return None, f"missing raw file(s) for {', '.join(missing)}"

    pieces = []
    for ym in months:
        path = by_month[ym]
        if path not in ds_cache:
            ds_cache[path] = xr.open_dataset(path)
        ds = ds_cache[path]
        # Dataset times are UTC-labeled instants (JMA convention); shift +9h
        # to JST so this matches data/storms/<code>.json's "times" convention.
        jst_times = ds["time"].values.astype("datetime64[s]").astype(datetime)
        jst_times = np.array([t + timedelta(hours=9) for t in jst_times])
        mask = (jst_times >= start) & (jst_times <= end)
        if not mask.any():
            continue
        pieces.append(ds[VAR_KEY].isel(time=np.where(mask)[0]).assign_coords(
            time=jst_times[mask]))

    if not pieces:
        return None, "no overlapping time steps found"

    combined = xr.concat(pieces, dim="time") if len(pieces) > 1 else pieces[0]
    combined = combined.sortby("time")
    combined = combined.isel(lat=slice(None, None, stride), lon=slice(None, None, stride))

    lat = [round(float(v), 3) for v in combined["lat"].values]
    lon = [round(float(v), 3) for v in combined["lon"].values]
    times = [t.strftime("%Y-%m-%dT%H:00:00") for t in combined["time"].values.astype("datetime64[s]").astype(datetime)]
    hpa = np.round(combined.values / 100.0).astype(int)  # Pa -> whole hPa
    values = hpa.tolist()

    out_path = out_dir / f"{code}.json"
    out_path.write_text(json.dumps({"lat": lat, "lon": lon, "times": times, "values": values},
                                    separators=(",", ":")), encoding="utf-8")
    return out_path, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, help="folder containing the 185 downloaded .nc files")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--stride", type=int, default=2,
                     help="keep every Nth grid point in lat/lon (default 2, i.e. half resolution)")
    ap.add_argument("--codes", help="comma-separated storm codes to build "
                     "(default: all landfallJP storms, plus any storm flagged 'damaging' -- "
                     "see data/damage_storm_codes.json)")
    args = ap.parse_args()

    try:
        import xarray  # noqa: F401
    except ImportError:
        sys.exit("xarray is required: pip install xarray netCDF4")

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_month = index_raw_files(raw_dir)
    print(f"found {len(by_month)} monthly files in {raw_dir}")

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        codes = [c for c, m in index.items() if m.get("landfallJP") or m.get("damaging")]

    ds_cache = {}
    ok, failed = 0, []
    for i, code in enumerate(codes, 1):
        out_path, err = build_one(code, by_month, out_dir, args.stride, ds_cache)
        if out_path:
            size_kb = out_path.stat().st_size / 1024
            print(f"[{i}/{len(codes)}] {code}: ok ({size_kb:.0f} KB)")
            ok += 1
        else:
            print(f"[{i}/{len(codes)}] {code}: FAILED ({err})")
            failed.append(code)
    for ds in ds_cache.values():
        ds.close()

    print()
    print(f"{ok}/{len(codes)} storms written to {out_dir}")
    if failed:
        print(f"{len(failed)} failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
