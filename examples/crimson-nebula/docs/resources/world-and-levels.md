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

## Level and content tools
- `Tiled` and `LDtk` for 2D. `Blender` plus engine-native tools for 3D. `ProBuilder`-style blockout in-engine for grayboxing.

Back to the index: `docs/RESOURCES.md`.
