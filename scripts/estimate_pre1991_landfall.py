#!/usr/bin/env python3
"""JMA's best-track text only carries the "passed within 1h of landfall in
Japan" marker (column 72, '#') from 1991 onward -- storms before that have
the column present but always blank, so scripts/build_all_storms.py's
landfallJP comes out False for every single pre-1991 storm regardless of
whether it actually hit Japan.

This backfills landfallJP for those storms with a geometric estimate: a
storm's track is considered to have passed near Japan if any track point
comes within STATION_RADIUS_KM of any station in data/stations_network.json
(the network's ~2600 stations blanket the whole Japanese archipelago, so
"close to some station" is a reasonable proxy for "over or near Japan"
without needing a separate coastline/polygon dataset).

Storms from 1991 onward are left untouched -- they already have the
authoritative flag from the source data. Each backfilled storm also gets
landfallJPMethod:"estimated" (vs "official") in data/index.json so this
approximation stays visible/traceable rather than silently posing as the
real thing.

Usage: python3 scripts/estimate_pre1991_landfall.py
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
NETWORK_PATH = ROOT / "data" / "stations_network.json"

STATION_RADIUS_KM = 10  # calibrated so the pre-1991 backfill rate (storms/year)
# matches the official 1991-2025 landfallJP rate (~3.9/year); see the commit
# message / PR discussion for the calibration sweep (5/10/15/20/25/30/50/75/
# 100/150km all tested against that target).
EARTH_R_KM = 6371.0


def haversine_min_km(track_lat, track_lon, station_lat, station_lon):
    """Min distance (km) from any track point to any station, vectorized."""
    lat1 = np.radians(track_lat)[:, None]
    lon1 = np.radians(track_lon)[:, None]
    lat2 = np.radians(station_lat)[None, :]
    lon2 = np.radians(station_lon)[None, :]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    d = 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return float(d.min())


def main():
    network = json.loads(NETWORK_PATH.read_text(encoding="utf-8"))
    # Union of wind+rain station coords is a denser, more complete map of Japan
    # than either alone.
    stations = network["wind"] + network["rain"]
    st_lat = np.array([s["lat"] for s in stations])
    st_lon = np.array([s["lon"] for s in stations])

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    updated = 0
    now_true = 0
    for code, meta in index.items():
        if int(meta["year"]) >= 1991:
            meta["landfallJPMethod"] = "official"
            continue
        path = STORMS_DIR / f"{code}.json"
        storm = json.loads(path.read_text(encoding="utf-8"))
        track = storm["track"]
        if not track:
            continue
        t_lat = np.array([p["lat"] for p in track])
        t_lon = np.array([p["lon"] for p in track])
        near = haversine_min_km(t_lat, t_lon, st_lat, st_lon) <= STATION_RADIUS_KM

        storm["landfallJP"] = near
        path.write_text(json.dumps(storm, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        meta["landfallJP"] = near
        meta["landfallJPMethod"] = "estimated"
        updated += 1
        if near:
            now_true += 1

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"backfilled {updated} pre-1991 storms, {now_true} now flagged landfallJP=true")


if __name__ == "__main__":
    main()
