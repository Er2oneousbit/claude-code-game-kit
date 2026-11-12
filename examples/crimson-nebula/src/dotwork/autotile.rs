// ---------------------------------------------------------------------------
// dotwork/autotile.rs
// Purpose : The tile rules of the Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md "Autotiling and maps"):
//           the key that picks a terrain cell's tile (canon, cell_mask for blob47, sides4 and corners4, the corner
//           bits of a corners4 tile), the deterministic variant pick (hash32, cell_roll, pick), the tiles a stamp
//           covers, map cell centres on both shapes, and the flip and transpose flags of placed tiles as a Transform
//           rotation and scale.
// Usage   : let key = cell_mask(&painted, x, y, TerrainMode::Corners4);   corners_key(&corners, terrain, shape)
//           let tile = pick(&candidates, cell_roll(x, y, layer_index));   cell_centre(Shape::Isometric, x, y, size)
//           stamp_cells(x, y, width, &tiles);   let (angle, scale) = flags_transform(flags);
// Notes   : Engine-free and pure: tests/dotwork.rs checks it against the golden fixture's expected.json, which
//           assetspec.py (the reference) wrote. Neighbour order and bits are the spec's: N, NE, E, SE, S, SW, W, NW =
//           bits 0 to 7, y down (row 0 is the top of the map). Masks are u8, like the spec's 8 bits. The hash is
//           Bob Jenkins' 6-shift integer hash ported as written: u32 shifts, wrapping adds and xors only, so every
//           engine rolls the same number for a cell (the spec's test vectors are in the unit tests below).
//
// Pseudocode:
//   cell_mask: for each of the 8 neighbours painted with the same terrain set its bit -> sides4 keeps N E S W only,
//   blob47 drops a corner bit unless both sides next to it are set (canon), corners4 keeps canon's corner bits
//   corners_key: sum the bits of the corners that hold the tile's own terrain (names per shape)
//   cell_roll: hash32(hash32(x:16 | y:16) + layer) / 2^32;  pick: walk the weights in atlas order until the roll
//   times the total falls inside one
//   stamp_cells: tile j of a stamp w cells wide lands at (x + j % w, y + j / w), reading order
//   cell_centre: square ((x + 0.5) w, (y + 0.5) h); isometric ((x - y + 1) w / 2, (x + y + 1) h / 2), y down
//   flags_transform: transpose, then flip x, then flip y as a matrix in y-down image space -> mirror it into Bevy's
//   y-up space -> split it into a z rotation and a y scale of +1 or -1 (Transform applies scale, then rotation)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
//           Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the corners4 rule
//           and corner keys, the hash and the probability pick, stamps, the isometric centre as Godot's
//           map_to_local gives it
// ---------------------------------------------------------------------------
use std::collections::{BTreeMap, HashSet};

use bevy::math::{Mat2, Vec2};

/// The 8 neighbours as (dx, dy), y down, in bit order: N, NE, E, SE, S, SW, W, NW.
pub const NB8: [(i64, i64); 8] = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)];
/// N, E, S and W: the bits a sides4 mask keeps.
pub const SIDES_ONLY: u8 = 1 | 4 | 16 | 64;
/// NE, SE, SW and NW: the bits a corners4 key keeps.
pub const CORNERS_ONLY: u8 = 2 | 8 | 32 | 128;
/// Placed-tile flags (map layers of kind "tiles", the sixth number): transpose first, then flip.
pub const FLIP_H: u8 = 1;
pub const FLIP_V: u8 = 2;
pub const TRANSPOSE: u8 = 4;

/// How a tileset's terrains match their neighbours (the spec's `terrain_sets[].mode`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TerrainMode {
    /// Match corners and sides: 47 masks.
    Blob47,
    /// Match sides: masks with N, E, S and W only.
    Sides4,
    /// Match corners: tiles carry a terrain per corner; a cell's key is the corner bits of its blob mask.
    Corners4,
}

impl TerrainMode {
    pub fn parse(mode: &str) -> Option<Self> {
        match mode {
            "blob47" => Some(TerrainMode::Blob47),
            "sides4" => Some(TerrainMode::Sides4),
            "corners4" => Some(TerrainMode::Corners4),
            _ => None,
        }
    }
}

/// A map cell's shape (the spec's tileset `shape`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shape {
    Square,
    /// 2:1 diamonds in Godot's diamond-down layout.
    Isometric,
}

impl Shape {
    pub fn parse(shape: &str) -> Option<Self> {
        match shape {
            "square" => Some(Shape::Square),
            "isometric" => Some(Shape::Isometric),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Shape::Square => "square",
            Shape::Isometric => "isometric",
        }
    }

    /// The corner names a corners4 tile carries on this shape, with the mask bit of the neighbour across each
    /// (a diamond's top corner touches the cell up the screen, which is NW in map coordinates).
    pub fn corner_bits(self) -> [(&'static str, u8); 4] {
        match self {
            Shape::Square => [
                ("top_left", 128),
                ("top_right", 2),
                ("bottom_right", 8),
                ("bottom_left", 32),
            ],
            Shape::Isometric => [("top", 128), ("right", 2), ("bottom", 8), ("left", 32)],
        }
    }
}

/// A corner bit only counts when both sides next to it are set: the 256 raw masks fold into the 47 blob masks.
pub fn canon(mut m: u8) -> u8 {
    for c in [1u32, 3, 5, 7] {
        let before = (m >> ((c + 7) % 8)) & 1;
        let after = (m >> ((c + 1) % 8)) & 1;
        if before == 0 || after == 0 {
            m &= !(1u8 << c);
        }
    }
    m
}

/// The key a painted cell at (x, y) needs, from the set of painted cells of the same terrain (the spec's
/// cell_mask): the canon mask (blob47), its four side bits (sides4) or its four corner bits (corners4: a corner is
/// the terrain only when all four cells meeting there are painted).
pub fn cell_mask(painted: &HashSet<(i64, i64)>, x: i64, y: i64, mode: TerrainMode) -> u8 {
    let mut m = 0u8;
    for (bit, (dx, dy)) in NB8.iter().enumerate() {
        if painted.contains(&(x + dx, y + dy)) {
            m |= 1 << bit;
        }
    }
    match mode {
        TerrainMode::Sides4 => m & SIDES_ONLY,
        TerrainMode::Corners4 => canon(m) & CORNERS_ONLY,
        TerrainMode::Blob47 => canon(m),
    }
}

/// The key a corners4 tile answers to: the sum of the corner bits whose corner holds the tile's own terrain.
/// None when the corner names are not the shape's four (the reference gives such a tile no key).
pub fn corners_key(corners: &BTreeMap<String, i64>, terrain: u32, shape: Shape) -> Option<u8> {
    let names = shape.corner_bits();
    if corners.len() != names.len() || names.iter().any(|(n, _)| !corners.contains_key(*n)) {
        return None;
    }
    Some(
        names
            .iter()
            .filter(|(n, _)| corners[*n] == i64::from(terrain))
            .map(|(_, bit)| bit)
            .sum(),
    )
}

/// Bob Jenkins' 32-bit integer hash (six shifts), as the spec writes it: only shifts, adds and xors, every step
/// kept to 32 bits (u32 shifts drop the high bits; the adds wrap).
pub fn hash32(mut k: u32) -> u32 {
    k = k.wrapping_add(0x7ED5_5D16).wrapping_add(k << 12);
    k = k ^ 0xC761_C23C ^ (k >> 19);
    k = k.wrapping_add(0x1656_67B1).wrapping_add(k << 5);
    k = k.wrapping_add(0xD3A2_646C) ^ (k << 9);
    k = k.wrapping_add(0xFD70_46C5).wrapping_add(k << 3);
    k ^ 0xB55A_4F09 ^ (k >> 16)
}

/// The roll in [0, 1) that picks a terrain cell's variant: from the cell and the index of its layer in the map's
/// `layers` list (0-based, every kind counted), the same number in every engine. Coordinates wrap at 16 bits.
pub fn cell_roll(x: i64, y: i64, layer: usize) -> f64 {
    let packed = (((x & 0xFFFF) as u32) << 16) | ((y & 0xFFFF) as u32);
    f64::from(hash32(hash32(packed).wrapping_add(layer as u32))) / 4_294_967_296.0
}

/// The candidate whose weight span holds `roll` times the total: `candidates` are (probability, value) in atlas
/// order (atlases by id, tiles in list order). The first when every weight is 0; None for no candidates.
pub fn pick<T>(candidates: &[(f64, T)], roll: f64) -> Option<&T> {
    let total: f64 = candidates.iter().map(|(w, _)| w).sum();
    if total <= 0.0 {
        return candidates.first().map(|(_, v)| v);
    }
    let mut u = roll * total;
    for (w, v) in candidates {
        u -= w;
        if u < 0.0 {
            return Some(v);
        }
    }
    candidates.last().map(|(_, v)| v)
}

/// The cells a stamp placed from its top-left cell (x, y) covers: tile `j` of a stamp `width` cells wide lands at
/// (x + j % width, y + j / width), in reading order (the spec's stamps layers). A width of 0 counts as 1.
pub fn stamp_cells(x: i64, y: i64, width: u32, tiles: &[[u32; 3]]) -> Vec<(i64, i64, [u32; 3])> {
    let w = i64::from(width.max(1));
    tiles
        .iter()
        .enumerate()
        .map(|(j, &tile)| {
            let j = j as i64;
            (x + j % w, y + j / w, tile)
        })
        .collect()
}

/// The centre of map cell (x, y) in the map's own pixels, y down, the map's top-left corner at (0, 0).
/// Isometric is Godot's diamond-down layout (TileMapLayer.map_to_local on 4.7.2): x steps down-right, y steps
/// down-left, cell (0, 0)'s diamond centre is (w / 2, h / 2).
pub fn cell_centre(shape: Shape, x: i64, y: i64, cell: Vec2) -> Vec2 {
    match shape {
        Shape::Square => Vec2::new((x as f32 + 0.5) * cell.x, (y as f32 + 0.5) * cell.y),
        Shape::Isometric => Vec2::new((x - y + 1) as f32 * cell.x / 2.0, (x + y + 1) as f32 * cell.y / 2.0),
    }
}

/// The flip and transpose flags of a placed tile as (z rotation in radians, scale) for its Transform, in Bevy's
/// y-up space. Transform scales first, then rotates, so rotation(angle) * scale reproduces the flags exactly.
pub fn flags_transform(flags: u8) -> (f32, Vec2) {
    let m = flags_matrix(flags);
    let det = m.determinant().round();
    let scale = Vec2::new(1.0, det);
    let rot = m * Mat2::from_diagonal(scale); // scale is its own inverse
    (rot.x_axis.y.atan2(rot.x_axis.x), scale)
}

/// The flags as a matrix acting on y-up offsets from the tile's centre.
pub fn flags_matrix(flags: u8) -> Mat2 {
    let mut m = Mat2::IDENTITY; // y down, image space
    if flags & TRANSPOSE != 0 {
        m = Mat2::from_cols(Vec2::new(0.0, 1.0), Vec2::new(1.0, 0.0)) * m;
    }
    if flags & FLIP_H != 0 {
        m = Mat2::from_diagonal(Vec2::new(-1.0, 1.0)) * m;
    }
    if flags & FLIP_V != 0 {
        m = Mat2::from_diagonal(Vec2::new(1.0, -1.0)) * m;
    }
    let mirror = Mat2::from_diagonal(Vec2::new(1.0, -1.0)); // y down <-> y up
    mirror * m * mirror
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canon_folds_to_47_masks() {
        let masks: HashSet<u8> = (0..=255u8).map(canon).collect();
        assert_eq!(masks.len(), 47);
        assert_eq!(canon(2), 0, "NE alone needs N and E");
        assert_eq!(canon(1 | 2 | 4), 7);
        assert_eq!(canon(255), 255);
    }

    #[test]
    fn cell_mask_reads_neighbours_y_down() {
        let painted: HashSet<(i64, i64)> = [(1, 1), (1, 0), (2, 1), (2, 0)].into_iter().collect();
        // (1, 1) has N (1, 0), E (2, 1) and NE (2, 0): 1 + 4 + 2
        assert_eq!(cell_mask(&painted, 1, 1, TerrainMode::Blob47), 7);
        assert_eq!(cell_mask(&painted, 1, 1, TerrainMode::Sides4), 5);
        // corners4: NE is painted on all four cells meeting there (bit 2); nothing else
        assert_eq!(cell_mask(&painted, 1, 1, TerrainMode::Corners4), 2);
    }

    #[test]
    fn corners4_keys_of_a_3x3_block() {
        let painted: HashSet<(i64, i64)> = (0..3).flat_map(|y| (0..3).map(move |x| (x, y))).collect();
        assert_eq!(
            cell_mask(&painted, 1, 1, TerrainMode::Corners4),
            170,
            "the centre has all four corners"
        );
        assert_eq!(cell_mask(&painted, 0, 0, TerrainMode::Corners4), 8, "top-left: SE only");
        assert_eq!(
            cell_mask(&painted, 1, 0, TerrainMode::Corners4),
            40,
            "top-middle: SE and SW"
        );
        assert_eq!(
            cell_mask(&painted, 2, 2, TerrainMode::Corners4),
            128,
            "bottom-right: NW only"
        );
    }

    #[test]
    fn corner_names_map_to_bits_by_shape() {
        let tile = |pairs: &[(&str, i64)]| {
            pairs
                .iter()
                .map(|(n, v)| (n.to_string(), *v))
                .collect::<BTreeMap<_, _>>()
        };
        let square = tile(&[
            ("top_left", 1),
            ("top_right", 0),
            ("bottom_right", 1),
            ("bottom_left", -1),
        ]);
        assert_eq!(corners_key(&square, 1, Shape::Square), Some(128 | 8));
        assert_eq!(corners_key(&square, 0, Shape::Square), Some(2));
        let iso = tile(&[("top", 1), ("right", 1), ("bottom", 0), ("left", 0)]);
        assert_eq!(corners_key(&iso, 1, Shape::Isometric), Some(128 | 2));
        assert_eq!(
            corners_key(&iso, 1, Shape::Square),
            None,
            "square names on an iso tile: no key"
        );
    }

    #[test]
    fn hash_and_roll_match_the_spec_vectors() {
        assert_eq!(hash32(0), 1_800_329_511);
        assert_eq!(hash32(1), 3_028_713_910);
        assert_eq!(hash32(0xFFFF_FFFF), 4_268_016_002);
        let close = |a: f64, b: f64| (a - b).abs() < 5e-7;
        assert!(close(cell_roll(0, 0, 0), 0.169182), "{}", cell_roll(0, 0, 0));
        assert!(close(cell_roll(3, 1, 1), 0.765973), "{}", cell_roll(3, 1, 1));
        assert!(close(cell_roll(3, 2, 1), 0.531301), "{}", cell_roll(3, 2, 1));
        assert!(close(cell_roll(-1, -1, 0), 0.992978), "{}", cell_roll(-1, -1, 0));
    }

    #[test]
    fn the_pick_walks_the_weights_in_order() {
        let c = [(1.0, "a"), (0.6, "b")];
        assert_eq!(pick(&c, 0.0), Some(&"a"));
        assert_eq!(pick(&c, 0.62), Some(&"a"), "0.62 * 1.6 < 1");
        assert_eq!(pick(&c, 0.7), Some(&"b"));
        assert_eq!(pick(&[(0.0, "a"), (0.0, "b")], 0.9), Some(&"a"), "all zero: the first");
        assert_eq!(pick::<&str>(&[], 0.5), None);
    }

    #[test]
    fn a_stamp_expands_in_reading_order() {
        // the golden door: 1 x 2, placed at (7, 0)
        let door = stamp_cells(7, 0, 1, &[[4, 0, 0], [4, 1, 0]]);
        assert_eq!(door, vec![(7, 0, [4, 0, 0]), (7, 1, [4, 1, 0])]);
        // a 3 x 2 piece: tile j at (x + j % 3, y + j / 3)
        let tiles: Vec<[u32; 3]> = (0..6).map(|j| [0, j, 0]).collect();
        let well = stamp_cells(2, 5, 3, &tiles);
        assert_eq!(well[4], (3, 6, [0, 4, 0]));
        assert_eq!(well.len(), 6);
        assert!(stamp_cells(0, 0, 2, &[]).is_empty());
    }

    #[test]
    fn flags_turn_pixels_like_the_spec_says() {
        // y-up offsets: a pixel right of centre (1, 0) and one above it (0, 1)
        let apply = |flags: u8, v: Vec2| {
            let (angle, scale) = flags_transform(flags);
            let out = Mat2::from_angle(angle) * (v * scale);
            Vec2::new(out.x.round(), out.y.round())
        };
        assert_eq!(apply(0, Vec2::X), Vec2::X);
        assert_eq!(apply(FLIP_H, Vec2::X), -Vec2::X);
        assert_eq!(apply(FLIP_V, Vec2::Y), -Vec2::Y);
        // transpose swaps x and y in y-down space: right (1, 0) goes to down, which is (0, -1) in y up
        assert_eq!(apply(TRANSPOSE, Vec2::X), -Vec2::Y);
        assert_eq!(apply(TRANSPOSE, Vec2::Y), -Vec2::X);
        // transpose first, then flip horizontally: right -> down -> down (flip x leaves y alone)
        assert_eq!(apply(TRANSPOSE | FLIP_H, Vec2::X), -Vec2::Y);
        assert_eq!(apply(TRANSPOSE | FLIP_H, Vec2::Y), Vec2::X);
        for flags in 0..8u8 {
            let m = flags_matrix(flags);
            for v in [Vec2::X, Vec2::Y] {
                assert_eq!(apply(flags, v), m * v, "flags {flags}");
            }
        }
    }

    #[test]
    fn cells_are_placed_by_their_centres() {
        let cell = Vec2::new(8.0, 8.0);
        assert_eq!(cell_centre(Shape::Square, 0, 0, cell), Vec2::new(4.0, 4.0));
        assert_eq!(cell_centre(Shape::Square, 2, 1, cell), Vec2::new(20.0, 12.0));
        // Godot's diamond-down map_to_local on a 16 x 8 set (4.7.2, 2026-11-11)
        let iso = Vec2::new(16.0, 8.0);
        assert_eq!(cell_centre(Shape::Isometric, 0, 0, iso), Vec2::new(8.0, 4.0));
        assert_eq!(cell_centre(Shape::Isometric, 1, 0, iso), Vec2::new(16.0, 8.0));
        assert_eq!(cell_centre(Shape::Isometric, 0, 1, iso), Vec2::new(0.0, 8.0));
        assert_eq!(cell_centre(Shape::Isometric, 3, 2, iso), Vec2::new(16.0, 24.0));
    }
}
