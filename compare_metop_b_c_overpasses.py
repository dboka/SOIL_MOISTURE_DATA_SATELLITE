from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import rasterio


ROOTS = [
    Path(r"C:\Users\deniss.boka\MESLI_PROJECT\ASCAT_HSAF_ORDER2"),
    Path(r"C:\Users\deniss.boka\MESLI_PROJECT\ASCAT_HSAF_ORDER"),
]
OUT = Path(r"C:\Users\deniss.boka\MESLI_PROJECT\metop_b_c_comparison.csv")


def read_values(path: str) -> np.ma.MaskedArray:
    with rasterio.open(path) as src:
        return src.read(1, masked=True)


def local_time(row: pd.Series, column: str) -> str:
    if column in row.index and pd.notna(row[column]):
        return str(row[column])
    utc_col = column.replace("_latvia_time", "_utc")
    return pd.Timestamp(row[utc_col]).tz_convert(ZoneInfo("Europe/Riga")).isoformat()


def main() -> int:
    rows = []
    for root in ROOTS:
        idx_path = root / "data" / "clean_overpass_tiffs" / "hsaf_h28_clean_overpass_tiff_index.csv"
        idx = pd.read_csv(idx_path)
        idx["start"] = pd.to_datetime(idx["sensing_start_utc"])
        for date, group in idx.groupby("date"):
            b = group[group["satellite"] == "METOPB"].copy()
            c = group[group["satellite"] == "METOPC"].copy()
            for _, brow in b.iterrows():
                if c.empty:
                    continue
                c = c.assign(minutes_from_b=(c["start"] - brow["start"]).abs().dt.total_seconds() / 60)
                crow = c.sort_values("minutes_from_b").iloc[0]
                if crow["minutes_from_b"] > 45:
                    continue
                barr = read_values(brow["output_tiff"])
                carr = read_values(crow["output_tiff"])
                common = (~barr.mask) & (~carr.mask)
                if int(common.sum()) < 1000:
                    continue
                diff = barr.data[common].astype("float64") - carr.data[common].astype("float64")
                bvals = barr.data[common].astype("float64")
                cvals = carr.data[common].astype("float64")
                corr = np.corrcoef(bvals, cvals)[0, 1] if common.sum() > 2 else np.nan
                rows.append(
                    {
                        "order": root.name,
                        "date": date,
                        "metopb_start_utc": brow["sensing_start_utc"],
                        "metopb_start_latvia": local_time(brow, "sensing_start_latvia_time"),
                        "metopc_start_utc": crow["sensing_start_utc"],
                        "metopc_start_latvia": local_time(crow, "sensing_start_latvia_time"),
                        "minutes_between": float(crow["minutes_from_b"]),
                        "common_cells": int(common.sum()),
                        "metopb_mean": float(np.mean(bvals)),
                        "metopc_mean": float(np.mean(cvals)),
                        "bias_b_minus_c": float(np.mean(diff)),
                        "rmse": float(np.sqrt(np.mean(diff**2))),
                        "mae": float(np.mean(np.abs(diff))),
                        "corr": float(corr),
                        "metopb_tiff": brow["output_tiff"],
                        "metopc_tiff": crow["output_tiff"],
                    }
                )
    result = pd.DataFrame(rows).sort_values(["date", "metopb_start_utc"])
    result.to_csv(OUT, index=False)
    print(result.to_string(index=False))
    print(f"Written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
