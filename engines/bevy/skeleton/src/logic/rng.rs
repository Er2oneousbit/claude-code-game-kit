// ---------------------------------------------------------------------------
// logic/rng.rs
// Purpose : A tiny seeded random number generator (xorshift64*): the same seed gives the same numbers on
//           every machine and every build, so bots, replays and generated levels repeat exactly.
// Usage   : let mut rng = Rng::new(seed);  rng.next_f32();  rng.range(-1.0, 1.0);  rng.below(6);
// Notes   : Not for security. Seed 0 is remapped (xorshift would stay at 0 forever). A crate such as rand
//           is fine too (write an ADR); this one has no dependencies and its sequence never changes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 { 0x9E37_79B9_7F4A_7C15 } else { seed },
        }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state ^= self.state >> 12;
        self.state ^= self.state << 25;
        self.state ^= self.state >> 27;
        self.state.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    /// Uniform in [0, 1).
    pub fn next_f32(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / (1u64 << 24) as f32
    }

    /// Uniform in [lo, hi).
    pub fn range(&mut self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.next_f32()
    }

    /// Uniform integer in [0, n); 0 when n is 0.
    pub fn below(&mut self, n: u32) -> u32 {
        if n == 0 { 0 } else { (self.next_u64() % n as u64) as u32 }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_same_seed_repeats_the_same_sequence() {
        let (mut a, mut b) = (Rng::new(42), Rng::new(42));
        for _ in 0..100 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
    }

    #[test]
    fn the_sequence_never_changes_between_builds() {
        // Pinned values: if this fails, every saved seed, replay and bot result changes meaning.
        let mut rng = Rng::new(1);
        assert_eq!(rng.next_u64(), 5_180_492_295_206_395_165);
    }

    #[test]
    fn floats_and_ranges_stay_inside_their_bounds() {
        let mut rng = Rng::new(7);
        for _ in 0..10_000 {
            let f = rng.next_f32();
            assert!((0.0..1.0).contains(&f));
            assert!((-2.0..3.0).contains(&rng.range(-2.0, 3.0)));
            assert!(rng.below(6) < 6);
        }
        assert_eq!(rng.below(0), 0);
    }

    #[test]
    fn seed_zero_still_produces_numbers() {
        let mut rng = Rng::new(0);
        assert_ne!(rng.next_u64(), 0);
    }
}

// {{FOOTER}}
