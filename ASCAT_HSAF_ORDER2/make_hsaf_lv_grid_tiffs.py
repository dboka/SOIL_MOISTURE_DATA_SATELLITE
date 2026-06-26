from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from sample_hsaf_to_lv_grid import DEFAULT_GRID, RELEVANT_DIR, hsaf_crs, parse_name, sample_file


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "grid_tiffs"
SSM_NODATA = -9999.0
COUNT_NODATA = 65535


def grid_geometry(grid: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
    xs = np.sort(grid["x"].unique())
    ys = np.sort(grid["y"].unique())
    x_step = float(np.median(np.diff(xs)))
    y_step = float(np.median(np.diff(ys)))
    if not np.isclose(x_step, 1000) or not np.isclose(y_step, 1000):
        raise SystemExit(f"Expected 1000 m grid spacing, got x={x_step}, y={y_step}")
    transform = from_origin(xs.min() - x_step / 2, ys.max() + y_step / 2, x_step, y_step)
    return xs, ys, transform


def write_tiff(
    path: Path,
    array: np.ndarray,
    transform: rasterio.Affine,
    dtype: str,
    nodata: float | int,
    tags: dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:3059",
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(array.astype(dtype), 1)
        dst.update_tags(**tags)


def points_to_array(
    values: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    height: int,
    width: int,
    nodata: float = SSM_NODATA,
) -> np.ndarray:
    array = np.full((height, width), nodata, dtype=np.float32)
    valid_values = np.where(np.isnan(values), nodata, values).astype(np.float32)
    array[rows, cols] = valid_values
    return array


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create EPSG:3059 GeoTIFFs for H SAF H28 ASCAT SSM sampled to Latvia 1x1 km grid."
    )
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--input-dir", default=str(RELEVANT_DIR))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
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
    grid_mask = np.zeros((height, width), dtype=bool)
    grid_mask[rows, cols] = True

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

    daily_dir = output_dir / "daily_mean_ssm"
    daily_count_dir = output_dir / "daily_observation_count"
    daily_rows = []
    aggregate_valid_count = np.zeros((height, width), dtype=np.uint16)
    aggregate_sum = np.zeros((height, width), dtype=np.float64)

    for date in sorted(daily_count):
        count = daily_count[date]
        valid = count > 0
        mean = np.full(len(grid), np.nan, dtype="float64")
        mean[valid] = daily_sum[date][valid] / count[valid]
        mean_array = points_to_array(mean, rows, cols, height, width)

        count_array = np.full((height, width), COUNT_NODATA, dtype=np.uint16)
        count_array[rows[valid], cols[valid]] = count[valid]

        write_tiff(
            daily_dir / f"hsaf_h28_lv_1x1_mean_ssm_{date.replace('-', '')}.tif",
            mean_array,
            transform,
            "float32",
            SSM_NODATA,
            {
                "date": date,
                "units": "percent saturation",
                "description": "H SAF H28 ASCAT daily mean SSM sampled to Latvia 1x1 km grid",
            },
        )
        write_tiff(
            daily_count_dir / f"hsaf_h28_lv_1x1_observation_count_{date.replace('-', '')}.tif",
            count_array,
            transform,
            "uint16",
            COUNT_NODATA,
            {
                "date": date,
                "units": "observations",
                "description": "QA layer: number of valid H SAF H28 ASCAT observations per Latvia 1x1 km grid cell",
            },
        )

        valid_array = np.zeros((height, width), dtype=bool)
        valid_array[rows[valid], cols[valid]] = True
        aggregate_valid_count[valid_array] += 1
        aggregate_sum[valid_array] += mean[valid]

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

    total_days = len(daily_count)
    coverage_count = np.full((height, width), COUNT_NODATA, dtype=np.uint16)
    coverage_count[grid_mask] = aggregate_valid_count[grid_mask]
    coverage_pct = np.full((height, width), SSM_NODATA, dtype=np.float32)
    coverage_pct[grid_mask] = aggregate_valid_count[grid_mask].astype("float32") / total_days * 100
    aggregate_mean = np.full((height, width), SSM_NODATA, dtype=np.float32)
    has_valid = grid_mask & (aggregate_valid_count > 0)
    aggregate_mean[has_valid] = (aggregate_sum[has_valid] / aggregate_valid_count[has_valid]).astype(np.float32)

    write_tiff(
        output_dir / "hsaf_h28_lv_1x1_valid_coverage_count.tif",
        coverage_count,
        transform,
        "uint16",
        COUNT_NODATA,
        {
            "units": "days",
            "total_days": str(total_days),
            "description": "Number of days with valid H SAF H28 ASCAT SSM per Latvia 1x1 km grid cell",
        },
    )
    write_tiff(
        output_dir / "hsaf_h28_lv_1x1_valid_coverage_pct.tif",
        coverage_pct,
        transform,
        "float32",
        SSM_NODATA,
        {
            "units": "%",
            "total_days": str(total_days),
            "description": "Percent of days with valid H SAF H28 ASCAT SSM per Latvia 1x1 km grid cell",
        },
    )
    write_tiff(
        output_dir / "hsaf_h28_lv_1x1_mean_ssm_pct.tif",
        aggregate_mean,
        transform,
        "float32",
        SSM_NODATA,
        {
            "units": "percent saturation",
            "total_days": str(total_days),
            "description": "Mean valid H SAF H28 ASCAT SSM per Latvia 1x1 km grid cell",
        },
    )

    pd.DataFrame(file_rows).to_csv(output_dir / "hsaf_h28_lv_grid_file_coverage.csv", index=False)
    pd.DataFrame(daily_rows).to_csv(output_dir / "hsaf_h28_lv_grid_daily_coverage.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    im0 = axes[0].imshow(np.ma.masked_equal(coverage_pct, SSM_NODATA), cmap="viridis", vmin=0, vmax=100)
    axes[0].set_title("H SAF valid coverage (%)")
    axes[0].axis("off")
    fig.colorbar(im0, ax=axes[0], fraction=0.046)
    im1 = axes[1].imshow(np.ma.masked_equal(aggregate_mean, SSM_NODATA), cmap="YlGnBu", vmin=0, vmax=100)
    axes[1].set_title("H SAF mean SSM (%)")
    axes[1].axis("off")
    fig.colorbar(im1, ax=axes[1], fraction=0.046)
    quicklook_path = output_dir / "hsaf_h28_lv_1x1_quicklook.png"
    fig.savefig(quicklook_path, dpi=170)
    plt.close(fig)

    print(f"Daily mean SSM TIFFs: {daily_dir}")
    print(f"Daily observation count TIFFs: {daily_count_dir}")
    print(f"Coverage count TIFF: {output_dir / 'hsaf_h28_lv_1x1_valid_coverage_count.tif'}")
    print(f"Coverage percent TIFF: {output_dir / 'hsaf_h28_lv_1x1_valid_coverage_pct.tif'}")
    print(f"Mean SSM TIFF: {output_dir / 'hsaf_h28_lv_1x1_mean_ssm_pct.tif'}")
    print(f"Quicklook PNG: {quicklook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
