# CLMS GFSC viewer data

`build_gfsc_viewer_data.py` searches the CDSE OData catalogue for GFSC 60 m products intersecting Latvia, downloads the product ZIPs, and writes `ASCAT_HSAF_ORDER/moving_window_html/data/gfsc_frames.js` for GitHub Pages. The ZIPs stay in the ignored `GFSC/data` directory. The bundle contains GF snow-cover percentages sampled on the existing 1 km viewer grid, plus acquisition times from AT and Sentinel-1/2 identification from QAFLAGS.

```powershell
python GFSC/build_gfsc_viewer_data.py --start 2026-11-23 --end 2026-11-24 --append --env-file path/to/.env
```

The `.env` file needs `CDSE_USER` and `CDSE_PASSWORD`. You can also set them as environment variables. Without dates, the script queries the last three completed days.

The example appends the latest catalogued day to the existing November bundle. On 24 November 2026, the catalogue had seven products dated 23 November and none yet dated 24 November. The 23 November frame covers 9.01% of the Latvia land grid; its sampled values and acquisition times are identical to the 22 November frame, with Sentinel-2 observations from 22 November around 09:54 UTC. The script queries each day separately because broad OData responses can repeat products across pages and omit others.

GFSC is a daily seven-day composite. The product date is not an overpass time; each valid pixel's AT band holds its input observation's sensing start time. GF values 0-100 are valid snow-cover percentages. Codes 205 (cloud), 210 (water), and 255 (no data) are excluded. Coverage percentages use the Latvia land mask in the viewer, derived from its SWI layer. A cell with 0% snow cover is valid coverage.

Sources: [CDSE GFSC band documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/snow/snow-cover-extent/clms_wsi_gap-filled-fractional-snow-cover_europe_utm_60m_daily_v1.html), [CDSE OData snow download example](https://documentation.dataspace.copernicus.eu/notebook-samples/geo/odata_download_and_explore_clms_hr-wsi_1_snow.html), and [CLMS snow product manual](https://land.copernicus.eu/en/technical-library/product-user-manual-high-resolution-snow-products-europe).
