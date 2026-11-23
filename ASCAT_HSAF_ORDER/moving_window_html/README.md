# Soil Moisture Moving Window Viewer

Static HTML viewer for Latvia soil moisture layers:

- H SAF H28 ASCAT overpasses: 13-17 June 2026
- Copernicus CLMS SSM daily frames: 1-23 June 2026
- Copernicus CLMS SWI010 daily frames: 1-23 June 2026
- ERA5-Land swvl1 daily frames: 10-18 June 2026
- CLMS GFSC 60 m daily composites: 17-20 November 2026

All layers are shown on the same Latvia 1x1 km viewer grid and a fixed 0-100% colour scale. SWI010 is a Soil Water Index layer with a 10-day characteristic time length. ERA5-Land is volumetric soil water layer 1, shown as percent volumetric soil water for visual comparison; it is not the same retrieval as satellite surface soil moisture.

GFSC is snow-cover fraction, a separate variable with its own colour palette. Its native 60 m GF band is sampled at the centres of the 1 km viewer cells. The product date is a daily composite, not a single satellite overpass. Click a valid cell to see the acquisition time and Sentinel sensor from the AT and QAFLAGS bands. For 17-20 November 2026, only 1.41% of Latvia land cells have valid GF values; cloud, water and no-data codes are excluded. The viewer now lists cells without a catalogued tile separately from cells marked no-data or cloud within a tile. The four frames contain the same GF values and source observation times.

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
