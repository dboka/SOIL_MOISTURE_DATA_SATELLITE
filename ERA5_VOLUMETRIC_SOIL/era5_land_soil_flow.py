from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CATALOG_DIR = DATA_DIR / "catalog"

ERA5_TO_SHORT_NAME = {
    "volumetric_soil_water_layer_1": "swvl1",
    "volumetric_soil_water_layer_2": "swvl2",
    "volumetric_soil_water_layer_3": "swvl3",
    "volumetric_soil_water_layer_4": "swvl4",
}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment value: {name}")
    return value


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("LATVIA_BBOX must have four comma-separated values")
    return parts[0], parts[1], parts[2], parts[3]


def date_range(start_date: str, end_date: str) -> list[date]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("--end-date must be on or after --start-date")
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_cds_request(
    start_date: str,
    end_date: str,
    variables: list[str],
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    days = date_range(start_date, end_date)
    min_lon, min_lat, max_lon, max_lat = bbox
    return {
        "variable": variables,
        "year": sorted({f"{day.year:04d}" for day in days}),
        "month": sorted({f"{day.month:02d}" for day in days}),
        "day": [f"{day.day:02d}" for day in days],
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "area": [max_lat, min_lon, min_lat, max_lon],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def save_request(dataset: str, request: dict[str, Any]) -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    output = {"dataset": dataset, "request": request}
    (CATALOG_DIR / "era5_land_request.json").write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )
    print(f"CDS request written: {CATALOG_DIR / 'era5_land_request.json'}")


def download_era5(dataset: str, request: dict[str, Any], output_path: Path) -> Path:
    import cdsapi

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        print(f"Already downloaded: {output_path}")
        return output_path
    cdsapi.Client().retrieve(dataset, request, str(output_path))
    print(f"Downloaded: {output_path}")
    return output_path


def coordinate_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise ValueError(f"Could not find coordinate from candidates: {', '.join(candidates)}")


def time_name(ds: xr.Dataset) -> str:
    return coordinate_name(ds, ("valid_time", "time"))


def normalize_longitudes(ds: xr.Dataset, lon_name: str) -> xr.Dataset:
    lon = ds[lon_name]
    if float(lon.max()) <= 180:
        return ds
    ds = ds.assign_coords({lon_name: (((lon + 180) % 360) - 180)})
    return ds.sortby(lon_name)


def crop_to_bbox(ds: xr.Dataset, bbox: tuple[float, float, float, float]) -> xr.Dataset:
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_name = coordinate_name(ds, ("latitude", "lat"))
    lon_name = coordinate_name(ds, ("longitude", "lon"))
    ds = normalize_longitudes(ds, lon_name)

    lat = ds[lat_name]
    lat_slice = slice(max_lat, min_lat) if float(lat[0]) > float(lat[-1]) else slice(min_lat, max_lat)
    return ds.sel({lat_name: lat_slice, lon_name: slice(min_lon, max_lon)})


def variable_names(ds: xr.Dataset, requested_variables: list[str]) -> list[str]:
    names = []
    for variable in requested_variables:
        short = ERA5_TO_SHORT_NAME.get(variable, variable)
        if short in ds.data_vars:
            names.append(short)
        elif variable in ds.data_vars:
            names.append(variable)
        else:
            raise ValueError(
                f"Variable {variable!r} was not found in the dataset. Available: {list(ds.data_vars)}"
            )
    return names


def daily_mean(ds: xr.Dataset) -> xr.Dataset:
    t_name = time_name(ds)
    if t_name != "time":
        ds = ds.rename({t_name: "time"})
    return ds.resample(time="1D").mean(keep_attrs=True)


def write_daily_tiff(
    array: xr.DataArray,
    variable: str,
    day: np.datetime64,
    output_dir: Path,
) -> Path:
    import rasterio
    from rasterio.transform import from_bounds

    lat_name = coordinate_name(array.to_dataset(name=variable), ("latitude", "lat"))
    lon_name = coordinate_name(array.to_dataset(name=variable), ("longitude", "lon"))
    array = array.squeeze(drop=True)
    for dim in list(array.dims):
        if dim not in {lat_name, lon_name}:
            print(f"Selecting first {dim} value for {variable} GeoTIFF export.")
            array = array.isel({dim: 0}).squeeze(drop=True)
    values = np.asarray(array.values, dtype="float32")
    if values.ndim != 2:
        raise ValueError(f"Expected a 2D daily array for {variable}, got shape {values.shape}")

    lat = np.asarray(array[lat_name].values, dtype="float64")
    lon = np.asarray(array[lon_name].values, dtype="float64")
    if lat[0] < lat[-1]:
        values = np.flipud(values)
        lat = lat[::-1]

    output_dir.mkdir(parents=True, exist_ok=True)
    day_text = np.datetime_as_string(day, unit="D").replace("-", "")
    output_path = output_dir / f"era5_land_{variable}_{day_text}_latvia.tif"
    nodata = -9999.0
    values_pct = values * 100.0
    values_pct = np.where(np.isfinite(values_pct), values_pct, nodata).astype("float32")

    x_res = abs(float(lon[1] - lon[0])) if lon.size > 1 else 0.1
    y_res = abs(float(lat[0] - lat[1])) if lat.size > 1 else 0.1
    west = float(lon.min() - x_res / 2)
    east = float(lon.max() + x_res / 2)
    south = float(lat.min() - y_res / 2)
    north = float(lat.max() + y_res / 2)
    transform = from_bounds(west, south, east, north, values_pct.shape[1], values_pct.shape[0])

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=values_pct.shape[0],
        width=values_pct.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(values_pct, 1)
        dst.update_tags(
            variable=variable,
            date=np.datetime_as_string(day, unit="D"),
            units="percent volumetric soil water",
            source_units=str(array.attrs.get("units", "m3 m-3")),
        )
        dst.update_tags(1, units="percent volumetric soil water")

    return output_path


def raster_summary(path: Path, date_text: str, variable: str) -> dict[str, Any]:
    import rasterio

    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        valid = data.compressed().astype("float64")
        return {
            "date": date_text,
            "variable": variable,
            "total_pixels": int(src.width * src.height),
            "valid_pixels": int(valid.size),
            "coverage_pct": float(valid.size / (src.width * src.height) * 100)
            if src.width and src.height
            else None,
            "units": src.tags(1).get("units"),
            "min": float(np.min(valid)) if valid.size else None,
            "mean": float(np.mean(valid)) if valid.size else None,
            "max": float(np.max(valid)) if valid.size else None,
            "path": str(path),
        }


def save_processing_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "era5_land_daily_stats.csv"
    fieldnames = [
        "date",
        "variable",
        "total_pixels",
        "valid_pixels",
        "coverage_pct",
        "units",
        "min",
        "mean",
        "max",
        "path",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Processing summary written: {output_path}")


def process_netcdf(path: Path, requested_variables: list[str], bbox: tuple[float, float, float, float]) -> None:
    print(f"Processing NetCDF: {path}")
    with xr.open_dataset(path) as source:
        ds = crop_to_bbox(source, bbox)
        variables = variable_names(ds, requested_variables)
        daily = daily_mean(ds[variables])
        summaries = []
        for variable in variables:
            for day in daily["time"].values:
                array = daily[variable].sel(time=day)
                output_path = write_daily_tiff(array, variable, day, PROCESSED_DIR)
                date_text = np.datetime_as_string(day, unit="D")
                summary = raster_summary(output_path, date_text, variable)
                summaries.append(summary)
                print(
                    f"{date_text} {variable}: mean {summary['mean']:.3f}% "
                    f"from {summary['valid_pixels']} pixels"
                    if summary["mean"] is not None
                    else f"{date_text} {variable}: no valid pixels"
                )
    save_processing_summary(summaries)


def default_raw_path(start_date: str, end_date: str) -> Path:
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    return RAW_DIR / f"era5_land_{start}_{end}.nc"


def main() -> int:
    load_env(ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Download and process ERA5-Land volumetric soil water for Latvia."
    )
    parser.add_argument("--start-date", default=os.getenv("ERA5_START_DATE", "2026-06-10"))
    parser.add_argument("--end-date", default=os.getenv("ERA5_END_DATE", "2026-06-18"))
    parser.add_argument("--dataset", default=os.getenv("ERA5_DATASET", "reanalysis-era5-land"))
    parser.add_argument(
        "--variables",
        default=os.getenv("ERA5_VARIABLES", "volumetric_soil_water_layer_1"),
        help="Comma-separated ERA5-Land variable names",
    )
    parser.add_argument("--input-netcdf", help="Process an existing ERA5-Land NetCDF")
    parser.add_argument("--output-netcdf", help="Download target path")
    parser.add_argument("--no-download", action="store_true", help="Only write the CDS request JSON")
    parser.add_argument("--skip-download", action="store_true", help="Process --input-netcdf without CDS")
    args = parser.parse_args()

    bbox = parse_bbox(env("LATVIA_BBOX", "20.5,55.6,28.5,58.1"))
    variables = split_csv(args.variables)
    request = build_cds_request(args.start_date, args.end_date, variables, bbox)
    save_request(args.dataset, request)

    if args.no_download:
        return 0

    if args.skip_download:
        if not args.input_netcdf:
            raise RuntimeError("--skip-download requires --input-netcdf")
        netcdf_path = Path(args.input_netcdf)
    elif args.input_netcdf:
        netcdf_path = Path(args.input_netcdf)
    else:
        netcdf_path = Path(args.output_netcdf) if args.output_netcdf else default_raw_path(args.start_date, args.end_date)
        download_era5(args.dataset, request, netcdf_path)

    process_netcdf(netcdf_path, variables, bbox)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
