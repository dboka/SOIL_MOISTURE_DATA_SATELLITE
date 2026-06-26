from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.fill import fillnodata


ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "data" / "clean_overpass_tiffs"
OUTPUT_DIR = ROOT / "data" / "visual_filled_overpass_tiffs"
GRID_MASK_TIFF = Path(r"C:\Users\deniss.boka\MESLI_PROJECT\COPERNICUS\data\grid_tiffs\lv_1x1_valid_coverage_pct.tif")
NODATA = -9999.0


def fill_visual(path: Path, grid_mask: np.ndarray) -> Path:
    relative = path.relative_to(INPUT_DIR)
    output = OUTPUT_DIR / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path) as src:
        array = src.read(1).astype("float32")
        valid_mask = array != src.nodata
        filled = fillnodata(
            array,
            mask=valid_mask.astype("uint8"),
            max_search_distance=3,
            smoothing_iterations=0,
        ).astype("float32")
        # Keep non-Latvia cells and invalid values as nodata.
        filled[(filled < 0) | (filled > 100) | (~grid_mask)] = NODATA
        profile = src.profile.copy()
        profile.update(dtype="float32", nodata=NODATA, compress="deflate")
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(filled, 1)
            tags = src.tags()
            tags.update(
                {
                    "visual_only_interpolated": "true",
                    "interpolation_note": "Small nodata seams filled with rasterio.fillnodata max_search_distance=3. Do not use for validation statistics.",
                    "analysis_source": str(path),
                }
            )
            dst.update_tags(**tags)
    return output


def main() -> int:
    with rasterio.open(GRID_MASK_TIFF) as mask_src:
        grid_mask = ~mask_src.read(1, masked=True).mask
    files = sorted(path for path in INPUT_DIR.rglob("*.tif") if path.is_file())
    if not files:
        raise SystemExit(f"No clean overpass TIFFs found in {INPUT_DIR}")
    for path in files:
        output = fill_visual(path, grid_mask)
        with rasterio.open(output) as src:
            valid = src.read(1, masked=True).compressed()
            print(f"{output}: valid={valid.size} min={valid.min():.2f} mean={valid.mean():.2f} max={valid.max():.2f}")
    print(f"Visual-filled TIFFs written: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
