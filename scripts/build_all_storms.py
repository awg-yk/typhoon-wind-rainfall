#!/usr/bin/env python3
"""Parse the full JMA best-track text (bst_all.txt, 1951-) into one JSON file
per storm under data/storms/, and rebuild data/index.json with a metadata
row for every storm in the best track (not just the ones with wind/rain
observation data).

Existing storms that already have wind/rain payloads (data/storms/<code>.json
with "wind"/"rain"/"times" keys) are left untouched aside from re-syncing
their "track" and "name" from the best track text, so no observation data is
lost.

Usage: python3 scripts/build_all_storms.py /path/to/bst_all.txt
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"

GRADE_RANK = ['5', '4', '3', '6', '2', '9', '7', '1', '8']


def jma_year(yy):
    return 2000 + yy if yy <= 50 else 1900 + yy


def parse_best_track(text):
    storms = []
    cur = None
    for raw in text.splitlines():
        if len(raw) < 5:
            continue
        if raw.startswith('66666'):
            if cur and len(cur['track']) >= 1:
                storms.append(cur)
            id_str = raw[6:10].strip()
            if not id_str:
                cur = None
                continue
            name = raw[30:50].strip()
            yy = int(id_str[:2])
            cur = {'code': id_str, 'name': name, 'year': str(jma_year(yy)), 'track': [], 'landfallJP': False}
            continue
        if cur is None or len(raw) < 36:
            continue
        time_str = raw[0:8].strip()
        lat_raw = raw[15:18].strip()
        lon_raw = raw[19:23].strip()
        if len(time_str) != 8 or not lat_raw or not lon_raw:
            continue
        grade_code = raw[13:14].strip()
        pres_raw = raw[24:28].strip()
        landfall_ch = raw[71] if len(raw) > 71 else ''

        yy2 = int(time_str[0:2])
        mm, dd, hh = time_str[2:4], time_str[4:6], time_str[6:8]
        dt = f"{jma_year(yy2)}-{mm}-{dd}T{hh}:00:00"

        lat = int(lat_raw) / 10
        lon = int(lon_raw) / 10
        pres = int(pres_raw) if pres_raw else None

        cur['track'].append({'time': dt, 'lat': lat, 'lon': lon, 'pres': pres, 'grade': grade_code})
        if landfall_ch == '#':
            cur['landfallJP'] = True
    if cur and len(cur['track']) >= 1:
        storms.append(cur)
    return storms


def main():
    if len(sys.argv) != 2:
        print("usage: build_all_storms.py <path to bst_all.txt>", file=sys.stderr)
        sys.exit(1)
    text = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace')
    storms = parse_best_track(text)

    STORMS_DIR.mkdir(parents=True, exist_ok=True)
    index = {}
    for s in storms:
        code = s['code']
        path = STORMS_DIR / f"{code}.json"
        grades = [t['grade'] for t in s['track'] if t['grade']]
        best = next((g for g in GRADE_RANK if g in grades), (grades[0] if grades else None))
        months = sorted({int(t['time'][5:7]) for t in s['track']})

        if path.exists():
            existing = json.loads(path.read_text(encoding='utf-8'))
            existing['name'] = s['name'] or existing.get('name', '')
            existing['year'] = s['year']
            existing['track'] = s['track']
            existing['landfallJP'] = s['landfallJP']
            path.write_text(json.dumps(existing, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            has_obs = 'wind' in existing and 'rain' in existing
        else:
            payload = {'name': s['name'], 'year': s['year'], 'track': s['track'], 'landfallJP': s['landfallJP']}
            path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            has_obs = False

        index[code] = {
            'name': s['name'],
            'year': s['year'],
            'maxGrade': best,
            'months': months,
            'landfallJP': s['landfallJP'],
            'hasObs': has_obs,
        }

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"wrote {len(storms)} storms ({sum(1 for v in index.values() if v['hasObs'])} with obs data)")


if __name__ == '__main__':
    main()
