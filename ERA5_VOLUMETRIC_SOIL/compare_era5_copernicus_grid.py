from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_COPERNICUS = ROOT.parent / "COPERNICUS" / "data" / "grid" / "lv_1x1_grid_ssm_valid_long.csv"
DEFAULT_ERA5 = ROOT / "data" / "grid" / "lv_1x1_grid_era5_swvl1_valid_long.csv"
OUTPUT_DIR = ROOT / "data" / "comparison"


def daily_metrics(group: pd.DataFrame) -> pd.Series:
    diff = group["era5_soil_water_pct"] - group["ssm_pct"]
    return pd.Series(
        {
            "matched_grid_cells": int(len(group)),
            "copernicus_mean_pct": float(group["ssm_pct"].mean()),
            "era5_mean_pct": float(group["era5_soil_water_pct"].mean()),
            "bias_era5_minus_copernicus_pct": float(diff.mean()),
            "mae_pct": float(diff.abs().mean()),
            "rmse_pct": float(np.sqrt(np.mean(np.square(diff)))),
            "correlation": float(group["era5_soil_water_pct"].corr(group["ssm_pct"]))
            if len(group) > 1
            else np.nan,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Copernicus SSM and ERA5-Land swvl1 on the Latvia 1x1 km grid."
    )
    parser.add_argument("--copernicus-long", default=str(DEFAULT_COPERNICUS))
    parser.add_argument("--era5-long", default=str(DEFAULT_ERA5))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    copernicus = pd.read_csv(args.copernicus_long)
    era5 = pd.read_csv(args.era5_long)

    required_copernicus = {"date", "ID", "lon", "lat", "ssm_pct"}
    required_era5 = {"date", "ID", "era5_soil_water_pct"}
    missing_copernicus = required_copernicus - set(copernicus.columns)
    missing_era5 = required_era5 - set(era5.columns)
    if missing_copernicus:
        raise SystemExit(f"Missing Copernicus columns: {sorted(missing_copernicus)}")
    if missing_era5:
        raise SystemExit(f"Missing ERA5 columns: {sorted(missing_era5)}")

    merged = copernicus.merge(
        era5[["date", "ID", "era5_soil_water_pct"]],
        on=["date", "ID"],
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise SystemExit("No overlapping date/ID grid cells found between Copernicus and ERA5.")

    merged["era5_minus_copernicus_pct"] = merged["era5_soil_water_pct"] - merged["ssm_pct"]
    daily_rows = []
    for date_text, group in merged.groupby("date", sort=True):
        metrics = daily_metrics(group)
        metrics["date"] = date_text
        daily_rows.append(metrics)
    daily = pd.DataFrame(daily_rows)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = output_dir / "era5_copernicus_swvl1_grid_comparison.csv"
    daily_path = output_dir / "era5_copernicus_swvl1_daily_metrics.csv"
    merged.to_csv(merged_path, index=False)
    daily.to_csv(daily_path, index=False)

    print(f"Matched rows: {len(merged)}")
    print(f"Comparison output written: {merged_path}")
    print(f"Daily metrics written: {daily_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
