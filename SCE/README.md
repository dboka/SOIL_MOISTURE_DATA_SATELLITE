# CLMS Snow Cover Extent Europe 500 m

`build_sce_viewer_data.py` downloads the daily **Terra MODIS** COG variant of the Copernicus SCE Europe 500 m product and writes `ASCAT_HSAF_ORDER/moving_window_html/data/sce_frames.js` for GitHub Pages. The CDSE download endpoint packages the COG as a ZIP. Those ZIPs stay local under the ignored `SCE/data` directory.

```powershell
python SCE/build_sce_viewer_data.py --start 2026-11-01 --end 2026-11-22 --env-file path/to/.env
```

The `.env` file needs `CDSE_USER` and `CDSE_PASSWORD`, or they can be set as environment variables. The example includes all completed November days available on 23 November 2026. Without dates, the script queries the last three completed days.

The native COG grid is 0.005° (about 500 m). The viewer samples it at the centres of its existing Latvia 1 km grid cells. Digital values 100-200 represent 0-100% snow-cover fraction after subtracting 100. Code 255 is no data; separate codes can indicate cloud (30), water (20-22), polar night (251), or input error (254). The Terra MODIS sensing window comes from `time_coverage_start` and `time_coverage_end` COG metadata; it is not an exact per-pixel time. Coverage percentages use the viewer's Latvia land mask.

Sources: [CLMS SCE product page](https://land.copernicus.eu/en/products/snow/snow-cover-extent-europe-v1-0-500m/), [CDSE SCE band documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/snow/snow-cover-extent/sce_europe_500m_daily_v1.html).
