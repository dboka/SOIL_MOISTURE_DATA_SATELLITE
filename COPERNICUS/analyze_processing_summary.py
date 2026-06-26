from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parent
SUMMARY_PATH = ROOT / "data" / "processed" / "processing_summary.csv"
OUTPUT_DIR = ROOT / "data" / "processed"


def main() -> int:
    if not SUMMARY_PATH.exists():
        raise SystemExit(f"Missing summary file: {SUMMARY_PATH}")

    df = pd.read_csv(SUMMARY_PATH, parse_dates=["date"])
    if "coverage_pct" not in df.columns:
        df["coverage_pct"] = df["valid_pixels"] / (df["width"] * df["height"]) * 100

    usable = df[df["valid_pixels"] > 0].copy()
    usable = usable.sort_values("date")
    df = df.sort_values("date")

    print(f"Days in summary: {len(df)}")
    print(f"Usable days with valid Latvia SSM pixels: {len(usable)}")
    if not usable.empty:
        best = usable.sort_values("coverage_pct", ascending=False).iloc[0]
        driest = usable.sort_values("mean", ascending=True).iloc[0]
        wettest = usable.sort_values("mean", ascending=False).iloc[0]
        print(
            "Best coverage: "
            f"{best['date'].date()} "
            f"coverage={best['coverage_pct']:.1f}% "
            f"mean={best['mean']:.1f}%"
        )
        print(
            "Lowest mean SSM: "
            f"{driest['date'].date()} "
            f"mean={driest['mean']:.1f}% "
            f"coverage={driest['coverage_pct']:.1f}%"
        )
        print(
            "Highest mean SSM: "
            f"{wettest['date'].date()} "
            f"mean={wettest['mean']:.1f}% "
            f"coverage={wettest['coverage_pct']:.1f}%"
        )

    stats_path = OUTPUT_DIR / "latvia_ssm_daily_stats.csv"
    columns = [
        "date",
        "valid_pixels",
        "coverage_pct",
        "min",
        "mean",
        "max",
        "product",
        "path",
    ]
    df[columns].to_csv(stats_path, index=False)

    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.plot(df["date"], df["mean"], marker="o", color="#1b7f5f", label="Mean SSM")
    ax1.set_ylabel("Mean SSM (%)")
    ax1.set_ylim(0, 100)
    ax1.grid(True, axis="y", alpha=0.3)

    ax2 = ax1.twinx()
    ax2.bar(df["date"], df["coverage_pct"], alpha=0.25, color="#3b6fb6", label="Coverage")
    ax2.set_ylabel("Latvia bbox coverage (%)")
    ax2.set_ylim(0, 100)

    ax1.set_title("Copernicus CLMS Surface Soil Moisture over Latvia bbox")
    ax1.set_xlabel("Date")
    fig.autofmt_xdate()
    fig.tight_layout()

    chart_path = OUTPUT_DIR / "latvia_ssm_daily_chart.png"
    fig.savefig(chart_path, dpi=160)
    plt.close(fig)

    print(f"Daily stats written: {stats_path}")
    print(f"Chart written: {chart_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
