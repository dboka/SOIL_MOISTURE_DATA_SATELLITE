# Copernicus CLMS Surface Soil Moisture test flow

This folder contains a small CDSE OData test for Latvia using:

- Collection: `CLMS`
- Dataset: `ssm_europe_1km_daily_v1`
- Preferred format: `cog`
- Default test interval: `2026-06-01` to today's date

## Setup

```powershell
cd C:\Users\deniss.boka\MESLI_PROJECT\COPERNICUS
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
CDSE_USER=...
CDSE_PASSWORD=...
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Catalogue-only test

This does not require credentials:

```powershell
python .\copernicus_ssm_flow.py --start-date 2026-06-01 --end-date 2026-06-25 --no-download
```

Outputs are written to:

- `data\catalog\products.csv`
- `data\catalog\products.json`
- `data\catalog\last_query_url.txt`

## Download one COG and crop Latvia

After credentials are in `.env`:

```powershell
python .\copernicus_ssm_flow.py --start-date 2026-06-01 --end-date 2026-06-25 --download-count 1
```

Raw files go to `data\raw`; Latvia crops go to `data\processed`.

## Analyze downloaded days

After downloading multiple days:

```powershell
python .\analyze_processing_summary.py
```

This creates:

- `data\processed\latvia_ssm_daily_stats.csv`
- `data\processed\latvia_ssm_daily_chart.png`

## Sample SSM to Latvia 1x1 km grid

```powershell
python .\sample_ssm_to_lv_grid.py
```

This uses `1x1_LV_grid_2024_xy2.csv` and all processed `*_latvia.tif` files. Outputs:

- `data\grid\lv_1x1_grid_ssm_wide.csv`
- `data\grid\lv_1x1_grid_ssm_daily_coverage.csv`
- `data\grid\lv_1x1_grid_ssm_valid_long.csv`

## Create Latvia 1x1 km GeoTIFF coverage maps

```powershell
python .\make_lv_grid_coverage_tiffs.py
```

This uses the extracted `SSM` rasters in `data\extracted` and writes EPSG:3059 GeoTIFFs:

- `data\grid_tiffs\lv_1x1_valid_coverage_count.tif`
- `data\grid_tiffs\lv_1x1_valid_coverage_pct.tif`
- `data\grid_tiffs\lv_1x1_mean_ssm_pct.tif`
- `data\grid_tiffs\daily_ssm\lv_1x1_ssm_YYYYMMDD.tif`

CDSE documentation used:

- OData catalogue and download: https://documentation.dataspace.copernicus.eu/APIs/OData.html
- Token endpoint: https://documentation.dataspace.copernicus.eu/APIs/Token.html
- CLMS Soil Moisture dataset list: https://documentation.dataspace.copernicus.eu/Data/CopernicusServices/CLMS.html
