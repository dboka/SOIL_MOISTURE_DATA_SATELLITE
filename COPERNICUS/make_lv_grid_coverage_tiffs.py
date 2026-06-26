from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parent
GRID_PATH = ROOT / "1x1_LV_grid_2024_xy2.csv"
EXTRACTED_DIR = ROOT / "data" / "extracted"
OUTPUT_DIR = ROOT / "data" / "grid_tiffs"
DATE_RE = re.compile(r"_(\d{8})0000_")
SSM_NODATA = -9999.0
COUNT_NODATA = 65535


def raster_date(path: Path) -> str:
    match = DATE_RE.search(path.name)
    if not match:
        raise ValueError(f"Could not parse date from raster name: {path.name}")
    value = match.group(1)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def find_ssm_rasters(extracted_dir: Path) -> list[Path]:
    rasters = sorted(
        path
        for path in extracted_dir.rglob("*.tif*")
        if "-SSM_" in path.name and path.name.lower().endswith((".tif", ".tiff"))
    )
    if not rasters:
        raise SystemExit(f"No extracted SSM rasters found under: {extracted_dir}")
    return rasters


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


def sample_ssm(path: Path, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    coords = list(zip(lon, lat))
    with rasterio.open(path) as src:
        raw = np.fromiter((sample[0] for sample in src.sample(coords)), dtype="float64")
        nodata = src.nodata
        if nodata is not None:
            raw[raw == nodata] = np.nan
        raw[(raw < 0) | (raw > 200)] = np.nan
        scale = src.scales[0] if src.scales and src.scales[0] else 1.0
        offset = src.offsets[0] if src.offsets and src.offsets[0] else 0.0
        return raw * scale + offset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create EPSG:3059 GeoTIFFs for CLMS SSM sampled to the Latvia 1x1 km grid."
    )
    parser.add_argument("--grid", default=str(GRID_PATH))
    parser.add_argument("--extracted-dir", default=str(EXTRACTED_DIR))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--skip-daily", action="store_true", help="Only write aggregate coverage TIFFs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    grid = pd.read_csv(args.grid, usecols=["ID", "x", "y", "lon", "lat"], low_memory=False)
    xs, ys, transform = grid_geometry(grid)
    height = len(ys)
    width = len(xs)
    x_min = xs.min()
    y_max = ys.max()

    cols = np.rint((grid["x"].to_numpy() - x_min) / 1000).astype(int)
    rows = np.rint((y_max - grid["y"].to_numpy()) / 1000).astype(int)
    lon = grid["lon"].to_numpy(dtype="float64")
    lat = grid["lat"].to_numpy(dtype="float64")
    grid_mask = np.zeros((height, width), dtype=bool)
    grid_mask[rows, cols] = True

    rasters = find_ssm_rasters(Path(args.extracted_dir))
    valid_count = np.zeros((height, width), dtype=np.uint16)
    ssm_sum = np.zeros((height, width), dtype=np.float64)
    stats_rows = []

    daily_dir = output_dir / "daily_ssm"
    for raster_path in rasters:
        date = raster_date(raster_path)
        values = sample_ssm(raster_path, lon, lat)
        valid = ~np.isnan(values)

        daily = np.full((height, width), SSM_NODATA, dtype=np.float32)
        daily_values = np.where(valid, values, SSM_NODATA).astype(np.float32)
        daily[rows, cols] = daily_values

        if not args.skip_daily:
            write_tiff(
                daily_dir / f"lv_1x1_ssm_{date.replace('-', '')}.tif",
                daily,
                transform,
                "float32",
                SSM_NODATA,
                {
                    "date": date,
                    "units": "%",
                    "source": str(raster_path),
                    "description": "CLMS Surface Soil Moisture sampled to Latvia 1x1 km grid",
                },
            )

        valid_cells = np.zeros((height, width), dtype=bool)
        valid_cells[rows[valid], cols[valid]] = True
        valid_count[valid_cells] += 1
        ssm_sum[valid_cells] += values[valid]

        valid_values = values[valid]
        stats_rows.append(
            {
                "date": date,
                "valid_grid_cells": int(valid.sum()),
                "grid_cells": int(len(grid)),
                "coverage_pct": float(valid.mean() * 100),
                "min": float(np.nanmin(valid_values)) if valid_values.size else np.nan,
                "mean": float(np.nanmean(valid_values)) if valid_values.size else np.nan,
                "max": float(np.nanmax(valid_values)) if valid_values.size else np.nan,
                "source": str(raster_path),
            }
        )
        print(f"{date}: {valid.sum()} / {len(grid)} valid grid cells")

    count_array = np.full((height, width), COUNT_NODATA, dtype=np.uint16)
    count_array[grid_mask] = valid_count[grid_mask]
    pct_array = np.full((height, width), SSM_NODATA, dtype=np.float32)
    pct_array[grid_mask] = valid_count[grid_mask].astype("float32") / len(rasters) * 100
    mean_array = np.full((height, width), SSM_NODATA, dtype=np.float32)
    has_valid = grid_mask & (valid_count > 0)
    mean_array[has_valid] = (ssm_sum[has_valid] / valid_count[has_valid]).astype(np.float32)

    write_tiff(
        output_dir / "lv_1x1_valid_coverage_count.tif",
        count_array,
        transform,
        "uint16",
        COUNT_NODATA,
        {
            "units": "days",
            "total_days": str(len(rasters)),
            "description": "Number of days with valid CLMS SSM values per Latvia 1x1 km grid cell",
        },
    )
    write_tiff(
        output_dir / "lv_1x1_valid_coverage_pct.tif",
        pct_array,
        transform,
        "float32",
        SSM_NODATA,
        {
            "units": "%",
            "total_days": str(len(rasters)),
            "description": "Percent of days with valid CLMS SSM values per Latvia 1x1 km grid cell",
        },
    )
    write_tiff(
        output_dir / "lv_1x1_mean_ssm_pct.tif",
        mean_array,
        transform,
        "float32",
        SSM_NODATA,
        {
            "units": "%",
            "total_days": str(len(rasters)),
            "description": "Mean valid CLMS SSM percent per Latvia 1x1 km grid cell",
        },
    )

    stats = pd.DataFrame(stats_rows).sort_values("date")
    stats_path = output_dir / "lv_1x1_grid_tiff_daily_coverage.csv"
    stats.to_csv(stats_path, index=False)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    coverage_plot = np.ma.masked_equal(pct_array, SSM_NODATA)
    mean_plot = np.ma.masked_equal(mean_array, SSM_NODATA)
    im0 = axes[0].imshow(coverage_plot, cmap="viridis", vmin=0, vmax=100)
    axes[0].set_title("Valid SSM coverage (%)")
    axes[0].axis("off")
    fig.colorbar(im0, ax=axes[0], fraction=0.046)
    im1 = axes[1].imshow(mean_plot, cmap="YlGnBu", vmin=0, vmax=100)
    axes[1].set_title("Mean valid SSM (%)")
    axes[1].axis("off")
    fig.colorbar(im1, ax=axes[1], fraction=0.046)
    quicklook_path = output_dir / "lv_1x1_coverage_quicklook.png"
    fig.savefig(quicklook_path, dpi=170)
    plt.close(fig)

    print(f"Coverage count TIFF: {output_dir / 'lv_1x1_valid_coverage_count.tif'}")
    print(f"Coverage percent TIFF: {output_dir / 'lv_1x1_valid_coverage_pct.tif'}")
    print(f"Mean SSM TIFF: {output_dir / 'lv_1x1_mean_ssm_pct.tif'}")
    print(f"Daily SSM TIFF folder: {daily_dir}")
    print(f"Daily stats CSV: {stats_path}")
    print(f"Quicklook PNG: {quicklook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
