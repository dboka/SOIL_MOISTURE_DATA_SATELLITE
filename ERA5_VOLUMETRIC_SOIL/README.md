# ERA5-Land volumetric soil water workflow

This folder contains an ERA5-Land workflow for comparing Latvia soil moisture with the existing Copernicus SSM workflow.

- Dataset: `reanalysis-era5-land`
- Default variable: `volumetric_soil_water_layer_1` (`swvl1`, 0-7 cm)
- Default interval: `2026-06-10` to `2026-06-18`
- Latvia bbox: `20.5,55.6,28.5,58.1`
- Native units: `m3 m-3`; comparison outputs also include percent volumetric soil water.

## Setup

```powershell
cd C:\Users\deniss.boka\MESLI_PROJECT\ERA5_VOLUMETRIC_SOIL
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
CDSAPI_URL=https://cds.climate.copernicus.eu/api
CDSAPI_KEY=...
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Write the CDS request only

This does not require credentials:

```powershell
python .\era5_land_soil_flow.py --start-date 2026-06-10 --end-date 2026-06-18 --no-download
```

Outputs are written to:

- `data\catalog\era5_land_request.json`

## Download and process ERA5-Land

```powershell
python .\era5_land_soil_flow.py --start-date 2026-06-10 --end-date 2026-06-18
```

Raw NetCDF files go to `data\raw`. Daily Latvia GeoTIFFs and summaries go to `data\processed`:

- `era5_land_swvl1_YYYYMMDD_latvia.tif`
- `era5_land_daily_stats.csv`

The GeoTIFF pixel values are percent volumetric soil water (`swvl1 * 100`) for easier comparison with Copernicus SSM.

## Process an already downloaded file

```powershell
python .\era5_land_soil_flow.py --input-netcdf .\data\raw\era5_land_20260610_20260618.nc --skip-download
```

## Sample ERA5-Land to the Latvia 1x1 km grid

```powershell
python .\sample_era5_to_lv_grid.py
```

By default this reuses:

- `..\COPERNICUS\1x1_LV_grid_2024_xy2.csv`
- `data\processed\era5_land_swvl1_*_latvia.tif`

Outputs:

- `data\grid\lv_1x1_grid_era5_swvl1_wide.csv`
- `data\grid\lv_1x1_grid_era5_swvl1_daily_coverage.csv`
- `data\grid\lv_1x1_grid_era5_swvl1_valid_long.csv`

## Compare ERA5-Land with Copernicus SSM on the grid

Run this after both workflows have created their valid-long grid outputs:

```powershell
python .\compare_era5_copernicus_grid.py
```

Outputs:

- `data\comparison\era5_copernicus_swvl1_grid_comparison.csv`
- `data\comparison\era5_copernicus_swvl1_daily_metrics.csv`
