# SOP-14: Game AI (enemies, NPCs, companions)

## Goal
Characters that make readable, believable decisions, run every frame on the player's machine for free, and can be tested
and tuned like any other system. "Game AI" here means the classic techniques shipped games use (F20). Language models
are a different topic with different costs: `SOP-15`.

Run it with `/game-ai`.

## 1. Three layers, built in this order (F21)
| Layer | Question it answers | Typical tool |
|---|---|---|
| **Perception** | What does this character know? (sees the player, heard a noise, is in light) | Distance and angle checks, raycasts or line of sight on the grid, engine perception components |
| **Decision** | What does it want to do now? | One of the techniques in step 2 |
| **Movement** | How does it get there? | Engine navigation (navmesh, agents) or A* on a grid, then steering for smooth motion |

Keep them separate in code: decision logic reads perception results and outputs an intent ("chase", "flee to X"),
movement turns the intent into velocity. Each layer can then be tested and swapped alone.

## 2. Pick the simplest decision technique that works (F20)
| Technique | Use when | Starts to hurt when | Shipped example | Read |
|---|---|---|---|---|
| **Scripted / timers** | A pattern, not a mind (boss phases, a turret) | Players need it to react | Countless bosses | |
| **Finite state machine (FSM)** | A handful of clear modes: patrol, chase, search, return | States multiply and transitions turn into a web | Pac-Man ghosts' modes | Nystrom "State"; Graham FSM (E39) |
| **Hierarchical FSM / statecharts** | An FSM with shared sub-states (combat contains attack, reload, cover) | Logic needs priorities more than modes | Many action games | E39 |
| **Behavior tree (BT)** | Many behaviors with clear priorities and fallbacks, reusable sub-trees | Every tick re-checks a big tree, or designers fight priority order | Halo 2 (Isla, GDC 2005) | Champandard "BT Starter Kit" (E39) |
| **Utility AI** | Several options compete and the best one depends on many inputs (hunger, distance, fear, health) | Scores need constant hand-tuning, behavior gets hard to predict | The Sims | Graham "Utility Theory" (E39) |
| **Planners (GOAP, HTN)** | Characters must chain actions toward goals in changing situations | You do not need multi-step plans (most games do not) | F.E.A.R. (GOAP) | Orkin GDC 2006; Humphreys HTN (E39) |
"Behavior Selection Algorithms: An Overview" (Game AI Pro, E39) compares them all and is the best single read.

Rules:
- Start with an FSM. Move up the table only when a named problem appears, and record the move in an ADR (`/adr`).
- Steering behaviors (seek, flee, arrive, separation) and boids are a **movement** layer, not a decision technique.
  Combine them with any row above.

## 3. Make it a system like any other
- **Engine-free core:** decision logic and grid pathfinding are pure functions or plain classes with no engine imports, so
  unit tests run instantly (`SOP-09`). The engine side only gathers perception and applies movement.
- **Tunables in one place:** sight range, speeds, score weights, timers. Never literals inside AI code (`SOP-01`).
- **Deterministic:** seed every random choice from a project RNG. A bug you can replay is a bug you can fix.
- **Budget the cost:** decide every few frames or on events, not every frame for every character; spread path searches
  across frames when there are many agents. Measure first (`SOP-10`).
- **Readable on screen:** every state or top action shows in animation, color, sound or a speech bubble. If players
  cannot read it, they experience it as random or unfair. Tell is half the design.

## 4. See what it thinks (F22)
Build the debug view before the second behavior. Minimum: current state or top-scoring action above each character,
its path, its perception range. Engine tools:

| Engine | Built-in AI debugging |
|---|---|
| Godot | Debug menu > **Visible Navigation** at runtime; `NavigationServer2D/3D.set_debug_enabled(true)` from script (debug builds) |
| Unreal | **Gameplay Debugger**: apostrophe key (`'`) or the `EnableGDT` cheat; numpad switches Navmesh, Behavior Tree, EQS, Perception. **P** in the viewport shows the navmesh |
| Unity | Behavior package: live debugging of the graph in Play mode; NavMesh shown in the Scene view |
| Web, C++ | Your own: draw paths and labels from a debug flag (`?debug` on web, `--debug` on C++) |
| Web 3D (Three.js) | Your own, behind `?debug`: `THREE.Line` for paths, a flat fan mesh for the sight cone (cut by the same line-of-sight test the AI uses), `EdgesGeometry` outlines for collision boxes, state text in the HTML HUD |
| RPG Maker MZ | Your own, from a plugin: log the state to the console (F8 in a Playtest) or draw it on a Sprite behind a debug switch **(verify F8)** |

## 5. Engine notes
| Engine | Navigation | Decision tools | Watch out |
|---|---|---|---|
| **Godot 4.7** | `NavigationRegion2D/3D` + `NavigationAgent2D/3D` (E36) | No built-in gameplay BT or FSM (the AnimationTree state machine is for animation only) **(verify)**. Add-ons: LimboAI (BT + HSM, MIT), Beehave (BT, MIT), Godot State Charts (MIT) (E40) | Path queries on the first physics frame come back empty: defer them **(verify for your version)**. The agent never moves the node: call `get_next_path_position()` each physics frame and move it yourself. Avoidance needs `set_velocity()` and the `velocity_computed` signal |
| **Unreal 5.8** | NavMeshBoundsVolume, RecastNavMesh, static/dynamic generation (E37) | Behavior Trees + Blackboard, StateTree (enable the StateTree and GameplayStateTree plugins), EQS for "find the best spot" queries, AI Perception on the AIController | StateTree's maturity label **(verify for your version)**; MassEntity is marked experimental |
| **Unity 6** | AI Navigation package (NavMeshSurface, NavMeshLink) (E38) | Behavior package (`com.unity.behavior`, behavior graphs, Blackboard, free). Graphs are wired in the editor's graph window: in 1.0.16 the graph modules and node constructors are internal, so C# can add custom nodes but not build a graph (K01). Code-only: an FSM or BT in C# | OffMeshLink is deprecated: use NavMeshLink. Package versions above were read for 6000.3 **(verify on yours)** |
| **Web (Phaser 4)** | None built in **(verify)**. Small grids: write A* in `src/core` (about 60 lines, testable); libraries: easystarjs, PathFinding.js (MIT, both with no recent release) (E40) | Write it: an FSM or utility scorer is a few dozen lines of TypeScript | `phaser-navmesh` declares Phaser 3 as its peer dependency **(verify before using on Phaser 4)** |
| **Web 3D (Three.js r186)** | None built in **(verify)**. Flat levels: grid A* in `src/core` over building boxes (the Courier Dash example). Navmesh: `@recast-navigation/three` (Recast/Detour for the web, MIT, active), `three-pathfinding` (MIT, last release 2024) (E40) | Write it: an FSM is a few dozen lines of TypeScript. Library: `yuka` (steering, FSM, goal-driven agents, MIT, last release 2022) (E40) | Keep perception in `src/core` against simple shapes (boxes, circles), not raycasts into render meshes: testable without a GPU, and what the debug view draws is what the AI uses. Add any library with an ADR **(verify versions)** |
| **C++ / SDL2** | Recast/Detour (Zlib, vcpkg port `recastnavigation`) or your own A* on a grid | BehaviorTree.CPP (MIT, vcpkg port `behaviortree-cpp`) for BTs; an FSM needs no library (E40) | Add ports to the project's vcpkg manifest with an ADR |
| **RPG Maker MZ** | Tile passability (`Game_Map.isPassable`) and the built-in step toward a target for events (`moveTowardCharacter`, short range) **(verify)**; longer paths: your own A* over the map in the engine-free plugin | None built in beyond event pages and conditions. An FSM or utility scorer in the engine-free plugin, tested in Node; the glue plugin moves `Game_Event`s | Logic in events is hard to test: keep decisions in the rules plugin and let events only call commands (the kit's Lockpick MZ example keeps every rule out of MZ) |

## 6. Test it
1. **Unit tests** for the decision core: given these inputs, this state or score wins. One test per rule you would
   hate to break ("never chases into light", "returns home after losing the player for 3 s").
2. **Pathfinding tests** on tiny hand-made grids: straight line, around a wall, no path, start equals goal.
3. **Scenario run:** an autoplay or scripted-input mode that plays a level and logs markers (`CAUGHT`, `ESCAPED`);
   the smoke test or a bot run checks them. Seeded, so a failure replays exactly.
   Run it as a **pair** that tests a pillar: a bot that plays the way the design wants must win, a bot that ignores the
   mechanic must lose (F32). Play **many seeds and assert a gap**, not one seed and not an exact count: 12 seeds swung by 5 wins
   after a 1 m layout change in the kit's tank example; 40 seeds and "wins at least X, the other at most Y" held (K01).
   With the rules engine-free and a fixed time step, the whole pair runs as a unit test in seconds.
   Assert only gaps the bots can perceive: bots that see in meters are not slowed by darkness, so "careful beats
   never lighting the lantern" was a coin flip for them once the dark got darker; log such a gap and judge it by
   playtest (K01: Graveyard Shift asserts it on its hand-made yard only).
4. **Saboteur mode** (tip, E54): the same bot, told to break the game instead of win it: arbitrage loops, softlocks,
   rewards paid twice, places it cannot leave. Run it at each milestone; every find becomes a regression test.
   A player's exploit is a find too: measure how many levels it breaks before choosing the fix, then keep it in the
   checks so it cannot come back (tip, E60: one trick beat 33 of 60 levels; a no-draw zone around the target fixed it).
5. **Every hand-made level passes its own pair** (tip, E60): its intended solution wins, sloppy copies of that solution
   still win (a player's hand is not exact), and a library of lazy generic answers loses. Mirrored levels double the
   check for free. It needs the rules to run headless, like the scenario pair; a level a lazy answer beats is not done.
6. **Playtest for fairness:** a catch the player could not see coming is a bug, whatever the code says (`SOP-03`).
   Bots can show a milestone is no worse than the last one; only a person can say it is fun (tip, E54).

## Worked examples (the kit's own, K01)
| Example | Technique | What the scenario pair caught |
|---|---|---|
| Ghost Lantern (web) | Utility AI, A* | Twice inverted: ghosts slower than the player made the lantern pointless; dim light repelled ghosts at point blank. Fixed with numbers |
| Courier Dash (web 3D) | FSM, grid A* | The robot spotted a courier who had not moved yet: perception stays off until the run starts, like the clock |
| Scrap Tanks (C++) | Behavior tree | Charging beat fighting from cover 9 of 12 runs: raiders kept their guns on the player while flanking, so whoever rounded a corner fired first. With the gun pointing where they drive until FIRE, cover won 25 of 40, charging 11 of 40 (10 before the 2026-10 review fixes) |
| Graveyard Shift (Unity) | FSM, NavMesh | The careful lantern bot was the worst of three: a dark keeper, once spotted, could never shake a hunt, and a catch ended the night. With hunts that tire and a catch that costs a soul, over 8 seeds: careful 44, always dark 40, always lit 23 (careful's lead over dark is thin, a playtest question) |
| Rune Delve (Unreal) | FSM, AI Perception, NavMesh, GAS | A ward that outlasted the orc's wind-up blocked even when raised early, so spamming it worked: with the ward window shorter than the wind-up, the timing bot clears 3 of 8 delves (5 before the 2026-10 review made the ward block one swing) and the spamming bot none (its wards met no swing in any run) |
Lessons that apply to any game:
- **An AI that is always aimed erases cover and positioning.** Make aiming a state with a visible tell (a turret swing, a
  wind-up); that moment is the player's advantage and their cue.
- **Sight and a clear shot are different checks.** An agent that sees past an edge but cannot hit will wait forever: pick
  spots by the shot, not by the view.
- **When the mechanic is a toggle, test three bots:** always on, always off, and used well, on one shared movement brain.
  "Used well" must beat both; if it only beats one, the toggle is a rule, not a choice.
- **A defensive window must be shorter than the attack's telegraph,** or raising it early works as well as timing it,
  and the skill you meant to test disappears.
- **A chase that never ends makes any mistake fatal**, and then the cautious play loses to the bold one. Give pursuers a
  limit (they tire, lose interest, return) and make getting caught cost time rather than the run.

## Done when
- Perception, decision and movement are separate; the decision core has unit tests.
- Every tunable is in one place; random choices are seeded.
- The debug view shows state or scores, paths and perception.
- A playtest note says players could predict what the AI was about to do.

## Common mistakes
- Starting with a behavior tree or a planner for three states. An FSM would have shipped yesterday.
- Mixing pathfinding and decisions in one `update()` so neither can be tested.
- AI that is perfect: instant reactions and perfect aim feel like cheating. Add reaction delays and misses on purpose.
- No debug view, so every "why did it do that?" becomes guesswork.
- Asking a language model to run enemy behavior. Slow, costly and unpredictable for this job (see `SOP-15`).
