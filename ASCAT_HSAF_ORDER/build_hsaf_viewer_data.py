from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
HSAF_INDEX_PATH = ROOT / "data" / "clean_overpass_tiffs" / "hsaf_h28_clean_overpass_tiff_index.csv"
COPERNICUS_DIR = PROJECT_ROOT / "COPERNICUS" / "data" / "grid_tiffs" / "daily_ssm"
SWI_DIR = PROJECT_ROOT / "COPERNICUS_SWI" / "data" / "grid_tiffs" / "daily_swi"
ERA5_DIR = PROJECT_ROOT / "ERA5_VOLUMETRIC_SOIL" / "data" / "processed"
OUT_DIR = ROOT / "moving_window_html" / "data"
OUT_PATH = OUT_DIR / "hsaf_frames.js"
NODATA_OUT = -1
COPERNICUS_RE = re.compile(r"lv_1x1_ssm_(?P<date>\d{8})\.tif$")
SWI_RE = re.compile(r"lv_1x1_swi010_(?P<date>\d{8})\.tif$")
ERA5_RE = re.compile(r"era5_land_swvl1_(?P<date>\d{8})_latvia\.tif$")


def rounded_float(value: str | float, digits: int = 2) -> float:
    return round(float(value), digits)


def valid_mask(data: np.ndarray, nodata: float | int | None) -> np.ndarray:
    valid = np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    valid &= (data >= 0) & (data <= 100)
    return valid


def date_from_yyyymmdd(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def grid_metadata(src: rasterio.DatasetReader, data: np.ndarray) -> tuple[dict, list[float], list[float]]:
    height, width = data.shape
    transform = src.transform
    xs = transform.c + (np.arange(width) + 0.5) * transform.a
    ys = transform.f + (np.arange(height) + 0.5) * transform.e
    xx, yy = np.meshgrid(xs, ys)
    transformer = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
    lon_grid, lat_grid = transformer.transform(xx, yy)
    meta = {
        "width": int(width),
        "height": int(height),
        "crs": str(src.crs),
        "bounds": [round(v, 3) for v in src.bounds],
        "nodata": NODATA_OUT,
        "valueScale": 0.1,
        "units": "percent",
    }
    return meta, np.round(lon_grid.astype("float64"), 5).ravel().tolist(), np.round(
        lat_grid.astype("float64"), 5
    ).ravel().tolist()


def encode_tiff(path: Path) -> tuple[np.ndarray, dict, list[float], list[float], np.ndarray]:
    with rasterio.open(path) as src:
        data = src.read(1).astype("float32")
        valid = valid_mask(data, src.nodata)
        values = np.where(valid, np.rint(data * 10).astype("int16"), NODATA_OUT)
        meta, lon, lat = grid_metadata(src, data)
    return values, meta, lon, lat, valid


def build_hsaf_dataset() -> tuple[dict, dict, list[float], list[float]]:
    with HSAF_INDEX_PATH.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    rows = [
        row
        for row in rows
        if "2026-06-13" <= row["date"] <= "2026-06-17"
        and Path(row["output_tiff"]).exists()
    ]
    rows = sorted(rows, key=lambda row: (row["sensing_start_utc"], row["satellite"]))
    if not rows:
        raise SystemExit(f"No 2026-06-13..2026-06-17 HSAF TIFFs found in {HSAF_INDEX_PATH}")

    frames = []
    grid = None
    lon = lat = None
    for row in rows:
        values, frame_grid, frame_lon, frame_lat, _valid = encode_tiff(Path(row["output_tiff"]))
        if grid is None:
            grid, lon, lat = frame_grid, frame_lon, frame_lat
        frames.append(
            {
                "date": row["date"],
                "label": row["satellite"],
                "satellite": row["satellite"],
                "startUtc": row["sensing_start_utc"],
                "endUtc": row["sensing_end_utc"],
                "coveragePct": rounded_float(row["clean_coverage_pct"]),
                "validCells": int(row["clean_valid_grid_cells"]),
                "sourceFiles": int(row["source_file_count"]),
                "min": rounded_float(row["min"]),
                "mean": rounded_float(row["mean"]),
                "max": rounded_float(row["max"]),
                "values": values.ravel().tolist(),
            }
        )

    dataset = {
        "id": "hsaf",
        "name": "HSAF",
        "title": "H SAF H28 ASCAT surface soil moisture",
        "subtitle": "13-17 June 2026 overpasses",
        "window": {"start": "2026-06-13", "end": "2026-06-17"},
        "scale": {"min": 0, "max": 100, "label": "Soil moisture, % saturation"},
        "units": "percent saturation",
        "timeMode": "overpass",
        "frames": frames,
    }
    return dataset, grid, lon, lat


def build_copernicus_dataset() -> tuple[dict, dict, list[float], list[float]]:
    paths = [
        path
        for path in sorted(COPERNICUS_DIR.glob("lv_1x1_ssm_202606*.tif"))
        if "20260601" <= path.stem[-8:] <= "20260623"
    ]
    if not paths:
        raise SystemExit(f"No 2026-06-01..2026-06-23 Copernicus TIFFs found in {COPERNICUS_DIR}")

    frames = []
    grid = None
    lon = lat = None
    for path in paths:
        values, frame_grid, frame_lon, frame_lat, valid = encode_tiff(path)
        if grid is None:
            grid, lon, lat = frame_grid, frame_lon, frame_lat
        raw = (values.astype("float64") * frame_grid["valueScale"]).ravel()
        valid_values = raw[valid.ravel()]
        match = COPERNICUS_RE.search(path.name)
        if not match:
            raise ValueError(f"Unexpected Copernicus TIFF name: {path.name}")
        date_text = date_from_yyyymmdd(match.group("date"))
        frames.append(
            {
                "date": date_text,
                "label": "CLMS daily",
                "satellite": "Copernicus CLMS",
                "startUtc": f"{date_text}T00:00:00Z",
                "endUtc": f"{date_text}T23:59:59Z",
                "coveragePct": rounded_float(valid.mean() * 100),
                "validCells": int(valid.sum()),
                "sourceFiles": 1,
                "min": float(np.min(valid_values)) if valid_values.size else None,
                "mean": float(np.mean(valid_values)) if valid_values.size else None,
                "max": float(np.max(valid_values)) if valid_values.size else None,
                "values": values.ravel().tolist(),
            }
        )

    dataset = {
        "id": "copernicus",
        "name": "Copernicus SSM",
        "title": "Copernicus CLMS Surface Soil Moisture",
        "subtitle": "1-23 June 2026 daily frames",
        "window": {"start": "2026-06-01", "end": "2026-06-23"},
        "scale": {"min": 0, "max": 100, "label": "Soil moisture, %"},
        "units": "%",
        "timeMode": "daily",
        "frames": frames,
    }
    return dataset, grid, lon, lat


def build_swi_dataset() -> tuple[dict, dict, list[float], list[float]]:
    paths = [
        path
        for path in sorted(SWI_DIR.glob("lv_1x1_swi010_202606*.tif"))
        if "20260601" <= path.stem[-8:] <= "20260623"
    ]
    if not paths:
        raise SystemExit(f"No 2026-06-01..2026-06-23 SWI TIFFs found in {SWI_DIR}")

    frames = []
    grid = None
    lon = lat = None
    for path in paths:
        values, frame_grid, frame_lon, frame_lat, valid = encode_tiff(path)
        if grid is None:
            grid, lon, lat = frame_grid, frame_lon, frame_lat
        raw = (values.astype("float64") * frame_grid["valueScale"]).ravel()
        valid_values = raw[valid.ravel()]
        match = SWI_RE.search(path.name)
        if not match:
            raise ValueError(f"Unexpected SWI TIFF name: {path.name}")
        date_text = date_from_yyyymmdd(match.group("date"))
        frames.append(
            {
                "date": date_text,
                "label": "SWI010 daily",
                "satellite": "Copernicus CLMS SWI",
                "startUtc": f"{date_text}T00:00:00Z",
                "endUtc": f"{date_text}T23:59:59Z",
                "coveragePct": rounded_float(valid.mean() * 100),
                "validCells": int(valid.sum()),
                "sourceFiles": 1,
                "min": float(np.min(valid_values)) if valid_values.size else None,
                "mean": float(np.mean(valid_values)) if valid_values.size else None,
                "max": float(np.max(valid_values)) if valid_values.size else None,
                "values": values.ravel().tolist(),
            }
        )

    dataset = {
        "id": "swi_cop",
        "name": "SWI_COP",
        "title": "Copernicus CLMS Soil Water Index SWI010",
        "subtitle": "1-23 June 2026 daily SWI010 frames",
        "window": {"start": "2026-06-01", "end": "2026-06-23"},
        "scale": {"min": 0, "max": 100, "label": "Soil Water Index, %"},
        "units": "%",
        "timeMode": "daily",
        "note": "SWI010 is a Soil Water Index layer with a 10-day characteristic time length; it represents profile moisture dynamics, not the same quantity as surface soil moisture.",
        "frames": frames,
    }
    return dataset, grid, lon, lat


def sample_era5_to_viewer_grid(path: Path, lon: list[float], lat: list[float]) -> tuple[np.ndarray, np.ndarray]:
    coords = list(zip(lon, lat))
    with rasterio.open(path) as src:
        sampled = np.fromiter((item[0] for item in src.sample(coords)), dtype="float32")
        valid = valid_mask(sampled, src.nodata)
        values = np.where(valid, np.rint(sampled * 10).astype("int16"), NODATA_OUT)
    return values, valid


def build_era5_dataset(grid: dict, lon: list[float], lat: list[float]) -> dict:
    paths = []
    for path in sorted(ERA5_DIR.glob("era5_land_swvl1_*_latvia.tif")):
        match = ERA5_RE.search(path.name)
        if match and "20260610" <= match.group("date") <= "20260618":
            paths.append(path)
    if not paths:
        raise SystemExit(f"No 2026-06-10..2026-06-18 ERA5-Land TIFFs found in {ERA5_DIR}")

    frames = []
    for path in paths:
        match = ERA5_RE.search(path.name)
        if not match:
            raise ValueError(f"Unexpected ERA5 TIFF name: {path.name}")
        date_text = date_from_yyyymmdd(match.group("date"))
        values, valid = sample_era5_to_viewer_grid(path, lon, lat)
        raw = values.astype("float64") * grid["valueScale"]
        valid_values = raw[valid]
        frames.append(
            {
                "date": date_text,
                "label": "ERA5-Land daily",
                "satellite": "ERA5-Land",
                "startUtc": f"{date_text}T00:00:00Z",
                "endUtc": f"{date_text}T23:59:59Z",
                "coveragePct": rounded_float(valid.mean() * 100),
                "validCells": int(valid.sum()),
                "sourceFiles": 1,
                "min": float(np.min(valid_values)) if valid_values.size else None,
                "mean": float(np.mean(valid_values)) if valid_values.size else None,
                "max": float(np.max(valid_values)) if valid_values.size else None,
                "values": values.tolist(),
            }
        )

    return {
        "id": "era5",
        "name": "ERA5-Land",
        "title": "ERA5-Land volumetric soil water layer 1",
        "subtitle": "10-18 June 2026 daily volumetric soil water, shown as soil moisture %",
        "window": {"start": "2026-06-10", "end": "2026-06-18"},
        "scale": {"min": 0, "max": 100, "label": "Volumetric soil water, %"},
        "units": "percent volumetric soil water",
        "timeMode": "daily",
        "note": "ERA5-Land swvl1 is volumetric soil water in the 0-7 cm layer, not the same satellite surface soil moisture retrieval.",
        "frames": frames,
    }


def assert_same_grid(left: dict, right: dict) -> None:
    keys = ["width", "height", "crs", "bounds", "nodata", "valueScale"]
    mismatch = [key for key in keys if left.get(key) != right.get(key)]
    if mismatch:
        raise SystemExit(f"HSAF and Copernicus grids do not match: {mismatch}")


def build_payload() -> dict:
    hsaf, grid, lon, lat = build_hsaf_dataset()
    copernicus, cop_grid, _cop_lon, _cop_lat = build_copernicus_dataset()
    assert_same_grid(grid, cop_grid)
    swi, swi_grid, _swi_lon, _swi_lat = build_swi_dataset()
    assert_same_grid(grid, swi_grid)
    era5 = build_era5_dataset(grid, lon, lat)
    return {
        "title": "Latvia soil moisture moving window",
        "defaultDataset": "hsaf",
        "scale": {"min": 0, "max": 100, "label": "Soil moisture"},
        "grid": grid,
        "lon": lon,
        "lat": lat,
        "datasets": {
            "hsaf": hsaf,
            "copernicus": copernicus,
            "swi_cop": swi,
            "era5": era5,
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    OUT_PATH.write_text(
        "window.HSAF_VIEWER_DATA = "
        + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        + ";\nwindow.HSAF_DATA = window.HSAF_VIEWER_DATA.datasets.hsaf;\n",
        encoding="utf-8",
    )
    print(f"HSAF frames: {len(payload['datasets']['hsaf']['frames'])}")
    print(f"Copernicus frames: {len(payload['datasets']['copernicus']['frames'])}")
    print(f"SWI_COP frames: {len(payload['datasets']['swi_cop']['frames'])}")
    print(f"ERA5-Land frames: {len(payload['datasets']['era5']['frames'])}")
    print(f"Grid: {payload['grid']['width']} x {payload['grid']['height']}")
    print(f"Viewer data written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
