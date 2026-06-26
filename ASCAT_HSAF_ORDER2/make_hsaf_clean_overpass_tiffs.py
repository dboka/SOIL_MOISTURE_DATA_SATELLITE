from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from make_hsaf_overpass_tiffs import (
    NODATA,
    OUT_DIR as RAW_OVERPASS_DIR,
    grid_geometry,
    group_overpasses,
    iso_z,
    latvia_time,
    parse_ts,
    write_tiff,
)
from sample_hsaf_to_lv_grid import DEFAULT_GRID, RELEVANT_DIR, hsaf_crs, parse_name, sample_file


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "clean_overpass_tiffs"


def grid_neighbor_count(valid_grid: np.ndarray) -> np.ndarray:
    padded = np.pad(valid_grid.astype("uint8"), 1, mode="constant", constant_values=0)
    total = np.zeros(valid_grid.shape, dtype="uint8")
    for dr in range(3):
        for dc in range(3):
            total += padded[dr : dr + valid_grid.shape[0], dc : dc + valid_grid.shape[1]]
    return total


def tile_seam_mask(grid_x: np.ndarray, grid_y: np.ndarray, buffer_m: float) -> np.ndarray:
    mask = np.zeros(grid_x.shape, dtype=bool)
    for values in [grid_x, grid_y]:
        start = int(np.floor(values.min() / 600000.0) * 600000)
        end = int(np.ceil(values.max() / 600000.0) * 600000)
        for boundary in range(start, end + 1, 600000):
            mask |= np.abs(values - boundary) <= buffer_m
    return mask


def write_quicklook(tiff_path: Path, png_path: Path, title: str) -> None:
    with rasterio.open(tiff_path) as src:
        array = src.read(1, masked=True)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("white")
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    image = ax.imshow(array, cmap=cmap, vmin=0, vmax=100, interpolation="nearest")
    ax.set_title(title)
    ax.axis("off")
    fig.colorbar(image, ax=ax, fraction=0.046, label="SSM (%)")
    fig.savefig(png_path, dpi=170)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create cleaned H SAF H28 overpass TIFFs by masking tile seams and sparse swath-edge cells."
    )
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--input-dir", default=str(RELEVANT_DIR))
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--group-threshold-minutes", type=int, default=4)
    parser.add_argument("--tile-seam-buffer-m", type=float, default=1500.0)
    parser.add_argument("--min-neighbors-3x3", type=int, default=5)
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
    seam_mask = tile_seam_mask(grid_x, grid_y, args.tile_seam_buffer_m)

    index_rows = []
    quicklook_dir = output_dir / "quicklooks"
    for group in groups:
        value_sum = np.zeros(len(grid), dtype="float64")
        value_count = np.zeros(len(grid), dtype="uint16")
        for record in group:
            values, _inside = sample_file(record["path"], grid_x, grid_y)
            valid = ~np.isnan(values)
            value_sum[valid] += values[valid]
            value_count[valid] += 1

        raw_valid = value_count > 0
        if not raw_valid.any():
            continue
        values = np.full(len(grid), np.nan, dtype="float64")
        values[raw_valid] = value_sum[raw_valid] / value_count[raw_valid]

        valid_grid = np.zeros((height, width), dtype=bool)
        valid_grid[rows[raw_valid], cols[raw_valid]] = True
        support = grid_neighbor_count(valid_grid)
        point_support = support[rows, cols]
        clean_valid = raw_valid & ~seam_mask & (point_support >= args.min_neighbors_3x3)
        clean_values = values.copy()
        clean_values[~clean_valid] = np.nan
        if not clean_valid.any():
            continue

        start_dt = min(record["start_dt"] for record in group)
        end_dt = max(record["end_dt"] for record in group)
        created_dt = max(record["created_dt"] for record in group)
        sat = group[0]["sat"]
        date = group[0]["date"].replace("-", "")
        tiles = ",".join(sorted({record["tile"] for record in group}))
        output_name = f"hsaf_h28_{sat}_clean_overpass_{start_dt:%Y%m%d%H%M%S}_{end_dt:%Y%m%d%H%M%S}_lv_1x1_ssm.tif"
        output = output_dir / date / output_name
        tags = {
            "product": "H SAF H28 ASCAT disaggregated surface soil moisture",
            "variable": "surface_soil_moisture",
            "units": "percent saturation",
            "satellite": sat,
            "tiles_merged": tiles,
            "source_file_count": str(len(group)),
            "sensing_start_utc": iso_z(start_dt),
            "sensing_end_utc": iso_z(end_dt),
            "sensing_start_latvia_time": latvia_time(start_dt),
            "sensing_end_latvia_time": latvia_time(end_dt),
            "created_utc": iso_z(created_dt),
            "raw_valid_grid_cells": str(int(raw_valid.sum())),
            "clean_valid_grid_cells": str(int(clean_valid.sum())),
            "masked_grid_cells": str(int(raw_valid.sum() - clean_valid.sum())),
            "tile_seam_buffer_m": str(args.tile_seam_buffer_m),
            "min_neighbors_3x3": str(args.min_neighbors_3x3),
            "grid": "Latvia 1x1 km grid sampled to EPSG:3059",
            "aggregation": "single satellite overpass; adjacent HSAF tiles merged; overlaps averaged; seam/edge cells masked",
            "source_netcdfs": "|".join(str(record["path"]) for record in group),
        }
        write_tiff(output, clean_values, rows, cols, height, width, transform, tags)

        clean_vals = clean_values[clean_valid]
        index_rows.append(
            {
                "date": group[0]["date"],
                "satellite": sat,
                "sensing_start_utc": tags["sensing_start_utc"],
                "sensing_end_utc": tags["sensing_end_utc"],
                "sensing_start_latvia_time": tags["sensing_start_latvia_time"],
                "sensing_end_latvia_time": tags["sensing_end_latvia_time"],
                "tiles_merged": tiles,
                "source_file_count": len(group),
                "raw_valid_grid_cells": int(raw_valid.sum()),
                "clean_valid_grid_cells": int(clean_valid.sum()),
                "masked_grid_cells": int(raw_valid.sum() - clean_valid.sum()),
                "clean_coverage_pct": int(clean_valid.sum()) / len(grid) * 100,
                "min": float(np.nanmin(clean_vals)),
                "mean": float(np.nanmean(clean_vals)),
                "max": float(np.nanmax(clean_vals)),
                "output_tiff": str(output),
                "raw_overpass_dir": str(RAW_OVERPASS_DIR),
            }
        )
        quicklook_dir.mkdir(parents=True, exist_ok=True)
        write_quicklook(output, quicklook_dir / output_name.replace(".tif", ".png"), f"{sat} clean {iso_z(start_dt)}")
        print(
            f"{iso_z(start_dt)} {sat}: raw={raw_valid.sum()} clean={clean_valid.sum()} "
            f"masked={raw_valid.sum() - clean_valid.sum()} -> {output.name}"
        )

    index = pd.DataFrame(index_rows).sort_values(["date", "sensing_start_utc", "satellite"])
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "hsaf_h28_clean_overpass_tiff_index.csv"
    index.to_csv(index_path, index=False)
    print(f"Clean overpass TIFFs written: {len(index)}")
    print(f"Index CSV: {index_path}")
    print(f"Quicklooks: {quicklook_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
