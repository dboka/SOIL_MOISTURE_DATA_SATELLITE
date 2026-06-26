# Soil Moisture Moving Window Viewer

Static HTML viewer for Latvia soil moisture layers:

- H SAF H28 ASCAT overpasses: 13-17 June 2026
- Copernicus CLMS SSM daily frames: 1-23 June 2026
- Copernicus CLMS SWI010 daily frames: 1-23 June 2026
- ERA5-Land swvl1 daily frames: 10-18 June 2026

All layers are shown on the same Latvia 1x1 km viewer grid and a fixed 0-100% colour scale. SWI010 is a Soil Water Index layer with a 10-day characteristic time length. ERA5-Land is volumetric soil water layer 1, shown as percent volumetric soil water for visual comparison; it is not the same retrieval as satellite surface soil moisture.

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
