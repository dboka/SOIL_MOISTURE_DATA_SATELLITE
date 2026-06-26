from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from sample_hsaf_to_lv_grid import DEFAULT_GRID, RELEVANT_DIR, hsaf_crs, parse_name, sample_file


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "overpass_tiffs"
NODATA = -9999.0


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M%S")


def iso_z(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def grid_geometry(grid: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
    xs = np.sort(grid["x"].unique())
    ys = np.sort(grid["y"].unique())
    x_step = float(np.median(np.diff(xs)))
    y_step = float(np.median(np.diff(ys)))
    if not np.isclose(x_step, 1000) or not np.isclose(y_step, 1000):
        raise SystemExit(f"Expected 1000 m grid spacing, got x={x_step}, y={y_step}")
    transform = from_origin(xs.min() - x_step / 2, ys.max() + y_step / 2, x_step, y_step)
    return xs, ys, transform


def group_overpasses(records: list[dict], threshold_minutes: int) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for (_date, _sat), sat_records in pd.DataFrame(records).groupby(["date", "sat"]):
        ordered = sorted(sat_records.to_dict("records"), key=lambda row: row["start_dt"])
        current: list[dict] = []
        current_end: datetime | None = None
        for row in ordered:
            if not current:
                current = [row]
                current_end = row["end_dt"]
                continue
            assert current_end is not None
            if row["start_dt"] <= current_end + timedelta(minutes=threshold_minutes):
                current.append(row)
                current_end = max(current_end, row["end_dt"])
            else:
                groups.append(current)
                current = [row]
                current_end = row["end_dt"]
        if current:
            groups.append(current)
    return groups


def write_tiff(
    output: Path,
    values: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    height: int,
    width: int,
    transform: rasterio.Affine,
    tags: dict[str, str],
) -> None:
    array = np.full((height, width), NODATA, dtype=np.float32)
    valid = ~np.isnan(values)
    array[rows[valid], cols[valid]] = values[valid].astype(np.float32)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:3059",
        transform=transform,
        nodata=NODATA,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(array, 1)
        dst.update_tags(**tags)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one Latvia 1x1 km SSM GeoTIFF per H SAF satellite overpass, merging adjacent HSAF tiles."
    )
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--input-dir", default=str(RELEVANT_DIR))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--group-threshold-minutes", type=int, default=4)
    parser.add_argument("--include-empty", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    files = sorted(input_dir.glob("*.nc"))
    if not files:
        raise SystemExit(f"No NetCDF files found in {input_dir}. Run inspect_hsaf_order.py --extract-relevant first.")

    records = []
    for path in files:
        meta = parse_name(path)
        meta["path"] = path
        meta["start_dt"] = parse_ts(meta["sensing_start"])
        meta["end_dt"] = parse_ts(meta["sensing_end"])
        meta["created_dt"] = parse_ts(meta["created"])
        records.append(meta)
    groups = group_overpasses(records, args.group_threshold_minutes)

    grid = pd.read_csv(args.grid, usecols=["ID", "x", "y", "lon", "lat"], low_memory=False)
    xs, ys, transform = grid_geometry(grid)
    height = len(ys)
    width = len(xs)
    x_min = xs.min()
    y_max = ys.max()
    cols = np.rint((grid["x"].to_numpy() - x_min) / 1000).astype(int)
    rows = np.rint((y_max - grid["y"].to_numpy()) / 1000).astype(int)

    crs = hsaf_crs(files[0])
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    grid_x, grid_y = transformer.transform(grid["lon"].to_numpy(), grid["lat"].to_numpy())
    grid_x = np.asarray(grid_x)
    grid_y = np.asarray(grid_y)

    index_rows = []
    written = 0
    skipped = 0
    for group_no, group in enumerate(groups, start=1):
        value_sum = np.zeros(len(grid), dtype="float64")
        value_count = np.zeros(len(grid), dtype="uint16")
        for record in group:
            values, _inside = sample_file(record["path"], grid_x, grid_y)
            valid = ~np.isnan(values)
            value_sum[valid] += values[valid]
            value_count[valid] += 1

        valid = value_count > 0
        if not valid.any() and not args.include_empty:
            skipped += 1
            continue
        overpass_values = np.full(len(grid), np.nan, dtype="float64")
        overpass_values[valid] = value_sum[valid] / value_count[valid]

        start_dt = min(record["start_dt"] for record in group)
        end_dt = max(record["end_dt"] for record in group)
        created_dt = max(record["created_dt"] for record in group)
        sat = group[0]["sat"]
        date = group[0]["date"].replace("-", "")
        tiles = ",".join(sorted({record["tile"] for record in group}))
        output_name = f"hsaf_h28_{sat}_overpass_{start_dt:%Y%m%d%H%M%S}_{end_dt:%Y%m%d%H%M%S}_lv_1x1_ssm.tif"
        output = output_dir / date / output_name
        valid_values = overpass_values[valid]
        tags = {
            "product": "H SAF H28 ASCAT disaggregated surface soil moisture",
            "variable": "surface_soil_moisture",
            "units": "percent saturation",
            "satellite": sat,
            "tiles_merged": tiles,
            "source_file_count": str(len(group)),
            "sensing_start_utc": iso_z(start_dt),
            "sensing_end_utc": iso_z(end_dt),
            "created_utc": iso_z(created_dt),
            "valid_grid_cells": str(int(valid.sum())),
            "grid": "Latvia 1x1 km grid sampled to EPSG:3059",
            "aggregation": "single satellite overpass; adjacent HSAF tiles merged; overlaps averaged",
            "source_netcdfs": "|".join(str(record["path"]) for record in group),
        }
        write_tiff(output, overpass_values, rows, cols, height, width, transform, tags)
        written += 1
        index_rows.append(
            {
                "date": group[0]["date"],
                "satellite": sat,
                "sensing_start_utc": tags["sensing_start_utc"],
                "sensing_end_utc": tags["sensing_end_utc"],
                "created_utc": tags["created_utc"],
                "tiles_merged": tiles,
                "source_file_count": len(group),
                "valid_grid_cells": int(valid.sum()),
                "coverage_pct": int(valid.sum()) / len(grid) * 100,
                "min": float(np.nanmin(valid_values)) if valid_values.size else np.nan,
                "mean": float(np.nanmean(valid_values)) if valid_values.size else np.nan,
                "max": float(np.nanmax(valid_values)) if valid_values.size else np.nan,
                "output_tiff": str(output),
            }
        )
        print(f"{tags['sensing_start_utc']} {sat} {tiles}: {int(valid.sum())} cells -> {output.name}")

    index = pd.DataFrame(index_rows).sort_values(["date", "sensing_start_utc", "satellite"])
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "hsaf_h28_overpass_tiff_index.csv"
    index.to_csv(index_path, index=False)
    print(f"Overpass TIFFs written: {written}")
    print(f"Empty overpasses skipped: {skipped}")
    print(f"Index CSV: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
