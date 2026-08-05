#!/usr/bin/env python3
"""Convert raw obsdl CSVs from scripts/fetch_amedas_obsdl.py
(data/raw_amedas/<code>_wind.csv / <code>_rain.csv) into per-storm JSON
matching the shape the frontend already knows how to read for the legacy
156-station network, but keyed against the new expanded network in
data/stations_network.json.

CSV layout (obsdl "地点まとめ" hourly response), verified against a real
downloaded sample:
  row 0: "ダウンロードした時刻：..." (ignored)
  row 1: blank
  row 2: station name, repeated once per sub-column of that station's block
  row 3: element label (e.g. "風速(m/s)" / "降水量(mm)"), ignored (block width varies)
  row 4..N: one or two label rows identifying each sub-column's role
            (blank / "風向" / "品質情報" / "均質番号" / "現象なし情報")
  first data row: first row whose column 0 looks like a date ("2025/9/2 1:00:00")

Block width is NOT constant across stations (rain stations can have 3 or 4
sub-columns depending on whether "現象なし情報" is present), and two
different real stations can share the same displayed name (e.g. multiple
筑波山/白浜 entries), so columns are grouped by ROLE PATTERN rather than by
station name or a fixed stride: a column whose every label row is blank is
the start of a new station's block (its actual measurement value); this
gives exactly len(stations_network.json[kind]) groups, in request order,
which is how they line up 1:1 with that station list.

Usage:
  python3 scripts/convert_amedas_csv.py --codes 2515
  python3 scripts/convert_amedas_csv.py --all   # every data/raw_amedas/*_{wind,rain}.csv
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}:\d{2}$")

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
NETWORK_PATH = ROOT / "data" / "stations_network.json"
RAW_DIR = ROOT / "data" / "raw_amedas"
OUT_DIR = ROOT / "data" / "storms_obs"

# JMA 16-direction wind names -> degrees (direction the wind is blowing FROM)
DIR_TO_DEG = {
    "北": 0, "北北東": 22.5, "北東": 45, "東北東": 67.5,
    "東": 90, "東南東": 112.5, "南東": 135, "南南東": 157.5,
    "南": 180, "南南西": 202.5, "南西": 225, "西南西": 247.5,
    "西": 270, "西北西": 292.5, "北西": 315, "北北西": 337.5,
    "静穏": None,
}


def load_network():
    return json.loads(NETWORK_PATH.read_text(encoding="utf-8"))


def find_data_start(rows):
    for i, r in enumerate(rows):
        if r and DATE_RE.match(r[0]):
            return i
    raise ValueError("could not find a data row (expected a 'YYYY/M/D H:MM:SS' first column)")


def group_columns(rows, header_end):
    """Return [(start_col, end_col_exclusive), ...] -- one per station, in order,
    found by locating each column whose label rows are ALL blank (the
    station's primary measurement column) and running to just before the
    next one."""
    station_row = rows[2]
    label_rows = rows[4:header_end]
    n_cols = len(station_row)
    starts = [i for i in range(1, n_cols) if all(lr[i] == "" for lr in label_rows)]
    groups = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else n_cols
        groups.append((s, e))
    return groups


def col_role(rows, header_end, col):
    return tuple(rows[r][col] for r in range(4, header_end))


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def convert_wind(rows, header_end, groups, data_start):
    times, series = [], [[] for _ in groups]
    for row in rows[data_start:]:
        if not row or not row[0]:
            continue
        dt = datetime.strptime(row[0], "%Y/%m/%d %H:%M:%S")
        times.append(dt.strftime("%Y-%m-%dT%H:00:00"))
        for gi, (s, e) in enumerate(groups):
            speed, dir_deg = None, None
            for c in range(s, e):
                role = col_role(rows, header_end, c)
                if role == ("",) * len(role):
                    speed = to_float(row[c])
                elif role[0] == "風向" and all(v == "" for v in role[1:]):
                    dname = row[c].strip()
                    dir_deg = DIR_TO_DEG.get(dname)
            series[gi].append([speed, dir_deg] if speed is not None else None)
    return times, series


def convert_rain(rows, header_end, groups, data_start):
    times, series = [], [[] for _ in groups]
    for row in rows[data_start:]:
        if not row or not row[0]:
            continue
        dt = datetime.strptime(row[0], "%Y/%m/%d %H:%M:%S")
        times.append(dt.strftime("%Y-%m-%dT%H:00:00"))
        for gi, (s, e) in enumerate(groups):
            val = to_float(row[s])  # first column of the group is always the value
            series[gi].append(val)
    return times, series


def convert_one(code, kind, network):
    csv_path = RAW_DIR / f"{code}_{kind}.csv"
    if not csv_path.exists():
        return False
    rows = list(csv.reader(csv_path.open(encoding="utf-8-sig")))
    data_start = find_data_start(rows)
    header_end = data_start
    groups = group_columns(rows, header_end)

    stations = network[kind]
    if len(groups) != len(stations):
        print(f"  [WARN] {code} [{kind}]: {len(groups)} column-groups but "
              f"{len(stations)} stations in the network -- output would be "
              f"misaligned, skipping. (station list and CSV must come from "
              f"the same data/stations_network.json)", file=sys.stderr)
        return False

    if kind == "wind":
        times, series = convert_wind(rows, header_end, groups, data_start)
    else:
        times, series = convert_rain(rows, header_end, groups, data_start)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{code}_{kind}.json"
    out_path.write_text(json.dumps({"times": times, "values": series},
                                    ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    print(f"{code} [{kind}]: {len(stations)} stations x {len(times)} hours -> {out_path}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated storm codes, e.g. 1912,1915")
    ap.add_argument("--all", action="store_true", help="convert every CSV found in data/raw_amedas/")
    args = ap.parse_args()

    network = load_network()

    if args.all:
        codes = sorted({p.stem.rsplit("_", 1)[0] for p in RAW_DIR.glob("*_wind.csv")} |
                        {p.stem.rsplit("_", 1)[0] for p in RAW_DIR.glob("*_rain.csv")})
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        sys.exit("specify --codes or --all")

    for code in codes:
        for kind in ("wind", "rain"):
            convert_one(code, kind, network)


if __name__ == "__main__":
    main()
