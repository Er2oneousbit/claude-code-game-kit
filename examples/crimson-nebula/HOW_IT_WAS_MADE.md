# How Crimson Nebula was made

The kit's Bevy example, built the same day the Bevy overlay was, to put the overlay through a real game. One Claude Code
session (Claude Opus 5.5) on Windows 11 with Rust 1.99.1 and Bevy 0.20.0, 2026-10-28. A player asked for Bevy support
after the kit's first public release; the user asked for a racing game with it, and answered the kit's `make-a-game`
interview one question at a time. Claude did the rest by following the kit's documents and tools, and recorded every
place the kit fell short. Each gap was fixed **in the kit** during the run and pulled into the game with
`new_game.py --upgrade`, the same way any kit user gets updates.

## The rule
Allowed: what a kit user has after scaffolding (docs, SOPs, skills, `tools/`, the overlay's pinned crates) plus the
sources the kit's resource lists name. Not allowed: outside scripts or tools. Exceptions are listed at the end.

## 1. Interview and plan (`make-a-game`)
The user's answers, one prompt each: a kart racer with items, feels most like Mario Kart, the twist is that **the track
changes each lap**, the core action is reading the track, the hook is unlocks, only 1st place unlocks, a 3D chase
camera, neon night, "me and friends; frantic", solo against AI first, the first toy is "track changes plus one item
(boost)", split-screen and online out of scope. Claude drafted the plan (three pillars: read the change, close and loud,
neon tells you everything), the user said "Looks good, build it", and chose to make it kit example #10.

## 2. Scaffold and health check (FIRST_HOUR 0 to 5 min)
```
python scripts/new_game.py --name "Project_Crimson_Nebula" --engine bevy --dest ../crimson-nebula --git-init
python tools/dev.py doctor
```
A short path on purpose (cargo and MSVC are happier there), and `CARGO_TARGET_DIR` shared with the overlay's own test
projects so Bevy compiled once (the first build took 14.5 minutes). The plan went into `docs/GDD.md`, the tunables
into `src/logic/tuning.rs`.

## 3. Build (FIRST_HOUR fast lane, SOP-01, SOP-14)
- **Engine-free race first, with tests:** `track.rs` (a loop of 24 control points, about 1083 m; two shortcuts that
  peel off the loop; two lane closures that taper in), `kart.rs`, `race.rs` (countdown, walls, bumps, items, laps, the
  seeded change schedule, finish), `bots.rs`, `tuning.rs`. Nothing in `src/logic` imports Bevy.
- **The change schedule:** lap 1 never changes (FTUE lesson 1: just drive and grab a boost), lap 2 always closes a lane
  with a long warning (lesson 2), lap 3 is any other change. The warning starts when the leader is `WARN_TIME` (2 s) at
  its current speed plus `WARN_LEAD` (30 m) away, so a fast leader still gets two seconds.
- **Rivals (SOP-14):** steering at a lookahead point along a planned path (the loop at an offset, or a shortcut),
  braking for bends, passing. Technique: plain rules, no FSM needed; the three rivals differ only in how they read the
  track (`Style`: Reader reacts to the warning, Late to a live change, Ignorer never; it only steers out of a barrier
  after a bonk).
- **Bevy side:** the race steps in `FixedUpdate` at 60 Hz and prints markers (`RACE_GO`, `LAP`, `CHANGE_WARN`,
  `CHANGE_LIVE`, `FINISH`, `RACE_OVER`). The view is added only with a window: ribbons and walls as meshes built from the
  track, karts from a few shapes (body, wheels, driver), emissive color plus `Hdr` and `Bloom` for the neon, a chase
  camera with a field-of-view kick on boost, a HUD, results, Enter for a new track. Every Bevy API was checked in the
  0.20 source under `~/.cargo/registry` first (ENGINE.md gotcha 1): `TextLayout::justify`, `GlobalAmbientLight`,
  `bevy::camera::Hdr` and the mesh imports all differ from older examples.

## 4. What the kit's checks caught
The bot pair (SOP-14 step 6: a bot that reads the changes must beat one that ignores them) did most of the work. Every
row was found by tracing bots, not by guessing.

| Caught by | Problem | Fix |
|---|---|---|
| `kart::tests` | Velocity blended toward the facing direction every tick: the blend ate the acceleration | Forward speed and sideways slip kept apart; grip scrubs the slip |
| Bot pair | Reading barely helped: hitting a closure cost almost nothing | Contact with a barrier zaps once per `ZAP_COOLDOWN` (speed x0.45) |
| Bot pair | Bots stalled head-on against the barrier face | The closure tapers in over `CLOSURE_TAPER` (15 m) |
| Bot pair | The Ignorer dodged perfectly at the last moment | It reacts only after a bonk, from inside the barrier |
| Bot pair | A fast leader could never take a shortcut: the warning came too late | Warning distance from the leader's speed (above) |
| Bot trace | Shortcuts met the loop at 90 degrees; bots crashed into the corner | A layout search over the control points: shortcuts branch off over 35 m |
| Bot trace | Karts side by side glued together (a bump scaled both velocities) | Bumps exchange only the closing velocity |
| Bot trace | Progress jumped at the start line and where a shortcut overlaps the loop | Signed distance along the loop; shortcut membership is sticky |
| Bot trace | Bots cut corners on shortcuts, slid wide on bends | Shorter lookahead on shortcuts; brake for the curvature ahead |
| `dev.py doctor` link check | `docs/ARCHITECTURE.md` named files by short paths | Paths relative to the project root |
| `dev.py check` (clippy) | Unused values, identical branches | Fixed |
| `tests/headless.rs` | A test read the race before startup had made it | The race is made in `PreStartup` |

## 5. Kit gaps found and fixed (kit 0.5.0)
1. **`smoke --record` always started at frame 1.** The lane closing happens about 70 s into a race: hundreds of frames
   nobody wanted. Added `--record-from N` to the Bevy overlay.
2. **3D games got 2D art instructions.** FIRST_HOUR's fast lane and the `make-a-game` "crude on purpose" warning named
   only pixel sprites from `pixel_sprite.py`. Both now give the 3D floor too: figures built from a few shapes, never
   bare boxes. Synced into every example.
3. **A process slip, not a kit gap:** the interview was first asked as a batch of text questions. The skill already
   says one interactive question at a time; Claude was working from a stale copy.

## 6. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` | rustfmt and clippy clean |
| `python tools/dev.py test` | 40 tests: 36 unit (track, kart, race, bots, rng), 4 headless races through the real `GamePlugin` |
| Bot pair (`bots::tests`) | reading wins 20 of 20 seeds by 0.4 to 1.9 s; reacting at all beats ignoring |
| `smoke --frames 9000 --until RACE_OVER -- --autoplay reader --seed 3` | a full race headless; the player's bot wins in 117.31 s; the same seed replays tick for tick |
| `smoke --screenshot` / `--record --record-from` | the GIF above: warning banner, then the barrier |
| `python tools/dev.py run` | boots in a window (Vulkan), no errors |
| `python tools/doctor.py`, `check_links.py`, `publish_check.py` | healthy, no broken references; publish_check's one FAIL is the missing root LICENSE, which examples take from `../LICENSE.md` |

Balance tool: `cargo test --lib balance_report -- --ignored --nocapture` prints each seed's schedule and what reading
it gained.

## 7. Outside the kit (be honest)
- The shortcut layout came from a throwaway search script (try control-point fractions, keep the ones whose branch
  angle stayed shallow). The result is plain data in `track.rs`.
- Rust was installed with rustup during the run (the kit's `doctor` names it; it does not install it).
- **No human playtest yet.** The toy is built and the bot pair holds, but pillar 1 ("I saw it coming") and the zap's
  sting are open questions in `docs/HANDOFF.md`. The first playtest is ROADMAP's Now item.
