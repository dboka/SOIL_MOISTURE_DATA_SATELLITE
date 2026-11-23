"""Download NOAA IMS 1 km GeoTIFFs and add daily snow classes to the viewer."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.windows import Window


ROOT = Path(__file__).resolve().parent
VIEWER = ROOT.parent / "ASCAT_HSAF_ORDER" / "moving_window_html"
BASE_BUNDLE = VIEWER / "data" / "hsaf_frames.js"
OUT = VIEWER / "data" / "ims_frames.js"
RAW = ROOT / "data"
ARCHIVE = "https://noaadata.apps.nsidc.org/NOAA/G02156/GIS/1km/{year}/"
CURRENT = "https://usicecenter.gov/File/DownloadCurrent?pId=66"
ARCHIVE_RE = re.compile(r"ims(?P<year>\d{4})(?P<doy>\d{3})_1km_GIS_v[\d.]+\.tif\.gz")
CURRENT_RE = re.compile(r"NIC\.IMS_v3_(?P<date>\d{8})_1km\.tif\.gz")


def archive_products(start: date, end: date) -> dict[date, dict]:
    products = {}
    for year in range((start - timedelta(days=1)).year, end.year + 1):
        url = ARCHIVE.format(year=year)
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        for filename in set(match.group(0) for match in ARCHIVE_RE.finditer(response.text)):
            match = ARCHIVE_RE.fullmatch(filename)
            created = datetime.strptime(match["year"] + match["doy"], "%Y%j").date()
            valid = created + timedelta(days=1)  # GeoTIFF date is production date.
            if start <= valid <= end:
                products[valid] = {"name": filename, "url": urljoin(url, filename), "source": "NSIDC archive"}
    return products


def download_current_if_needed(products: dict[date, dict], start: date, end: date) -> None:
    if all(day in products for day in dates(start, end)):
        return
    with requests.get(CURRENT, stream=True, timeout=90) as response:
        response.raise_for_status()
        disposition = response.headers.get("Content-Disposition", "")
        match = CURRENT_RE.search(disposition)
        if not match:
            raise RuntimeError(f"Could not identify USNIC current GeoTIFF: {disposition}")
        valid = datetime.strptime(match["date"], "%Y%m%d").date() + timedelta(days=1)
        if not (start <= valid <= end) or valid in products:
            return
        RAW.mkdir(exist_ok=True)
        path = RAW / match.group(0)
        if not path.exists():
            temporary = path.with_suffix(".part")
            with temporary.open("wb") as file:
                for chunk in response.iter_content(chunk_size=65536):
                    file.write(chunk)
            temporary.replace(path)
        products[valid] = {"name": match.group(0), "url": CURRENT, "source": "USNIC current"}


def dates(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def download(product: dict) -> Path:
    RAW.mkdir(exist_ok=True)
    path = RAW / product["name"]
    if path.exists():
        with gzip.open(path, "rb") as file:
            if file.read(4)[:2] in (b"II", b"MM"):
                return path
    temporary = path.with_suffix(".part")
    with requests.get(product["url"], stream=True, timeout=120) as response:
        response.raise_for_status()
        with temporary.open("wb") as file:
            for chunk in response.iter_content(chunk_size=65536):
                file.write(chunk)
    with gzip.open(temporary, "rb") as file:
        if file.read(4)[:2] not in (b"II", b"MM"):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Invalid GeoTIFF in {product['name']}")
    temporary.replace(path)
    return path


def base_grid() -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    text = BASE_BUNDLE.read_text(encoding="utf-8")
    payload = json.loads(text.split("=", 1)[1].split("\nwindow.HSAF_DATA", 1)[0].strip().rstrip(";"))
    grid = payload["grid"]
    shape = (grid["height"], grid["width"])
    lon = np.asarray(payload["lon"], dtype="float64").reshape(shape)
    lat = np.asarray(payload["lat"], dtype="float64").reshape(shape)
    mask = np.asarray(payload["datasets"]["swi_cop"]["frames"][0]["values"], dtype="int16").reshape(shape) >= 0
    return grid, lon, lat, mask


def frame(day: date, path: Path, product: dict, grid: dict, lon: np.ndarray, lat: np.ndarray, mask: np.ndarray) -> dict:
    with rasterio.open("/vsigzip/" + path.resolve().as_posix()) as src:
        if src.count != 1 or src.width != 24576 or src.height != 24576:
            raise RuntimeError(f"Unexpected IMS raster structure: {path.name}")
        xs, ys = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(lon[mask], lat[mask])
        cols = np.floor((xs - src.transform.c) / src.transform.a).astype("int32")
        rows = np.floor((ys - src.transform.f) / src.transform.e).astype("int32")
        within = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        raw = np.zeros(mask.shape, dtype="uint8")
        if np.any(within):
            r0, r1 = int(rows[within].min()), int(rows[within].max())
            c0, c1 = int(cols[within].min()), int(cols[within].max())
            data = src.read(1, window=Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1))
            sampled = np.zeros(rows.shape, dtype="uint8")
            sampled[within] = data[rows[within] - r0, cols[within] - c0]
            raw[mask] = sampled
    valid = mask & np.isin(raw, (2, 4))
    snow = mask & (raw == 4)
    values = np.full(mask.shape, grid["nodata"], dtype="int16")
    values[valid] = np.where(snow[valid], 1000, 0)
    count = int(valid.sum())
    snow_count = int(snow.sum())
    snow_pct = round(snow_count / count * 100, 2) if count else None
    land = raw[mask]
    breakdown = {
        "latviaLandCells": int(mask.sum()),
        "tilesOnLand": 1,
        "noTileCells": 0,
        "cloudCells": 0,
        "waterCells": int(np.count_nonzero(np.isin(land, (1, 3)))),
        "noDataCells": int(np.count_nonzero(~np.isin(land, (1, 2, 3, 4)))),
    }
    valid_time = f"{day.isoformat()}T00:00:00Z"
    return {
        "date": day.isoformat(),
        "label": "IMS daily analysis",
        "satellite": "NOAA/USNIC multisensor IMS",
        "startUtc": valid_time,
        "endUtc": valid_time,
        "coveragePct": round(count / mask.sum() * 100, 2),
        "validCells": count,
        "sourceFiles": 1,
        "source": product["source"],
        "sourceFile": product["name"],
        "coverageBreakdown": breakdown,
        "snowCells": snow_count,
        "snowPct": snow_pct,
        "min": 0 if count else None,
        "mean": snow_pct,
        "max": 100 if snow_count else 0 if count else None,
        "values": values.ravel().tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    yesterday = date.today() - timedelta(days=1)
    parser.add_argument("--start", type=date.fromisoformat, default=yesterday - timedelta(days=2))
    parser.add_argument("--end", type=date.fromisoformat, default=yesterday)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    products = archive_products(args.start, args.end)
    download_current_if_needed(products, args.start, args.end)
    if not products:
        raise RuntimeError("No IMS 1 km GeoTIFFs found for this period")
    missing = [day for day in dates(args.start, args.end) if day not in products]
    if missing:
        print("IMS dates unavailable:", ", ".join(day.isoformat() for day in missing), flush=True)
    grid, lon, lat, mask = base_grid()
    frames = []
    for number, (day, product) in enumerate(sorted(products.items()), 1):
        path = download(product)
        item = frame(day, path, product, grid, lon, lat, mask)
        frames.append(item)
        print(f"[{number}/{len(products)}] {day}: {item['snowPct']}% snow over {item['coveragePct']}% land coverage", flush=True)
    dataset = {
        "id": "ims",
        "name": "NOAA IMS 1 km",
        "title": "NOAA Interactive Multisensor Snow and Ice Mapping System",
        "subtitle": f"{frames[0]['date']} to {frames[-1]['date']} daily 1 km snow/no-snow analyses for Latvia",
        "window": {"start": frames[0]["date"], "end": frames[-1]["date"]},
        "scale": {"min": 0, "max": 100, "label": "Binary snow state"},
        "units": "snow/no snow",
        "timeMode": "daily",
        "note": "IMS is an analyst-produced snow/no-snow classification, not snow-cover percentage. Class 2 is snow-free land; class 4 is snow-covered land. Sea and sea ice are excluded. The GeoTIFF filename is its production date; this frame is valid at 00:00 UTC on the following day. There is no single satellite overpass time.",
        "frames": frames,
    }
    OUT.write_text("window.HSAF_VIEWER_DATA.datasets.ims = " + json.dumps(dataset, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(frames)} valid dates, {OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
