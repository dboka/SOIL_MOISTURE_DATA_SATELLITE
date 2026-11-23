# Soil Moisture Data Satellite Workflows

This repository contains experimental workflows for finding and comparing soil moisture related satellite/reanalysis variables over Latvia.

The current focus is to search for, download, sample, and visually compare these variables:

- **H SAF H28 ASCAT surface soil moisture** overpasses
- **Copernicus CLMS Surface Soil Moisture (SSM)** daily 1 km raster product
- **Copernicus CLMS Soil Water Index (SWI)** daily 1 km raster product, currently using `SWI010`
- **ERA5-Land volumetric soil water layer 1 (`swvl1`)**, shown as percent volumetric soil water for comparison
- **Copernicus CLMS GFSC 60 m** daily fractional snow-cover composites, sampled to the viewer grid
- **Copernicus SCE Europe 500 m** Terra MODIS daily snow-cover fractions, sampled to the viewer grid
- **NOAA IMS 1 km** daily analyst-produced snow/no-snow maps, sampled to the viewer grid

The interactive viewer lives in:

```text
ASCAT_HSAF_ORDER/moving_window_html/index.html
```

It uses a Latvia 1x1 km viewer grid. Soil moisture and snow cover both use 0-100% numeric scales, with distinct meanings and palettes. The viewer includes a `CLMS GFSC 60 m` layer for 1-22 November 2026 (all completed November days available as of 23 November). Clicking a valid snow-cover cell shows the source Sentinel observation time from the GFSC AT band.

The `CLMS SCE 500 m` layer covers 1-22 November 2026 using Terra MODIS COG products. Its time panel shows the product's sensing window, not a per-pixel overpass time.

The `NOAA IMS 1 km` layer covers 1-23 November 2026. IMS has binary snow/no-snow classes, not a fractional snow percentage. The GeoTIFF file date is its production day; the analysis is valid at 00:00 UTC the following day.

Important note: these variables are related, but not identical. H SAF ASCAT and Copernicus SSM are satellite surface soil moisture style products. SWI is a Soil Water Index with a time-depth memory, and ERA5-Land `swvl1` is model/reanalysis volumetric soil water in the upper soil layer.

## Secrets and data

Credentials are intentionally excluded from git. Copy `.env.example` files locally and fill in credentials on your machine.

Large raw/downloaded geospatial files are also excluded from git. The workflows can regenerate them locally.
