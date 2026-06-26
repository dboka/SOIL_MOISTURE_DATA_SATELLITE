from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from sample_hsaf_to_lv_grid import DEFAULT_GRID, RELEVANT_DIR, hsaf_crs, parse_name, sample_file


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "observation_tiffs"
NODATA = -9999.0


def grid_geometry(grid: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
    xs = np.sort(grid["x"].unique())
    ys = np.sort(grid["y"].unique())
    x_step = float(np.median(np.diff(xs)))
    y_step = float(np.median(np.diff(ys)))
    if not np.isclose(x_step, 1000) or not np.isclose(y_step, 1000):
        raise SystemExit(f"Expected 1000 m grid spacing, got x={x_step}, y={y_step}")
    transform = from_origin(xs.min() - x_step / 2, ys.max() + y_step / 2, x_step, y_step)
    return xs, ys, transform


def to_iso_utc(value: str) -> str:
    return (
        f"{value[0:4]}-{value[4:6]}-{value[6:8]}T"
        f"{value[8:10]}:{value[10:12]}:{value[12:14]}Z"
    )


def to_latvia_time(value: str) -> str:
    dt = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("Europe/Riga")).isoformat()


def write_observation_tiff(
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
        description="Create one EPSG:3059 Latvia 1x1 km SSM GeoTIFF per valid H SAF H28 observation."
    )
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--input-dir", default=str(RELEVANT_DIR))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--include-empty", action="store_true", help="Also write observations with 0 valid Latvia cells")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    files = sorted(input_dir.glob("*.nc"))
    if not files:
        raise SystemExit(f"No NetCDF files found in {input_dir}. Run inspect_hsaf_order.py --extract-relevant first.")

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
    skipped_empty = 0
    for path in files:
        meta = parse_name(path)
        values, inside = sample_file(path, grid_x, grid_y)
        valid = ~np.isnan(values)
        valid_count = int(valid.sum())
        if valid_count == 0 and not args.include_empty:
            skipped_empty += 1
            continue

        date_folder = meta["date"].replace("-", "")
        output_name = (
            f"hsaf_h28_{meta['sat']}_{meta['tile']}_"
            f"{meta['sensing_start']}_{meta['sensing_end']}_lv_1x1_ssm.tif"
        )
        output = output_dir / date_folder / output_name
        valid_values = values[valid]
        tags = {
            "product": "H SAF H28 ASCAT disaggregated surface soil moisture",
            "variable": "surface_soil_moisture",
            "units": "percent saturation",
            "satellite": meta["sat"],
            "tile": meta["tile"],
            "sensing_start_utc": to_iso_utc(meta["sensing_start"]),
            "sensing_end_utc": to_iso_utc(meta["sensing_end"]),
            "sensing_start_latvia_time": to_latvia_time(meta["sensing_start"]),
            "sensing_end_latvia_time": to_latvia_time(meta["sensing_end"]),
            "created_utc": to_iso_utc(meta["created"]),
            "source_netcdf": str(path),
            "valid_grid_cells": str(valid_count),
            "inside_tile_grid_cells": str(int(inside.sum())),
            "grid": "Latvia 1x1 km grid sampled to EPSG:3059",
            "aggregation": "single HSAF observation, no daily averaging",
        }
        write_observation_tiff(output, values, rows, cols, height, width, transform, tags)
        written += 1
        index_rows.append(
            {
                "date": meta["date"],
                "satellite": meta["sat"],
                "tile": meta["tile"],
                "sensing_start_utc": tags["sensing_start_utc"],
                "sensing_end_utc": tags["sensing_end_utc"],
                "sensing_start_latvia_time": tags["sensing_start_latvia_time"],
                "sensing_end_latvia_time": tags["sensing_end_latvia_time"],
                "created_utc": tags["created_utc"],
                "valid_grid_cells": valid_count,
                "coverage_pct": valid_count / len(grid) * 100,
                "min": float(np.nanmin(valid_values)) if valid_values.size else np.nan,
                "mean": float(np.nanmean(valid_values)) if valid_values.size else np.nan,
                "max": float(np.nanmax(valid_values)) if valid_values.size else np.nan,
                "output_tiff": str(output),
                "source_netcdf": str(path),
            }
        )
        print(f"{tags['sensing_start_utc']} {meta['sat']} {meta['tile']}: {valid_count} cells -> {output.name}")

    index = pd.DataFrame(index_rows).sort_values(["date", "sensing_start_utc", "satellite", "tile"])
    index_path = output_dir / "hsaf_h28_observation_tiff_index.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    index.to_csv(index_path, index=False)
    print(f"Observation TIFFs written: {written}")
    print(f"Empty observations skipped: {skipped_empty}")
    print(f"Index CSV: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
