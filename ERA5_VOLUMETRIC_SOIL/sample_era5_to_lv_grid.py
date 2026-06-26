from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio


ROOT = Path(__file__).resolve().parent
GRID_PATH = ROOT.parent / "COPERNICUS" / "1x1_LV_grid_2024_xy2.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "data" / "grid"
DATE_RE = re.compile(r"era5_land_(?P<variable>[a-z0-9]+)_(?P<date>\d{8})_latvia\.tif$")


def raster_info(path: Path) -> tuple[str, str]:
    match = DATE_RE.search(path.name)
    if not match:
        raise ValueError(f"Could not parse variable/date from raster name: {path.name}")
    value = match.group("date")
    return match.group("variable"), f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def sample_raster(path: Path, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    coords = list(zip(lon, lat))
    with rasterio.open(path) as src:
        values = np.fromiter((sample[0] for sample in src.sample(coords)), dtype="float64")
        nodata = src.nodata
        if nodata is not None:
            values[values == nodata] = np.nan
        values[(values < 0) | (values > 100)] = np.nan
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample processed ERA5-Land Latvia rasters to the 1x1 km Latvia grid."
    )
    parser.add_argument("--grid", default=str(GRID_PATH), help="Input grid CSV with lon/lat columns")
    parser.add_argument("--rasters", default=str(PROCESSED_DIR / "era5_land_swvl1_*_latvia.tif"))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--base-columns",
        default="ID,x,y,lon,lat,Lakes_ha,River_ha,Water_perc,Sea_area,Forest_ha,Bogs_ha,Population,Stations",
        help="Comma-separated grid columns to keep in the wide output",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    grid = pd.read_csv(args.grid, low_memory=False)
    if "lon" not in grid.columns or "lat" not in grid.columns:
        raise SystemExit("Grid CSV must contain lon and lat columns.")

    raster_pattern = Path(args.rasters)
    rasters = sorted(
        raster_pattern.parent.glob(raster_pattern.name)
        if raster_pattern.is_absolute()
        else Path().glob(args.rasters)
    )
    if not rasters:
        raise SystemExit(f"No rasters found for pattern: {args.rasters}")

    base_columns = [col.strip() for col in args.base_columns.split(",") if col.strip()]
    base_columns = [col for col in base_columns if col in grid.columns]
    wide = grid[base_columns].copy()
    lon = grid["lon"].to_numpy(dtype="float64")
    lat = grid["lat"].to_numpy(dtype="float64")

    stats_rows = []
    valid_long_parts = []
    for raster_path in rasters:
        variable, date_text = raster_info(raster_path)
        column = f"era5_{variable}_pct_{date_text.replace('-', '')}"
        values = sample_raster(raster_path, lon, lat)
        wide[column] = values

        valid_mask = ~np.isnan(values)
        valid_values = values[valid_mask]
        stats_rows.append(
            {
                "date": date_text,
                "variable": variable,
                "raster": str(raster_path),
                "grid_cells": int(len(values)),
                "valid_grid_cells": int(valid_mask.sum()),
                "coverage_pct": float(valid_mask.mean() * 100),
                "min": float(np.min(valid_values)) if valid_values.size else np.nan,
                "mean": float(np.mean(valid_values)) if valid_values.size else np.nan,
                "max": float(np.max(valid_values)) if valid_values.size else np.nan,
            }
        )

        if valid_mask.any():
            valid_long_parts.append(
                pd.DataFrame(
                    {
                        "date": date_text,
                        "variable": variable,
                        "ID": grid.loc[valid_mask, "ID"].to_numpy(),
                        "lon": lon[valid_mask],
                        "lat": lat[valid_mask],
                        "era5_soil_water_pct": valid_values,
                    }
                )
            )
        print(f"{date_text} {variable}: valid grid cells {valid_mask.sum()} / {len(values)}")

    stats = pd.DataFrame(stats_rows).sort_values(["variable", "date"])
    variable_suffix = stats["variable"].iloc[0] if stats["variable"].nunique() == 1 else "soil"
    wide_path = output_dir / f"lv_1x1_grid_era5_{variable_suffix}_wide.csv"
    stats_path = output_dir / f"lv_1x1_grid_era5_{variable_suffix}_daily_coverage.csv"
    long_path = output_dir / f"lv_1x1_grid_era5_{variable_suffix}_valid_long.csv"

    wide.to_csv(wide_path, index=False)
    stats.to_csv(stats_path, index=False)
    if valid_long_parts:
        pd.concat(valid_long_parts, ignore_index=True).to_csv(long_path, index=False)
    else:
        pd.DataFrame(
            columns=["date", "variable", "ID", "lon", "lat", "era5_soil_water_pct"]
        ).to_csv(long_path, index=False)

    print(f"Wide grid output written: {wide_path}")
    print(f"Daily coverage output written: {stats_path}")
    print(f"Valid long output written: {long_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
