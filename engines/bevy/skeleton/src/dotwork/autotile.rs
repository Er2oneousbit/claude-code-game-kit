// ---------------------------------------------------------------------------
// dotwork/autotile.rs
// Purpose : The tile rules of the Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md "Autotiling and maps"):
//           the blob rule that picks a terrain cell's tile (canon, cell_mask), map cell positions, and the flip and
//           transpose flags of placed tiles as a Transform rotation and scale.
// Usage   : let mask = cell_mask(&painted, x, y, TerrainMode::Blob47);   cell_centre(Shape::Square, cell, size)
//           let (angle, scale) = flags_transform(flags);
// Notes   : Engine-free and pure: tests/dotwork.rs checks it against the golden fixture's expected.json, which
//           assetspec.py (the reference) wrote. Neighbour order and bits are the spec's: N, NE, E, SE, S, SW, W, NW =
//           bits 0 to 7, y down (row 0 is the top of the map). Masks are u8, like the spec's 8 bits.
//
// Pseudocode:
//   cell_mask: for each of the 8 neighbours painted with the same terrain set its bit -> sides4 keeps N E S W only,
//   blob47 drops a corner bit unless both sides next to it are set (canon)
//   flags_transform: transpose, then flip x, then flip y as a matrix in y-down image space -> mirror it into Bevy's
//   y-up space -> split it into a z rotation and a y scale of +1 or -1 (Transform applies scale, then rotation)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::HashSet;

use bevy::math::{Mat2, Vec2};

/// The 8 neighbours as (dx, dy), y down, in bit order: N, NE, E, SE, S, SW, W, NW.
pub const NB8: [(i64, i64); 8] = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)];
/// N, E, S and W: the bits a sides4 mask keeps.
pub const SIDES_ONLY: u8 = 1 | 4 | 16 | 64;
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
    /// Match corners: tiles carry a terrain per corner, not a mask (maps do not resolve these yet).
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

/// The mask a painted cell at (x, y) needs, from the set of painted cells of the same terrain (the spec's cell_mask).
pub fn cell_mask(painted: &HashSet<(i64, i64)>, x: i64, y: i64, mode: TerrainMode) -> u8 {
    let mut m = 0u8;
    for (bit, (dx, dy)) in NB8.iter().enumerate() {
        if painted.contains(&(x + dx, y + dy)) {
            m |= 1 << bit;
        }
    }
    match mode {
        TerrainMode::Sides4 => m & SIDES_ONLY,
        _ => canon(m),
    }
}

/// The centre of map cell (x, y) in the map's own pixels, y down, the map's top-left corner at (0, 0).
/// Isometric is Godot's diamond-down layout: x steps down-right, y steps down-left. **(verify)** against an isometric
/// map Godot painted: no golden map is isometric yet.
pub fn cell_centre(shape: Shape, x: i64, y: i64, cell: Vec2) -> Vec2 {
    match shape {
        Shape::Square => Vec2::new((x as f32 + 0.5) * cell.x, (y as f32 + 0.5) * cell.y),
        Shape::Isometric => Vec2::new(
            (x - y) as f32 * cell.x / 2.0,
            (x + y) as f32 * cell.y / 2.0 + cell.y / 2.0,
        ),
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
        let iso = Vec2::new(16.0, 8.0);
        assert_eq!(cell_centre(Shape::Isometric, 1, 0, iso), Vec2::new(8.0, 8.0));
        assert_eq!(cell_centre(Shape::Isometric, 0, 1, iso), Vec2::new(-8.0, 8.0));
    }
}

// {{FOOTER}}
