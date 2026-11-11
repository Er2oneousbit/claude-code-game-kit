// ---------------------------------------------------------------------------
// dotwork/player.rs
// Purpose : The frame clock of a Dotwork animation: which frame shows after a given time, from each frame's own
//           duration (holds matter: an attack's wind-up and hit-stop), looping or holding the last frame.
// Usage   : let mut p = FramePlayer::new(durations, looping);   if p.advance(dt) { show frame p.frame() }
// Notes   : Engine-free, so tests check it without a window. A frame shorter than MIN_FRAME counts as MIN_FRAME,
//           so a manifest with a zero duration cannot spin the loop. A non-looping clip stops on its last frame and
//           reports finished() (attacks, deaths, one-shot effects).
//
// Pseudocode:
//   advance(dt): unless finished, add dt -> while the time is past this frame's duration: take it off, step to the
//   next frame (wrap when looping; on the last frame of a one-shot clip stop and mark finished)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::time::Duration;

/// The shortest frame the player steps through (a guard against zero durations).
pub const MIN_FRAME: Duration = Duration::from_millis(1);

#[derive(Debug, Clone, PartialEq)]
pub struct FramePlayer {
    durations: Vec<Duration>,
    looping: bool,
    frame: usize,
    elapsed: Duration,
    finished: bool,
}

impl FramePlayer {
    pub fn new(durations: Vec<Duration>, looping: bool) -> Self {
        let durations = durations.into_iter().map(|d| d.max(MIN_FRAME)).collect();
        FramePlayer {
            durations,
            looping,
            frame: 0,
            elapsed: Duration::ZERO,
            finished: false,
        }
    }

    /// The frame showing now (0 for an empty clip).
    pub fn frame(&self) -> usize {
        self.frame
    }

    /// A one-shot clip reached its last frame's end.
    pub fn finished(&self) -> bool {
        self.finished
    }

    pub fn looping(&self) -> bool {
        self.looping
    }

    /// Each frame's duration, in frame order.
    pub fn durations(&self) -> &[Duration] {
        &self.durations
    }

    /// The clip's length: the sum of its durations.
    pub fn length(&self) -> Duration {
        self.durations.iter().sum()
    }

    /// Back to the first frame.
    pub fn restart(&mut self) {
        self.frame = 0;
        self.elapsed = Duration::ZERO;
        self.finished = false;
    }

    /// Moves the clock on by `dt`. True when the frame changed.
    pub fn advance(&mut self, dt: Duration) -> bool {
        if self.finished || self.durations.is_empty() {
            return false;
        }
        let start = self.frame;
        self.elapsed += dt;
        while self.elapsed >= self.durations[self.frame] {
            if self.frame + 1 < self.durations.len() {
                self.elapsed -= self.durations[self.frame];
                self.frame += 1;
            } else if self.looping {
                self.elapsed -= self.durations[self.frame];
                self.frame = 0;
            } else {
                self.elapsed = self.durations[self.frame];
                self.finished = true;
                break;
            }
        }
        self.frame != start
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    #[test]
    fn holds_change_how_long_a_frame_shows() {
        // the golden hero's walk_s: holds 1, 1, 2, 1 at 8 fps
        let mut p = FramePlayer::new(vec![ms(125), ms(125), ms(250), ms(125)], true);
        assert_eq!(p.length(), ms(625));
        assert!(!p.advance(ms(100)));
        assert!(p.advance(ms(30)));
        assert_eq!(p.frame(), 1);
        p.advance(ms(200)); // 130 + 200 = 330 ms: frame 2 runs from 250 to 500
        assert_eq!(p.frame(), 2);
        p.advance(ms(200)); // 530 ms: frame 3
        assert_eq!(p.frame(), 3);
        p.advance(ms(100)); // 630 ms: wrapped to frame 0
        assert_eq!(p.frame(), 0);
        assert!(!p.finished());
    }

    #[test]
    fn a_one_shot_clip_holds_its_last_frame() {
        let mut p = FramePlayer::new(vec![ms(100), ms(200), ms(100)], false);
        p.advance(ms(390));
        assert_eq!((p.frame(), p.finished()), (2, false));
        p.advance(ms(20));
        assert_eq!((p.frame(), p.finished()), (2, true));
        assert!(!p.advance(ms(1000)));
        assert_eq!(p.frame(), 2);
        p.restart();
        assert_eq!((p.frame(), p.finished()), (0, false));
    }

    #[test]
    fn zero_durations_and_big_steps_cannot_hang() {
        let mut p = FramePlayer::new(vec![Duration::ZERO, Duration::ZERO], true);
        p.advance(Duration::from_secs(5));
        assert!(p.frame() < 2);
        let mut empty = FramePlayer::new(Vec::new(), true);
        assert!(!empty.advance(ms(10)));
    }
}
