from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parent
COUNT_DIR = ROOT / "data" / "grid_tiffs" / "daily_observation_count"
OUTPUT_DIR = ROOT / "data" / "grid_tiffs" / "daily_observation_count_float"
NODATA = -9999.0


def convert(path: Path) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / path.name.replace(".tif", "_float.tif")
    with rasterio.open(path) as src:
        masked = src.read(1, masked=True).astype("float32")
        array = masked.filled(NODATA)
        profile = src.profile.copy()
        profile.update(dtype="float32", nodata=NODATA, compress="deflate")
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(array, 1)
            dst.update_tags(**src.tags())
            dst.update_tags(description="QGIS-friendly float copy. Valid values are observation counts; nodata is -9999.")
    return output


def main() -> int:
    for path in sorted(COUNT_DIR.glob("*.tif")):
        output = convert(path)
        with rasterio.open(output) as src:
            valid = src.read(1, masked=True).compressed()
            print(f"{output}: min={valid.min()} max={valid.max()} valid_cells={valid.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
