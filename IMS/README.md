# NOAA IMS 1 km snow and ice analysis

`build_ims_viewer_data.py` downloads the US National Ice Center (USNIC) IMS daily 1 km GeoTIFFs from the [NSIDC G02156 archive](https://nsidc.org/data/g02156/versions/1). When the latest analysis is not yet in that archive, it checks the [USNIC current GeoTIFF](https://usicecenter.gov/Products/ImsData). Compressed rasters remain in the ignored `IMS/data` directory. The script writes `ASCAT_HSAF_ORDER/moving_window_html/data/ims_frames.js` for GitHub Pages.

```powershell
python IMS/build_ims_viewer_data.py --start 2026-11-01 --end 2026-11-24
```

**Date convention:** The GeoTIFF filename is its production date. The analysis is valid at **00:00 UTC the next day**. Thus the example uses files created from 31 October through 23 November. This follows the [NSIDC user guide](https://nsidc.org/sites/default/files/g02156-v001-userguide_1_1.pdf).

The IMS raster classes are 0 outside the hemisphere, 1 sea, 2 snow-free land, 3 sea ice, and 4 snow-covered land. The viewer samples classes 2 and 4 at the centres of its existing Latvia 1 km grid and excludes water and sea ice. It reports a binary snow state per cell and the percentage of classified land cells marked snow; this is **not** a per-pixel snow-cover percentage. The analysis combines multiple inputs and analyst judgment, so there is no single satellite overpass time to display.

For 1-24 November 2026, all sampled Latvia land cells in the downloaded IMS maps are class 2. The 24 November frame uses the USNIC current file `NIC.IMS_v3_20261123_1km.tif.gz`; direct pixel checks at Stende, Riga, Alūksne and Daugavpils also returned class 2. This differs from CLIDATA's 2 cm HSNOW observation at Stende on 24 November and from CLMS SCE on some earlier dates. The [NOAA IMS map service](https://mapservices.weather.noaa.gov/raster/rest/services/obs/usnic_ims_snow_ice_1km/ImageServer) also returned class 2 for Riga when checked on 23 November 2026.

Please cite: U.S. National Ice Center. (2008). *IMS Daily Northern Hemisphere Snow and Ice Analysis at 1 km, 4 km, and 24 km Resolutions* (G02156, Version 1). National Snow and Ice Data Center. https://doi.org/10.7265/N52R3PMC.
