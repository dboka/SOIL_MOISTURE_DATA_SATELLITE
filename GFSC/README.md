# CLMS GFSC viewer data

`build_gfsc_viewer_data.py` searches the CDSE OData catalogue for GFSC 60 m products intersecting Latvia, downloads the product ZIPs, and writes `ASCAT_HSAF_ORDER/moving_window_html/data/gfsc_frames.js` for GitHub Pages. The ZIPs stay in the ignored `GFSC/data` directory. The bundle contains GF snow-cover percentages sampled on the existing 1 km viewer grid, plus acquisition times from AT and Sentinel-1/2 identification from QAFLAGS.

```powershell
python GFSC/build_gfsc_viewer_data.py --start 2026-11-17 --end 2026-11-20 --env-file path/to/.env
```

The `.env` file needs `CDSE_USER` and `CDSE_PASSWORD`. You can also set them as environment variables. Without dates, the script queries the last three completed days.

GFSC is a daily seven-day composite. The product date is not an overpass time; each valid pixel's AT band holds its input observation's sensing start time. GF values 0-100 are valid snow-cover percentages. Codes 205 (cloud), 210 (water), and 255 (no data) are excluded. Coverage percentages use the Latvia land mask in the viewer, derived from its SWI layer. A cell with 0% snow cover is valid coverage.

Sources: [CDSE GFSC band documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/snow/snow-cover-extent/clms_wsi_gap-filled-fractional-snow-cover_europe_utm_60m_daily_v1.html), [CDSE OData snow download example](https://documentation.dataspace.copernicus.eu/notebook-samples/geo/odata_download_and_explore_clms_hr-wsi_1_snow.html), and [CLMS snow product manual](https://land.copernicus.eu/en/technical-library/product-user-manual-high-resolution-snow-products-europe).
