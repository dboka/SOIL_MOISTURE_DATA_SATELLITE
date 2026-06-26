from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "clean_visuals"
HSAF_DIR = ROOT / "data" / "grid_tiffs" / "daily_mean_ssm"
COP_DIR = Path(r"C:\Users\deniss.boka\MESLI_PROJECT\COPERNICUS\data\grid_tiffs\daily_ssm")
DATES = ["20260615", "20260616", "20260617"]


def read_masked(path: Path) -> np.ma.MaskedArray:
    with rasterio.open(path) as src:
        return src.read(1, masked=True)


def save_single(path: Path, title: str, output: Path) -> None:
    arr = read_masked(path)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("white")
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    im = ax.imshow(arr, cmap=cmap, vmin=0, vmax=100, interpolation="nearest")
    ax.set_title(title)
    ax.axis("off")
    fig.colorbar(im, ax=ax, fraction=0.046, label="SSM (%)")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def save_compare(date: str, output: Path) -> None:
    hsaf_path = HSAF_DIR / f"hsaf_h28_lv_1x1_mean_ssm_{date}.tif"
    cop_path = COP_DIR / f"lv_1x1_ssm_{date}.tif"
    hsaf = read_masked(hsaf_path)
    cop = read_masked(cop_path)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("white")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for ax, arr, title in [
        (axes[0], hsaf, f"HSAF H28 {date}"),
        (axes[1], cop, f"Copernicus CLMS {date}"),
    ]:
        im = ax.imshow(arr, cmap=cmap, vmin=0, vmax=100, interpolation="nearest")
        ax.set_title(title)
        ax.axis("off")
    fig.colorbar(im, ax=axes, fraction=0.03, label="SSM (%)")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for date in DATES:
        save_single(
            HSAF_DIR / f"hsaf_h28_lv_1x1_mean_ssm_{date}.tif",
            f"HSAF H28 SSM {date}",
            OUT_DIR / f"hsaf_h28_ssm_{date}_clean.png",
        )
        save_single(
            COP_DIR / f"lv_1x1_ssm_{date}.tif",
            f"Copernicus CLMS SSM {date}",
            OUT_DIR / f"copernicus_clms_ssm_{date}_clean.png",
        )
        save_compare(date, OUT_DIR / f"compare_hsaf_copernicus_ssm_{date}.png")
    print(f"Clean visualizations written: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
