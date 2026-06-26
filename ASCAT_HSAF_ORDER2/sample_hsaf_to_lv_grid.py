from __future__ import annotations

import argparse
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS, Transformer


ROOT = Path(__file__).resolve().parent
DEFAULT_GRID = Path(r"C:\Users\deniss.boka\MESLI_PROJECT\COPERNICUS\1x1_LV_grid_2024_xy2.csv")
RELEVANT_DIR = ROOT / "data" / "extracted_relevant"
OUT_DIR = ROOT / "data" / "grid"
NAME_RE = re.compile(
    r"ASCAT-(?P<sat>METOP[BC])-0\.5km-H28_.*?_LIIB_"
    r"(?P<created>\d{14})_(?P<sensing_start>\d{14})_(?P<sensing_end>\d{14})_EU_"
    r"(?P<tile>E\d{3}N\d{3})\.nc$"
)


def parse_name(path: Path) -> dict[str, str]:
    match = NAME_RE.search(path.name)
    if not match:
        raise ValueError(f"Unexpected HSAF file name: {path.name}")
    row = match.groupdict()
    row["date"] = f"{row['sensing_start'][:4]}-{row['sensing_start'][4:6]}-{row['sensing_start'][6:8]}"
    row["file"] = str(path)
    return row


def hsaf_crs(sample_path: Path) -> CRS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = xr.open_dataset(sample_path, decode_times=False)
    try:
        return CRS.from_wkt(ds["azimuthal_equidistant"].attrs["spatial_ref"])
    finally:
        ds.close()


def nearest_axis_indices(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
    ascending = axis[0] < axis[-1]
    search_axis = axis if ascending else axis[::-1]
    idx = np.searchsorted(search_axis, values)
    idx = np.clip(idx, 0, len(search_axis) - 1)
    prev_idx = np.clip(idx - 1, 0, len(search_axis) - 1)
    choose_prev = np.abs(values - search_axis[prev_idx]) < np.abs(values - search_axis[idx])
    idx[choose_prev] = prev_idx[choose_prev]
    if ascending:
        return idx
    return len(axis) - 1 - idx


def sample_file(path: Path, grid_x: np.ndarray, grid_y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = xr.open_dataset(path, decode_times=False)
    try:
        xs = ds["x"].values
        ys = ds["y"].values
        inside = (
            (grid_x >= xs.min())
            & (grid_x <= xs.max())
            & (grid_y >= ys.min())
            & (grid_y <= ys.max())
        )
        values = np.full(grid_x.shape, np.nan, dtype="float64")
        if not inside.any():
            return values, inside

        # Nearest neighbour on the 500 m HSAF grid. HSAF y is descending.
        x_idx = nearest_axis_indices(xs, grid_x[inside])
        y_idx = nearest_axis_indices(ys, grid_y[inside])

        ssm = ds["surface_soil_moisture"].isel(time=0).values
        sampled = ssm[y_idx, x_idx].astype("float64")
        sampled[(sampled < 0) | (sampled > 100)] = np.nan
        values[np.where(inside)[0]] = sampled
        return values, inside
    finally:
        ds.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample extracted H SAF H28 ASCAT SSM files to Latvia 1x1 km grid.")
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--input-dir", default=str(RELEVANT_DIR))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(input_dir.glob("*.nc"))
    if not files:
        raise SystemExit(f"No NetCDF files found in {input_dir}. Run inspect_hsaf_order.py --extract-relevant first.")

    grid = pd.read_csv(args.grid, usecols=["ID", "lon", "lat"], low_memory=False)
    crs = hsaf_crs(files[0])
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    grid_x, grid_y = transformer.transform(grid["lon"].to_numpy(), grid["lat"].to_numpy())
    grid_x = np.asarray(grid_x)
    grid_y = np.asarray(grid_y)

    daily_sum: dict[str, np.ndarray] = {}
    daily_count: dict[str, np.ndarray] = {}
    file_rows = []

    for path in files:
        meta = parse_name(path)
        values, inside = sample_file(path, grid_x, grid_y)
        valid = ~np.isnan(values)
        date = meta["date"]
        daily_sum.setdefault(date, np.zeros(len(grid), dtype="float64"))
        daily_count.setdefault(date, np.zeros(len(grid), dtype="uint16"))
        daily_sum[date][valid] += values[valid]
        daily_count[date][valid] += 1

        valid_values = values[valid]
        file_rows.append(
            {
                **meta,
                "inside_tile_grid_cells": int(inside.sum()),
                "valid_grid_cells": int(valid.sum()),
                "coverage_pct": float(valid.mean() * 100),
                "min": float(np.nanmin(valid_values)) if valid_values.size else np.nan,
                "mean": float(np.nanmean(valid_values)) if valid_values.size else np.nan,
                "max": float(np.nanmax(valid_values)) if valid_values.size else np.nan,
            }
        )
        print(f"{date} {meta['sat']} {meta['tile']}: {valid.sum()} valid cells")

    daily_rows = []
    wide = grid[["ID", "lon", "lat"]].copy()
    for date in sorted(daily_count):
        count = daily_count[date]
        valid = count > 0
        mean = np.full(len(grid), np.nan, dtype="float64")
        mean[valid] = daily_sum[date][valid] / count[valid]
        wide[f"hsaf_ssm_{date.replace('-', '')}"] = mean
        vals = mean[valid]
        daily_rows.append(
            {
                "date": date,
                "grid_cells": len(grid),
                "valid_grid_cells": int(valid.sum()),
                "coverage_pct": float(valid.mean() * 100),
                "mean_observations_per_valid_cell": float(count[valid].mean()) if valid.any() else np.nan,
                "min": float(np.nanmin(vals)) if vals.size else np.nan,
                "mean": float(np.nanmean(vals)) if vals.size else np.nan,
                "max": float(np.nanmax(vals)) if vals.size else np.nan,
            }
        )

    file_stats_path = output_dir / "hsaf_h28_lv_grid_file_coverage.csv"
    daily_stats_path = output_dir / "hsaf_h28_lv_grid_daily_coverage.csv"
    wide_path = output_dir / "hsaf_h28_lv_grid_daily_mean_wide.csv"
    pd.DataFrame(file_rows).to_csv(file_stats_path, index=False)
    pd.DataFrame(daily_rows).to_csv(daily_stats_path, index=False)
    wide.to_csv(wide_path, index=False)

    print(f"File coverage CSV: {file_stats_path}")
    print(f"Daily coverage CSV: {daily_stats_path}")
    print(f"Wide daily mean CSV: {wide_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
