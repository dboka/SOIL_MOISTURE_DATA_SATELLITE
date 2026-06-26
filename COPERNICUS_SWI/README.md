# Copernicus CLMS Soil Water Index workflow

Workflow for CLMS **Soil Water Index 2025-present (raster 1 km), Europe, daily - version 2**.

- Dataset identifier: `swi_europe_1km_daily_v2`
- Default window: `2026-06-01` to `2026-06-23`
- Default SWI band: `SWI010`
- Output grid: Latvia 1x1 km grid, EPSG:3059

## Catalogue test

```powershell
python .\copernicus_swi_flow.py --start-date 2026-06-01 --end-date 2026-06-23 --no-download
```

## Download and extract

```powershell
python .\copernicus_swi_flow.py --start-date 2026-06-01 --end-date 2026-06-23 --download-count 23
```

Raw files go to `data\raw`; extracted SWI rasters go to `data\extracted`.

## Create Latvia grid TIFFs

```powershell
python .\make_lv_grid_swi_tiffs.py --band SWI010
```

Outputs:

- `data\grid_tiffs\daily_swi\lv_1x1_swi010_YYYYMMDD.tif`
- `data\grid_tiffs\lv_1x1_swi010_valid_coverage_pct.tif`
- `data\grid_tiffs\lv_1x1_swi010_mean_pct.tif`
- `data\grid_tiffs\lv_1x1_swi010_daily_coverage.csv`
