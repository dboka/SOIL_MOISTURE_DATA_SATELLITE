# Soil Moisture Moving Window Viewer

Static HTML viewer for Latvia soil moisture layers:

- H SAF H28 ASCAT overpasses: 13-17 June 2026
- Copernicus CLMS SSM daily frames: 1-23 June 2026
- Copernicus CLMS SWI010 daily frames: 1-23 June 2026
- ERA5-Land swvl1 daily frames: 10-18 June 2026
- CLMS GFSC 60 m daily composites: 1-22 November 2026
- CLMS SCE Europe 500 m Terra MODIS daily frames: 1-22 November 2026

All layers are shown on the same Latvia 1x1 km viewer grid and a fixed 0-100% colour scale. SWI010 is a Soil Water Index layer with a 10-day characteristic time length. ERA5-Land is volumetric soil water layer 1, shown as percent volumetric soil water for visual comparison; it is not the same retrieval as satellite surface soil moisture.

GFSC is snow-cover fraction, a separate variable with its own colour palette. Its native 60 m GF band is sampled at the centres of the 1 km viewer cells. The product date is a daily composite, not a single satellite overpass. Click a valid cell to see the acquisition time and Sentinel sensor from the AT and QAFLAGS bands. The viewer lists cells without a catalogued tile separately from cells marked no-data or cloud within a tile. Coverage varies from 0.33% on 21 November to 32.11% on 1-2 November; the 22 November frame contains actual snow-cover values. The GFSC button opens the latest available day, and the slider navigates the whole window.

SCE uses the daily Terra MODIS Europe 500 m COG. Digital values 100-200 become 0-100% snow cover; 255 and other invalid codes are not drawn. Its reported observation time is the product's sensing window from COG metadata, not a per-pixel timestamp. The SCE button opens the latest available day. Coverage reaches 95.43% of the Latvia viewer land grid on 6 November; 9, 20, and 21 November have no valid sampled cells.

Open locally through a small web server:

```powershell
cd C:\Users\deniss.boka\MESLI_PROJECT\ASCAT_HSAF_ORDER\moving_window_html
python -m http.server 8060
```

Then open:

```text
http://127.0.0.1:8060/
```

Regenerate the data bundle after rebuilding clean overpass TIFFs:

```powershell
cd C:\Users\deniss.boka\MESLI_PROJECT\ASCAT_HSAF_ORDER
python .\build_hsaf_viewer_data.py
```
