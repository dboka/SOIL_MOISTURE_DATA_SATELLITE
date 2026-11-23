"""Download daily CLMS SCE Europe 500 m MODIS COGs for the Latvia viewer."""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests
from rasterio.io import MemoryFile


ROOT = Path(__file__).resolve().parent
VIEWER = ROOT.parent / "ASCAT_HSAF_ORDER" / "moving_window_html"
BASE_BUNDLE = VIEWER / "data" / "hsaf_frames.js"
OUT = VIEWER / "data" / "sce_frames.js"
RAW = ROOT / "data"
CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DATASET_ID = "sce_europe_500m_daily_v1"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DOWNLOAD = "https://download.dataspace.copernicus.eu/odata/v1/Products({})/$value"
NAME_RE = re.compile(r"^c_gls_SCE500_(?P<date>\d{8})0000_CEURO_MODIS_V[\d.]+_cog$")


def credentials(env_file: Path | None) -> tuple[str, str]:
    env = dict(os.environ)
    if env_file:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"\''))
    user, password = env.get("CDSE_USER"), env.get("CDSE_PASSWORD")
    if not user or not password:
        raise RuntimeError("Set CDSE_USER and CDSE_PASSWORD or pass --env-file")
    return user, password


def catalogue(start: date, end: date) -> list[dict]:
    products = []
    day = start
    while day <= end:
        filter_text = (
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'datasetIdentifier' "
            f"and att/OData.CSC.StringAttribute/Value eq '{DATASET_ID}') and "
            f"ContentDate/Start ge {day.isoformat()}T00:00:00.000Z and "
            f"ContentDate/Start le {day.isoformat()}T23:59:59.999Z"
        )
        response = requests.get(
            CATALOGUE,
            params={"$filter": filter_text, "$select": "Name,Id,ContentLength", "$top": 100},
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("@odata.nextLink"):
            raise RuntimeError(f"Unexpected catalogue pagination on {day}")
        matches = [product for product in body.get("value", []) if NAME_RE.fullmatch(product["Name"])]
        if len(matches) > 1:
            raise RuntimeError(f"Multiple MODIS COGs found for {day}: {[p['Name'] for p in matches]}")
        products.extend(matches)
        day += timedelta(days=1)
    return sorted(products, key=lambda product: product["Name"])


def token(user: str, password: str) -> str:
    response = requests.post(
        TOKEN_URL,
        data={"client_id": "cdse-public", "username": user, "password": password, "grant_type": "password"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def download(product: dict, access_token: str) -> Path:
    RAW.mkdir(exist_ok=True)
    path = RAW / f'{product["Name"]}.zip'
    if path.exists() and zipfile.is_zipfile(path):
        return path
    temporary = path.with_suffix(".part")
    with requests.get(
        DOWNLOAD.format(product["Id"]),
        headers={"Authorization": f"Bearer {access_token}"},
        stream=True,
        timeout=120,
    ) as response:
        response.raise_for_status()
        with temporary.open("wb") as file:
            for chunk in response.iter_content(chunk_size=65536):
                file.write(chunk)
    if not zipfile.is_zipfile(temporary):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Invalid SCE product ZIP: {product['Name']}")
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


def frame(day: date, path: Path, grid: dict, lon: np.ndarray, lat: np.ndarray, mask: np.ndarray) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff"))]
        if len(members) != 1:
            raise RuntimeError(f"Expected one COG in {path.name}, found {members}")
        with MemoryFile(archive.read(members[0])) as mem, mem.open() as src:
            if src.count != 1 or src.crs.to_epsg() != 4326:
                raise RuntimeError(f"Unexpected SCE COG structure in {path.name}")
            col = np.floor((lon - src.transform.c) / src.transform.a).astype("int32")
            row = np.floor((lat - src.transform.f) / src.transform.e).astype("int32")
            within = mask & (row >= 0) & (row < src.height) & (col >= 0) & (col < src.width)
            from rasterio.windows import Window
            min_row, max_row = int(row[within].min()), int(row[within].max())
            min_col, max_col = int(col[within].min()), int(col[within].max())
            window = Window(min_col, min_row, max_col - min_col + 1, max_row - min_row + 1)
            data = src.read(1, window=window)
            raw = np.full(mask.shape, 255, dtype="int16")
            raw[within] = data[row[within] - min_row, col[within] - min_col]
            tags = src.tags()
    valid = mask & (raw >= 100) & (raw <= 200)
    values = np.full(mask.shape, grid["nodata"], dtype="int16")
    values[valid] = (raw[valid] - 100) * 10
    physical = values[valid].astype("float64") * grid["valueScale"]
    day_text = day.isoformat()
    start_utc = tags.get("time_coverage_start")
    end_utc = tags.get("time_coverage_end")
    if not start_utc or not end_utc or not start_utc.startswith(day_text) or not end_utc.startswith(day_text):
        raise RuntimeError(f"Missing or mismatched MODIS sensing window in {path.name}")
    land = raw[mask]
    breakdown = {
        "latviaLandCells": int(mask.sum()),
        "tilesOnLand": 1,
        "noTileCells": 0,
        "cloudCells": int(np.count_nonzero(land == 30)),
        "waterCells": int(np.count_nonzero(np.isin(land, (20, 21, 22)))),
        "noDataCells": int(np.count_nonzero(~((land >= 100) & (land <= 200)) & (land != 30) & ~np.isin(land, (20, 21, 22)))),
    }
    return {
        "date": day_text,
        "label": "SCE MODIS daily",
        "satellite": "Terra MODIS",
        "startUtc": start_utc,
        "endUtc": end_utc,
        "coveragePct": round(float(valid.sum() / mask.sum() * 100), 2),
        "validCells": int(valid.sum()),
        "sourceFiles": 1,
        "coverageBreakdown": breakdown,
        "min": round(float(physical.min()), 1) if physical.size else None,
        "mean": round(float(physical.mean()), 1) if physical.size else None,
        "max": round(float(physical.max()), 1) if physical.size else None,
        "values": values.ravel().tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    yesterday = date.today() - timedelta(days=1)
    parser.add_argument("--start", type=date.fromisoformat, default=yesterday - timedelta(days=2))
    parser.add_argument("--end", type=date.fromisoformat, default=yesterday)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    products = catalogue(args.start, args.end)
    if not products:
        raise RuntimeError("No MODIS SCE COG products found")
    user, password = credentials(args.env_file)
    access_token = token(user, password)
    grid, lon, lat, mask = base_grid()
    frames = []
    for number, product in enumerate(products, 1):
        if number % 20 == 0:
            access_token = token(user, password)
        path = download(product, access_token)
        stamp = NAME_RE.fullmatch(product["Name"])["date"]
        day = date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
        item = frame(day, path, grid, lon, lat, mask)
        frames.append(item)
        print(f"[{number}/{len(products)}] {day}: {item['coveragePct']}% Latvia coverage", flush=True)
    dataset = {
        "id": "sce",
        "name": "CLMS SCE 500 m",
        "title": "Copernicus Snow Cover Extent Europe 500 m",
        "subtitle": f"{frames[0]['date']} to {frames[-1]['date']} Terra MODIS daily snow cover; native 500 m sampled on the viewer's 1 km Latvia grid",
        "window": {"start": frames[0]["date"], "end": frames[-1]["date"]},
        "scale": {"min": 0, "max": 100, "label": "Snow cover fraction, %"},
        "units": "% snow cover",
        "timeMode": "daily",
        "note": "Frame time is the product's Terra MODIS sensing window, not an exact per-pixel overpass. Valid COG codes 100-200 become 0-100% snow; code 255 means no data. Cloud code 30, water codes 20-22, polar night and errors are excluded when present. Missing values cannot all be attributed to clouds.",
        "frames": frames,
    }
    OUT.write_text("window.HSAF_VIEWER_DATA.datasets.sce = " + json.dumps(dataset, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(frames)} days, {OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
