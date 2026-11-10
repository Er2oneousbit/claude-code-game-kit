// ---------------------------------------------------------------------------
// logic/charmap.rs
// Purpose : Which characters a font can draw, read from its character map (the TrueType/OpenType cmap table), so
//           the pseudo-locale drive and the tests catch text that would show as empty boxes ("tofu").
// Usage   : let map = CharMap::parse(include_bytes!("../shell/fonts/FiraMono-Medium.ttf")).unwrap();
//           map.missing("Paramètres")   // -> the characters the font has no glyph for, in order, once each
// Notes   : Reads cmap subtables of format 4 (the Basic Multilingual Plane) and 12 (all of Unicode), the two every
//           desktop font has; a character counts as covered when it maps to a glyph other than 0 (.notdef, the
//           empty box). Bevy draws a missing character with the box and never says so: its default font is an
//           ASCII-only subset, which is why the shell compiles in full fonts (src/shell/fonts/). Engine-free.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
//
// Pseudocode
//   table directory -> the cmap table -> its subtable records -> the first of (3,10), (0,4), (0,6), (0,3), (3,1)
//   with format 12 or 4 -> walk every segment or group, keep each character whose glyph is not 0
use std::collections::HashSet;

/// The cmap subtables to read, best first: (platform, encoding). 3/10 and 0/4 or 0/6 hold all of Unicode, 3/1 and
/// 0/3 the BMP.
const PREFERRED: [(u16, u16); 5] = [(3, 10), (0, 4), (0, 6), (0, 3), (3, 1)];

/// The characters a font has a glyph for.
#[derive(Default, Clone, Debug)]
pub struct CharMap {
    chars: HashSet<u32>,
}

fn u16_at(data: &[u8], at: usize) -> Option<u16> {
    Some(u16::from_be_bytes(data.get(at..at + 2)?.try_into().ok()?))
}

fn u32_at(data: &[u8], at: usize) -> Option<u32> {
    Some(u32::from_be_bytes(data.get(at..at + 4)?.try_into().ok()?))
}

impl CharMap {
    /// The character map of a .ttf or .otf file; None when it is not a font or has no usable cmap subtable.
    pub fn parse(font: &[u8]) -> Option<CharMap> {
        let tables = u16_at(font, 4)? as usize;
        let cmap = (0..tables).find_map(|i| {
            let rec = 12 + 16 * i;
            (font.get(rec..rec + 4)? == b"cmap").then(|| u32_at(font, rec + 8))?
        })? as usize;
        let subtables = u16_at(font, cmap + 2)? as usize;
        let mut found = Vec::new();
        for i in 0..subtables {
            let rec = cmap + 4 + 8 * i;
            let key = (u16_at(font, rec)?, u16_at(font, rec + 2)?);
            let at = cmap + u32_at(font, rec + 4)? as usize;
            if let Some(rank) = PREFERRED.iter().position(|p| *p == key)
                && matches!(u16_at(font, at), Some(4 | 12))
            {
                found.push((rank, at));
            }
        }
        found.sort();
        let &(_, at) = found.first()?;
        let mut chars = HashSet::new();
        match u16_at(font, at)? {
            4 => read_format_4(font, at, &mut chars)?,
            _ => read_format_12(font, at, &mut chars)?,
        }
        Some(CharMap { chars })
    }

    /// True when the font has a glyph for this character. Line breaks, tabs and other controls draw nothing and
    /// count as covered.
    pub fn covers(&self, c: char) -> bool {
        c.is_control() || self.chars.contains(&(c as u32))
    }

    /// The characters of `text` the font cannot draw, in order of appearance, each once.
    pub fn missing(&self, text: &str) -> Vec<char> {
        let mut out: Vec<char> = Vec::new();
        for c in text.chars() {
            if !self.covers(c) && !out.contains(&c) {
                out.push(c);
            }
        }
        out
    }

    /// How many characters the font covers.
    pub fn len(&self) -> usize {
        self.chars.len()
    }

    /// True for a font without one mapped character (or a CharMap::default()).
    pub fn is_empty(&self) -> bool {
        self.chars.is_empty()
    }
}

/// Format 4: segments of the BMP, each with a delta or an offset into the glyph id array.
fn read_format_4(font: &[u8], at: usize, chars: &mut HashSet<u32>) -> Option<()> {
    let segs = u16_at(font, at + 6)? as usize / 2;
    let ends = at + 14;
    let starts = ends + 2 * segs + 2; // a reserved u16 sits between endCode and startCode
    let deltas = starts + 2 * segs;
    let offsets = deltas + 2 * segs;
    for s in 0..segs {
        let end = u16_at(font, ends + 2 * s)? as u32;
        let start = u16_at(font, starts + 2 * s)? as u32;
        let delta = u16_at(font, deltas + 2 * s)? as u32;
        let range_offset = u16_at(font, offsets + 2 * s)? as usize;
        for c in start..=end.min(0xFFFE) {
            let glyph = if range_offset == 0 {
                (c + delta) & 0xFFFF
            } else {
                // the offset counts from the offset's own place in the array (the spec's pointer arithmetic)
                let raw = u16_at(font, offsets + 2 * s + range_offset + 2 * (c - start) as usize)? as u32;
                if raw == 0 { 0 } else { (raw + delta) & 0xFFFF }
            };
            if glyph != 0 {
                chars.insert(c);
            }
        }
    }
    Some(())
}

/// Format 12: groups of consecutive characters on consecutive glyphs, all of Unicode.
fn read_format_12(font: &[u8], at: usize, chars: &mut HashSet<u32>) -> Option<()> {
    let groups = u32_at(font, at + 12)? as usize;
    for g in 0..groups {
        let rec = at + 16 + 12 * g;
        let (start, end, glyph) = (u32_at(font, rec)?, u32_at(font, rec + 4)?, u32_at(font, rec + 8)?);
        for c in start..=end.min(0x10FFFF) {
            if glyph + (c - start) != 0 {
                chars.insert(c);
            }
        }
    }
    Some(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIRA: &[u8] = include_bytes!("../shell/fonts/FiraMono-Medium.ttf");
    const READABLE: &[u8] = include_bytes!("../shell/fonts/AtkinsonHyperlegible-Regular.ttf");

    #[test]
    fn a_full_font_covers_accents_arrows_and_the_subtitle_marker() {
        let map = CharMap::parse(FIRA).expect("Fira Mono has a cmap");
        assert!(map.len() > 1000, "only {} characters", map.len());
        assert!(map.missing("Paramètres Échap Entrée → ↘ ▼ [Séttíñgs~~]").is_empty());
    }

    #[test]
    fn missing_lists_each_uncovered_character_once_in_order() {
        let map = CharMap::parse(READABLE).expect("Atkinson Hyperlegible has a cmap");
        assert!(map.covers('é') && map.covers('\n'));
        assert_eq!(map.missing("a ▼ 漢 ▼ b"), vec!['▼', '漢']);
    }

    #[test]
    fn not_a_font_is_none() {
        assert!(CharMap::parse(b"").is_none());
        assert!(CharMap::parse(b"definitely not a font file, just some bytes").is_none());
        assert!(CharMap::default().is_empty());
    }
}
