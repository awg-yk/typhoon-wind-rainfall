#!/usr/bin/env python3
"""Bulk-download hourly AMeDAS/気象台等 wind and rain observations for storms
in data/storms/*.json, using the 気象庁「過去の気象データ・ダウンロード」(obsdl)
CSV API -- the same endpoint used by the working Colab notebook at
https://github.com/awg-yk/weather-station-finder/blob/main/notebooks/jma_bulk_download.ipynb
(request/response format, station batching, and volume-limit splitting logic
are ported from that notebook, which is known to work against the live API).

NOTE: this cannot be run inside the current sandboxed session -- outbound
access to www.data.jma.go.jp is blocked by this environment's network
policy (confirmed via the agent proxy status endpoint). Run it from a
machine with normal internet access instead:

    pip install requests
    python3 scripts/fetch_amedas_obsdl.py --landfall-only --kind wind,rain

This fetches per-storm CSVs into data/raw_amedas/<code>_<kind>.csv (raw
obsdl CSV format: header rows + one value/quality/homogeneity column-triplet
per station per element). Turning those CSVs into the per-storm wind/rain
JSON arrays the frontend consumes is a separate follow-up step once we can
inspect real output -- the exact column layout should be double-checked
against a small real response before writing that conversion, rather than
guessed here.

Requests are batched (many stations per request, using the JMA "1 request
<= ~44000 data points" volume limit) so a single storm needs on the order
of 10-20 requests rather than one per station per day.
"""
import argparse
import calendar
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parent.parent
STORMS_DIR = ROOT / "data" / "storms"
INDEX_PATH = ROOT / "data" / "index.json"
NETWORK_PATH = ROOT / "data" / "stations_network.json"
RAW_DIR = ROOT / "data" / "raw_amedas"

ROOT_URL = "https://www.data.jma.go.jp/risk/obsdl/index.php"
SHOW_URL = "https://www.data.jma.go.jp/risk/obsdl/show/table"

AGGRG_PERIOD_HOURLY = 9
ELEMENT_CODE = {"wind": "301", "rain": "101"}  # 風向・風速 / 降水量（前1時間）
MAX_RETRIES = 3
SLEEP_SEC = 3.0
VOLUME_LIMIT = 40000  # headroom under JMA's ~44000-datapoint-per-request limit


def station_num(prec_no: str, block_no: str) -> str:
    # obsdl station id prefix: 5-digit block_no (WMO 47xxx, 気象官署) -> "s"+block_no;
    # shorter (アメダス) -> "a"+block_no zero-padded to 4 digits. Not determined by the
    # 種別 label (e.g. some アメダス-labeled stations use 5-digit 47xxx codes too).
    return "s" + block_no if len(block_no) >= 5 else "a" + block_no.zfill(4)


@dataclass
class WeatherDataPayload:
    stationNumList: List[str] = field(default_factory=list)
    aggrgPeriod: int = AGGRG_PERIOD_HOURLY
    elementNumList: List[List[str]] = field(default_factory=list)
    interAnnualType: int = 1
    ymdList: List[str] = field(default_factory=list)  # [y1, y2, m1, m2, d1, d2]
    optionNumList: List[Any] = field(default_factory=list)
    downloadFlag: str = "true"
    rmkFlag: int = 1
    disconnectFlag: int = 1
    youbiFlag: int = 0
    fukenFlag: int = 0
    kijiFlag: int = 0
    huukouFlag: int = 0
    csvFlag: int = 1
    jikantaiFlag: int = 0
    jikantaiList: List[Any] = field(default_factory=list)
    ymdLiteral: int = 1

    def to_post_data(self) -> dict:
        return {k: (json.dumps(v) if isinstance(v, list) else v) for k, v in asdict(self).items()}


def count_periods_hourly(y1, y2, m1, m2, d1, d2) -> int:
    # aggrgPeriod=9 (hourly), interAnnualType=1 (continuous range): diff in days * 24.
    days = abs((date(y2, m2, min(d2, calendar.monthrange(y2, m2)[1])) -
                date(y1, m1, min(d1, calendar.monthrange(y1, m1)[1]))).days) + 1
    return days * 24


def looks_like_csv(content: bytes) -> bool:
    head = content[:200].lstrip()
    return head[:1] != b"<" and len(content) > 0


def fetch_data(session, station_nums, ymd, element_code) -> bytes:
    payload = WeatherDataPayload(
        stationNumList=list(station_nums),
        elementNumList=[[element_code, ""]],
        ymdList=[str(x) for x in ymd],
    )
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(SHOW_URL, data=payload.to_post_data(),
                                 headers={"Referer": ROOT_URL}, timeout=60)
            resp.raise_for_status()
            if not looks_like_csv(resp.content):
                raise RuntimeError("Non-CSV response (server busy or volume limit exceeded)")
            return resp.content
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(SLEEP_SEC * attempt)
    raise last_err


def _read_lines(content: bytes) -> List[str]:
    return content.decode("cp932", errors="replace").splitlines()


def merge_columns(lines_list: List[List[str]]) -> List[str]:
    """Column-wise merge of same-period responses covering different station batches."""
    if len(lines_list) == 1:
        return lines_list[0]
    n_rows = min(len(ls) for ls in lines_list)
    merged_rows = []
    for i in range(n_rows):
        merged = lines_list[0][i]
        for ls in lines_list[1:]:
            rest = ls[i].split(",", 1)[1] if "," in ls[i] else ""
            if rest:
                merged = f"{merged},{rest}"
        merged_rows.append(merged)
    return merged_rows


def write_lines(lines: List[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig", newline="")


def load_network():
    return json.loads(NETWORK_PATH.read_text(encoding="utf-8"))


def storm_date_range(code: str) -> Tuple[date, date]:
    s = json.loads((STORMS_DIR / f"{code}.json").read_text(encoding="utf-8"))
    track = s["track"]
    start = datetime.fromisoformat(track[0]["time"]) + timedelta(hours=9)  # UTC -> JST
    end = datetime.fromisoformat(track[-1]["time"]) + timedelta(hours=9)
    return start.date(), end.date()


def fetch_storm_kind(session, code: str, kind: str, stations: List[dict], dry_run: bool):
    d1, d2 = storm_date_range(code)
    ymd = [d1.year, d2.year, d1.month, d2.month, d1.day, d2.day]
    n_periods = count_periods_hourly(*ymd)
    spr = max(1, VOLUME_LIMIT // n_periods)  # stations per request
    nums = [station_num(s["prec_no"], s["block_no"]) for s in stations]
    batches = [nums[i:i + spr] for i in range(0, len(nums), spr)]

    if dry_run:
        print(f"{code} [{kind}] {d1}..{d2} ({n_periods}h) x {len(nums)} stations "
              f"-> {len(batches)} request(s)")
        return

    out_path = RAW_DIR / f"{code}_{kind}.csv"
    if out_path.exists():
        print(f"{code} [{kind}]: already downloaded, skipping ({out_path})")
        return

    # Cache each batch response individually under a per-storm/kind temp dir, so a
    # network drop partway through (e.g. batch 6/14) doesn't waste the batches that
    # already succeeded -- rerunning the same command resumes from the next one.
    batch_dir = RAW_DIR / "_batches" / f"{code}_{kind}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    batch_lines = []
    for bi, batch in enumerate(batches):
        batch_path = batch_dir / f"{bi:03d}.csv"
        if batch_path.exists():
            batch_lines.append(batch_path.read_text(encoding="utf-8-sig").splitlines())
            print(f"{code} [{kind}]: batch {bi + 1}/{len(batches)} ({len(batch)} stations) cached")
            continue
        content = fetch_data(session, batch, ymd, ELEMENT_CODE[kind])
        batch_path.write_text(content.decode("cp932"), encoding="utf-8-sig", newline="")
        batch_lines.append(_read_lines(content))
        print(f"{code} [{kind}]: batch {bi + 1}/{len(batches)} ({len(batch)} stations) ok")
        time.sleep(SLEEP_SEC)

    merged = merge_columns(batch_lines)
    write_lines(merged, out_path)
    for p in batch_dir.glob("*.csv"):
        p.unlink()
    batch_dir.rmdir()
    print(f"{code} [{kind}]: wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated storm codes, e.g. 1912,1915")
    ap.add_argument("--landfall-only", action="store_true",
                     help="use all landfallJP storms from data/index.json, plus any storm flagged "
                          "'damaging' (major Japan-wide damage per the Digital Typhoon disaster "
                          "database -- see data/damage_storm_codes.json -- even if best-track "
                          "landfall detection didn't flag it)")
    ap.add_argument("--kind", default="wind,rain", help="wind,rain or just one")
    ap.add_argument("--dry-run", action="store_true", help="print the request plan without fetching")
    args = ap.parse_args()

    network = load_network()
    kinds = [k.strip() for k in args.kind.split(",") if k.strip() in ("wind", "rain")]
    if not kinds:
        sys.exit("--kind must include wind and/or rain")

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.landfall_only:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        codes = [c for c, m in index.items() if m.get("landfallJP") or m.get("damaging")]
    else:
        sys.exit("specify --codes or --landfall-only")

    session = requests.Session()
    if not args.dry_run:
        session.get(ROOT_URL, timeout=30)  # establishes the session cookie obsdl expects

    failures = []
    for code in codes:
        for kind in kinds:
            try:
                fetch_storm_kind(session, code, kind, network[kind], args.dry_run)
            except Exception as e:  # noqa: BLE001 - keep going through the rest of the run
                print(f"{code} [{kind}]: FAILED ({e}) -- will retry on the next run "
                      f"(completed batches are cached)")
                failures.append(f"{code} [{kind}]")

    if failures and not args.dry_run:
        print()
        print(f"{len(failures)} failed: {', '.join(failures)}")
        print("Re-run the same command to retry just these (everything else is skipped as already done).")


if __name__ == "__main__":
    main()
