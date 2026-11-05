# World and level tools

Real-world map data (evidence E04) and level editors.

> **Read this caveat.** Written from general knowledge plus video notes, not live-checked. Sites change terms, go offline, or rename
> licenses. The license that matters is the one on the **specific asset page on the day you download it**. Save the license text in
> `docs/licenses/` and log the asset in `docs/ASSET_LOG.md` via `/asset-intake`. Anything marked **(verify)** is the most likely to have changed.

## Real-world map data (for games inspired by a real place)
| Source | What | Notes |
|---|---|---|
| National elevation portals (the video used Poland's Geoportal) | Height grids you turn into terrain meshes | Check each portal's license and attribution rules. Rules differ by country. Verify before shipping. |
| OpenStreetMap | Roads, streams, buildings, land use | Open data with an attribution requirement (I believe ODbL, **verify** current terms and what share-alike means for your derived data). |
Pattern from the video: height data is just an image where each pixel is a height. Lift a flat grid by those heights, connect into triangles. An 8 by 8 km area took about 2.5 MB of height data. Keep your own edits (road cuts, reshaping) as a separate layer so you can regenerate without losing the real landscape.

### Elevation sources by region
Written from general knowledge on 2026-11-04, not live-checked: every resolution and licence below is **(verify)**.
Read the licence on the download page, save it in `docs/licenses/` and log the data with `/asset-intake`.

| Region | Source | Detail | Licence | Notes |
|---|---|---|---|---|
| United States | USGS 3D Elevation Program (3DEP) | ~10 m everywhere, 1 m lidar for most of the country | Public domain | The default for the US: The National Map Downloader, OpenTopography or AWS |
| US coasts | NOAA CUDEM | Land plus near-shore seafloor | Public domain | Coastal levels where the sea floor matters |
| Poland | Geoportal (geoportal.gov.pl) | ~1 m lidar terrain | National terms | The source used in the video (E04) |
| Netherlands | AHN | ~0.5 to 1 m lidar | CC0 | |
| France | IGN RGE ALTI | 1 m | Etalab open licence 2.0 | |
| United Kingdom | Environment Agency lidar; OS Terrain 50 | 1 m (England); 50 m (Great Britain) | Open Government Licence | Credit line required |
| Switzerland | swisstopo swissALTI3D | 0.5 to 2 m | Free with attribution (open since 2021) | |
| Spain | CNIG / IGN MDT | 2 to 5 m | CC BY 4.0 | |
| Germany | State survey offices (DGM1) | 1 m in many states | Open, but varies by state (dl-de/zero, dl-de/by 2.0) | Each state has its own portal |
| Nordic countries | Denmark (DHM), Finland (NLS), Norway (Kartverket) | 0.4 to 2 m | Open, mostly CC BY 4.0 | |
| Europe, anywhere | Copernicus DEM (GLO-30) | 30 m | Free with attribution | The fallback where no national lidar exists |
| Global | Copernicus DEM GLO-30 | 30 m | Free with attribution | The best general global choice |
| Global | NASADEM / SRTM | 30 m, about 60° N to 56° S | Public domain | No data near the poles |
| Global | ALOS World 3D (AW3D30, JAXA) | 30 m | Free with attribution (JAXA terms) | Good in mountains |
| Global | ASTER GDEM v3 | 30 m, high latitudes included | Free (NASA / METI terms) | Noisier than the others |
| Oceans and islands | GEBCO | ~450 m, seafloor and land | Free with attribution | Bathymetry |
| One place for many | OpenTopography | Many of the above | Each dataset's own licence | A website and an API (free key) |

Two traps for games:
- **Surface or bare earth.** The global 30 m sets (Copernicus, SRTM, ALOS) mostly measure the top surface: tree canopy and
  roofs are baked into the heights. Lidar terrain models (DTM, "bare earth") are the ground itself, which is what a game
  wants when it places its own trees and buildings.
- **Non-commercial variants.** FABDEM (Copernicus with forests and buildings removed) is CC BY-NC-SA: fine for a
  hobby project, not for a game you sell **(verify)**.

Picks: 3DEP in the US; in Europe the national lidar portal where one exists, otherwise Copernicus GLO-30; Copernicus
GLO-30 everywhere else.

## Level and content tools
- `Tiled` and `LDtk` for 2D. `Blender` plus engine-native tools for 3D. `ProBuilder`-style blockout in-engine for grayboxing.

Back to the index: `docs/RESOURCES.md`.
