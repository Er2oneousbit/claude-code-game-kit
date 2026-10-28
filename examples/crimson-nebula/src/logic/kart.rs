// ---------------------------------------------------------------------------
// logic/kart.rs
// Purpose : Arcade kart handling, one fixed tick at a time: throttle and brake toward a target speed, steering
//           that scales in with speed, a hold-to-drift slide that charges a mini boost, and the boost item.
// Usage   : kart.drive(&input, dt);   then race.rs resolves walls, bumps, items and laps
// Notes   : Motion is a velocity that blends toward the nose direction at GRIP per second (DRIFT_GRIP while
//           drifting), so karts slide a little in every turn and a lot in a drift. No physics engine: the race is
//           pure Rust, repeatable tick for tick, and fast enough for bots to race hundreds of times in a test.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::math::Vec2;

use super::math::{approach, wrap_angle};
use super::tuning::*;

/// What a driver (a person or a bot) asks for this tick.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct KartInput {
    /// -1 brake/reverse .. 1 full throttle.
    pub throttle: f32,
    /// -1 right .. 1 left (positive turns counterclockwise, like the track).
    pub steer: f32,
    pub drift: bool,
    pub use_item: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Item {
    Boost,
}

#[derive(Debug, Clone)]
pub struct Kart {
    pub pos: Vec2,
    /// Nose direction (rad, 0 = +x, counterclockwise positive).
    pub heading: f32,
    pub vel: Vec2,
    pub drifting: bool,
    pub drift_charge: f32,
    /// Seconds of boost left (item or mini boost).
    pub boost: f32,
    pub item: Option<Item>,
    /// Was use_item held last tick (items fire on the press, not while held).
    pub item_held: bool,
}

impl Kart {
    pub fn new(pos: Vec2, heading: f32) -> Self {
        Self {
            pos,
            heading,
            vel: Vec2::ZERO,
            drifting: false,
            drift_charge: 0.0,
            boost: 0.0,
            item: None,
            item_held: false,
        }
    }

    pub fn forward(&self) -> Vec2 {
        Vec2::from_angle(self.heading)
    }

    /// Speed along the nose (negative when reversing).
    pub fn speed(&self) -> f32 {
        self.vel.dot(self.forward())
    }

    /// One tick of driving. Returns true when the item was used this tick.
    pub fn drive(&mut self, input: &KartInput, dt: f32) -> bool {
        let throttle = input.throttle.clamp(-1.0, 1.0);
        let steer = input.steer.clamp(-1.0, 1.0);
        let mut speed = self.speed();

        // Item: fires on the press
        let mut used = false;
        if input.use_item && !self.item_held && self.item == Some(Item::Boost) {
            self.item = None;
            self.boost = self.boost.max(BOOST_TIME);
            used = true;
        }
        self.item_held = input.use_item;

        // Speed
        if self.boost > 0.0 {
            speed = approach(speed, TOP_SPEED * BOOST_SPEED_MULT, BOOST_ACCEL * dt);
            self.boost = (self.boost - dt).max(0.0);
        } else if throttle > 0.0 {
            let target = TOP_SPEED * throttle;
            let rate = if speed > target { COAST_DRAG } else { ACCEL };
            speed = approach(speed, target, rate * dt);
        } else if throttle < 0.0 {
            speed = if speed > 0.0 {
                approach(speed, 0.0, BRAKE * -throttle * dt)
            } else {
                approach(speed, -REVERSE_SPEED, ACCEL * 0.5 * dt)
            };
        } else {
            speed = approach(speed, 0.0, COAST_DRAG * dt);
        }

        // Drift: starts and holds while the button is down, the kart is fast and steering
        let was_drifting = self.drifting;
        self.drifting = input.drift && speed >= DRIFT_MIN_SPEED && (was_drifting || steer.abs() > 0.3);
        if self.drifting {
            self.drift_charge += steer.abs() * dt;
        } else if was_drifting {
            if self.drift_charge >= DRIFT_CHARGE_MIN {
                self.boost = self.boost.max(MINI_BOOST_TIME);
            }
            self.drift_charge = 0.0;
        }

        // Velocity in the kart's frame before it turns: forward speed (just updated) plus sideways slip
        let slip = self.vel.dot(self.forward().perp());
        let moving = self.forward() * speed + self.forward().perp() * slip;

        // Steering: none when stopped, full from TURN_FULL_AT; reversing turns the other way like a car
        let scale = (speed.abs() / TURN_FULL_AT).min(1.0) * speed.signum();
        let bonus = if self.drifting { DRIFT_TURN_BONUS } else { 1.0 };
        self.heading = wrap_angle(self.heading + TURN_RATE * steer * scale * bonus * dt);

        // The motion keeps going its old way; seen from the turned nose part of it is now slip, which grip
        // scrubs off (fast with grip, slowly while drifting: the slide)
        let grip = if self.drifting { DRIFT_GRIP } else { GRIP };
        let (fwd, side) = (self.forward(), self.forward().perp());
        let new_speed = moving.dot(fwd);
        let new_slip = moving.dot(side) * (-grip * dt).exp();
        self.vel = fwd * new_speed + side * new_slip;
        self.pos += self.vel * dt;
        used
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 1.0 / 60.0;

    fn run(kart: &mut Kart, input: KartInput, ticks: usize) {
        for _ in 0..ticks {
            kart.drive(&input, DT);
        }
    }

    fn full() -> KartInput {
        KartInput {
            throttle: 1.0,
            ..Default::default()
        }
    }

    #[test]
    fn full_throttle_reaches_top_speed_and_no_more() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        run(&mut kart, full(), 600);
        assert!((kart.speed() - TOP_SPEED).abs() < 0.05, "speed {}", kart.speed());
        assert!(kart.pos.x > 100.0 && kart.pos.y.abs() < 0.01);
    }

    #[test]
    fn steering_left_turns_counterclockwise() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        run(&mut kart, full(), 120);
        let steer = KartInput { steer: 1.0, ..full() };
        run(&mut kart, steer, 30);
        assert!(kart.heading > 0.5, "heading {}", kart.heading);
        assert!(kart.pos.y > 0.0);
    }

    #[test]
    fn a_standing_kart_cannot_spin_on_the_spot() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        let steer = KartInput {
            steer: 1.0,
            ..Default::default()
        };
        run(&mut kart, steer, 60);
        assert_eq!(kart.heading, 0.0);
    }

    #[test]
    fn the_boost_item_fires_once_per_press_and_raises_top_speed() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        run(&mut kart, full(), 600);
        kart.item = Some(Item::Boost);
        let press = KartInput {
            use_item: true,
            ..full()
        };
        assert!(kart.drive(&press, DT));
        assert!(!kart.drive(&press, DT), "holding the button does not fire again");
        run(&mut kart, full(), 40);
        assert!(kart.speed() > TOP_SPEED * 1.2, "speed {}", kart.speed());
        run(&mut kart, full(), 300);
        assert!(kart.speed() <= TOP_SPEED + 0.5, "the boost wears off");
    }

    #[test]
    fn a_long_drift_charges_a_mini_boost_and_a_short_one_does_not() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        run(&mut kart, full(), 300);
        let drift = KartInput {
            steer: 1.0,
            drift: true,
            ..full()
        };
        run(&mut kart, drift, 10);
        run(&mut kart, full(), 1);
        assert_eq!(kart.boost, 0.0, "0.17 s of drift is not enough");
        run(&mut kart, full(), 120);
        run(&mut kart, drift, 70);
        run(&mut kart, full(), 1);
        assert!(kart.boost > 0.0, "a 1.2 s drift gives a mini boost");
    }

    #[test]
    fn brakes_stop_the_kart_then_it_reverses() {
        let mut kart = Kart::new(Vec2::ZERO, 0.0);
        run(&mut kart, full(), 300);
        let brake = KartInput {
            throttle: -1.0,
            ..Default::default()
        };
        run(&mut kart, brake, 60);
        assert!(kart.speed() < 0.0 && kart.speed() >= -REVERSE_SPEED);
    }
}
