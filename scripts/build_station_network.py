#!/usr/bin/env python3
"""Convert data/raw/stations_wind.csv / stations_rain.csv (the expanded
気象台等+アメダス observation network, one row per station) into
data/stations_network.json: a compact {wind:[...], rain:[...]} station list
keyed by array index, with prec_no/block_no extracted from each row's JMA
URL so scripts/fetch_amedas.py can build the per-station download URL.

Usage: python3 scripts/build_station_network.py
"""
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "stations_network.json"


def load(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            url = r.get("気象庁ページURL", "")
            qs = parse_qs(urlparse(url).query)
            prec_no = qs.get("prec_no", [None])[0]
            block_no = qs.get("block_no", [None])[0]
            if not prec_no or not block_no:
                continue
            kind = r["種別"]
            rows.append({
                "id": r["観測所ID"],
                "name": r["地点名"],
                "kana": r.get("かな", ""),
                "pref": r.get("都道府県", ""),
                "lat": float(r["緯度"]),
                "lon": float(r["経度"]),
                "elev": r.get("標高(m)", ""),
                "kind": kind,  # 気象官署 / 気象台等 / アメダス
                # 官署(hourly_s1.php) has more elements than アメダス(hourly_a1.php);
                # 気象官署/気象台等 both use the s1 page.
                "page": "s1" if kind in ("気象官署", "気象台等") else "a1",
                "prec_no": prec_no,
                "block_no": block_no,
            })
    return rows


def main():
    network = {
        "wind": load(RAW / "stations_wind.csv"),
        "rain": load(RAW / "stations_rain.csv"),
    }
    OUT.write_text(json.dumps(network, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wind stations: {len(network['wind'])}, rain stations: {len(network['rain'])}")


if __name__ == "__main__":
    main()
