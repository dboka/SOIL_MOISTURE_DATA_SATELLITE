"""Download CLMS GFSC 60 m tiles and add daily Latvia frames to the static viewer.

The viewer has a fixed EPSG:3059 1 km grid. GFSC values are sampled from their
native 60 m tiles at the centres of that grid; the raw ZIPs stay local.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.io import MemoryFile


ROOT = Path(__file__).resolve().parent
VIEWER = ROOT.parent / "ASCAT_HSAF_ORDER" / "moving_window_html"
BASE_BUNDLE = VIEWER / "data" / "hsaf_frames.js"
OUT = VIEWER / "data" / "gfsc_frames.js"
RAW = ROOT / "data"
DATASET_ID = "clms_wsi_gap-filled-fractional-snow-cover_europe_utm_60m_daily_v1"
CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DOWNLOAD = "https://download.dataspace.copernicus.eu/odata/v1/Products({})/$value"
NAME_RE = re.compile(r"^CLMS_WSI_GFSC_060m_T(?P<tile>[A-Z0-9]+)_(?P<date>\d{8})P7D_COMB_V\d+$")


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
    aoi = "POLYGON((20.9 55.6,28.3 55.6,28.3 58.2,20.9 58.2,20.9 55.6))"
    products = {}
    day = start
    while day <= end:
        # Query by day: a broad unsorted OData query can return duplicates
        # across pages and omit real products when its result set exceeds 100.
        filter_text = (
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'datasetIdentifier' "
            f"and att/OData.CSC.StringAttribute/Value eq '{DATASET_ID}') and "
            f"ContentDate/Start ge {day.isoformat()}T00:00:00.000Z and "
            f"ContentDate/Start le {day.isoformat()}T23:59:59.999Z and "
            f"OData.CSC.Intersects(area=geography'SRID=4326;{aoi}')"
        )
        response = requests.get(
            CATALOGUE,
            params={"$filter": filter_text, "$select": "Name,Id,ContentLength", "$top": 100},
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("@odata.nextLink"):
            raise RuntimeError(f"More than 100 GFSC products found on {day}; narrow the search area")
        for product in body.get("value", []):
            if NAME_RE.fullmatch(product["Name"]):
                products[product["Id"]] = product
        day += timedelta(days=1)
    return sorted(products.values(), key=lambda product: product["Name"])


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
    with requests.get(
        DOWNLOAD.format(product["Id"]),
        headers={"Authorization": f"Bearer {access_token}"},
        stream=True,
        timeout=120,
    ) as response:
        response.raise_for_status()
        temporary = path.with_suffix(".part")
        with temporary.open("wb") as file:
            for chunk in response.iter_content(chunk_size=65536):
                file.write(chunk)
        if not zipfile.is_zipfile(temporary):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Invalid product ZIP: {product['Name']}")
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


def frame(day: date, paths: list[Path], grid: dict, lon: np.ndarray, lat: np.ndarray, mask: np.ndarray) -> dict:
    values = np.full(lon.shape, grid["nodata"], dtype="int16")
    status = np.full(lon.shape, -1, dtype="int16")
    observed = np.zeros(lon.shape, dtype="uint64")
    flat_lon, flat_lat = lon.ravel(), lat.ravel()
    flat_mask = mask.ravel()
    flat_values = values.ravel()
    flat_status = status.ravel()
    flat_observed = observed.ravel()
    tiles_on_land = 0
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            members = {suffix: [name for name in archive.namelist() if name.endswith(suffix)]
                       for suffix in ("_GF.tif", "_AT.tif", "_QAFLAGS.tif")}
            if any(len(names) != 1 for names in members.values()):
                raise ValueError(f"Expected GF, AT and QAFLAGS bands in {path.name}")
            with MemoryFile(archive.read(members["_GF.tif"][0])) as mem, mem.open() as src:
                transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                xs, ys = transformer.transform(flat_lon, flat_lat)
                bounds = src.bounds
                indices = np.flatnonzero(
                    flat_mask &
                    (xs >= bounds.left) & (xs < bounds.right) &
                    (ys >= bounds.bottom) & (ys < bounds.top)
                )
                if indices.size:
                    tiles_on_land += 1
                    sampled = np.fromiter(
                        (item[0] for item in src.sample(zip(xs[indices], ys[indices]))),
                        dtype="uint8",
                        count=len(indices),
                    )
                    previous = flat_status[indices]
                    replace_status = (previous < 0) | ((previous > 100) & (sampled <= 100))
                    flat_status[indices[replace_status]] = sampled[replace_status]
                    valid = sampled <= 100  # 205 cloud, 210 water, 255 no data
                    use = valid & (flat_values[indices] < 0)
                    flat_values[indices[use]] = sampled[use].astype("int16") * 10
                    if np.any(use):
                        coords = list(zip(xs[indices[use]], ys[indices[use]]))
                        with MemoryFile(archive.read(members["_AT.tif"][0])) as at_mem, at_mem.open() as at_src:
                            times = np.fromiter((item[0] for item in at_src.sample(coords)), dtype="uint32", count=len(coords))
                        with MemoryFile(archive.read(members["_QAFLAGS.tif"][0])) as flags_mem, flags_mem.open() as flags_src:
                            flags = np.fromiter((item[0] for item in flags_src.sample(coords)), dtype="uint8", count=len(coords))
                        # 1=S1, 2=S2; zero acquisition time remains unavailable.
                        sensor = np.where(flags & 128, 1, 2).astype("uint64")
                        flat_observed[indices[use]] = times.astype("uint64") * 3 + sensor
    valid_values = flat_values[flat_values >= 0].astype("float64") * grid["valueScale"]
    observation_codes = sorted(int(code) for code in np.unique(flat_observed) if code >= 3)
    observation_lookup = [
        {
            "timeUtc": datetime.fromtimestamp(code // 3, timezone.utc).isoformat().replace("+00:00", "Z"),
            "sensor": "Sentinel-1" if code % 3 == 1 else "Sentinel-2",
        }
        for code in observation_codes
    ]
    observation_index = np.zeros(flat_observed.shape, dtype="uint8")
    for index, code in enumerate(observation_codes, 1):
        observation_index[flat_observed == code] = index
    day_text = day.isoformat()
    land_status = flat_status[flat_mask]
    return {
        "date": day_text,
        "label": "GFSC daily composite",
        "satellite": "CLMS GFSC (S1 + S2)",
        "startUtc": f"{day_text}T00:00:00Z",
        "endUtc": f"{day_text}T23:59:59Z",
        "coveragePct": round(float(valid_values.size / mask.sum() * 100), 2),
        "validCells": int(valid_values.size),
        "sourceFiles": len(paths),
        "coverageBreakdown": {
            "latviaLandCells": int(mask.sum()),
            "tilesOnLand": tiles_on_land,
            "noTileCells": int(np.count_nonzero(land_status < 0)),
            "cloudCells": int(np.count_nonzero(land_status == 205)),
            "waterCells": int(np.count_nonzero(land_status == 210)),
            "noDataCells": int(np.count_nonzero(land_status == 255)),
        },
        "observations": observation_lookup,
        "observationIndex": observation_index.tolist(),
        "min": round(float(valid_values.min()), 1) if valid_values.size else None,
        "mean": round(float(valid_values.mean()), 1) if valid_values.size else None,
        "max": round(float(valid_values.max()), 1) if valid_values.size else None,
        "values": flat_values.tolist(),
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
        raise RuntimeError("No GFSC products found for this area and date window")
    user, password = credentials(args.env_file)
    access_token = token(user, password)
    grid, lon, lat, mask = base_grid()
    by_day = defaultdict(list)
    for number, product in enumerate(products, 1):
        if number % 20 == 0:
            access_token = token(user, password)
        path = download(product, access_token)
        day = datetime.strptime(NAME_RE.fullmatch(product["Name"])["date"], "%Y%m%d").date()
        by_day[day].append(path)
        print(f"[{number}/{len(products)}] {product['Name']}", flush=True)
    frames = [frame(day, paths, grid, lon, lat, mask) for day, paths in sorted(by_day.items())]
    dataset = {
        "id": "gfsc",
        "name": "CLMS GFSC 60 m",
        "title": "Copernicus CLMS Gap-filled Fractional Snow Cover",
        "subtitle": f"{frames[0]['date']} to {frames[-1]['date']} daily composites; native 60 m sampled on the viewer's 1 km Latvia grid",
        "window": {"start": frames[0]["date"], "end": frames[-1]["date"]},
        "scale": {"min": 0, "max": 100, "label": "Snow cover fraction, %"},
        "units": "% snow cover",
        "timeMode": "daily",
        "note": "Daily S1/S2 composite of the previous 7 days, not a single overpass. 205 cloud, 210 water and 255 no data are excluded; coverage is the share of Latvia land grid cells with a valid GF value.",
        "frames": frames,
    }
    OUT.write_text("window.HSAF_VIEWER_DATA.datasets.gfsc = " + json.dumps(dataset, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(frames)} days, {OUT.stat().st_size:,} bytes)")
    for item in frames:
        print(item["date"], item["sourceFiles"], "tiles", item["coveragePct"], "% Latvia land coverage")


if __name__ == "__main__":
    main()
