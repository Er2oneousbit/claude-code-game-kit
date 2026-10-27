# SOP-10: Performance

## Goal
Hit frame-time and memory budgets with evidence, not hunches.

## Steps
1. **Set budgets** in `ARCHITECTURE.md`: target FPS (and frame time in ms), min spec hardware, memory ceiling, load time target.
   Example: 60 FPS means 16.6 ms per frame total.
2. **Measure first.** Use the engine profiler (see `docs/ENGINE_FLOW.md`). Record a baseline with the scene or level used.
3. **Find the top offender.** Fix only the biggest item. Remeasure. Repeat. Stop when the budget is met.
4. **Common culprits:** per-frame allocations, too many draw calls, overdraw, unbounded entity counts, physics on everything,
   expensive per-frame searches, loading in the main thread, unpooled spawn/despawn, huge textures, log spam.
5. **Record results** in the `docs/ARCHITECTURE.md` Budgets table ("Measured on", "Last measured"), and in the PR/commit message when there is one: before, after, where measured.
6. **Guard it.** Add a smoke-level stress scene or a frame-time log to catch regressions. Measure it on the production
   build at every milestone, not only when the game feels slow (tip, E54): small per-feature costs pile up quietly. One
   game's audit found a map screen at about 24 ms of script per frame (under 4x CPU throttle) and got it to about 2 ms.

## Reported examples (E04, one creator, unverified)
- **One quality slider can halve the frame rate.** Shadow softness from low to max took a scene from over 100 FPS to about 40. Expose such settings in a debug panel, measure each, and ship sensible defaults plus graphics options.
- **Trees:** a hero birch of 34,000 triangles was cut to about 2,800 (maple about 1,500) by baking groups of leaves into color and normal textures on flat planes while keeping the trunk and main branches as real geometry.
- **Grass:** repeating many small grass meshes with MultiMesh ran fine but looked pasted on. Painted blade textures on a few simple planes looked softer and blended better with simple geometry.

## Done when
- Budget met on the min-spec target, numbers recorded, no speculative optimizations left behind.

## Common mistakes
- Optimizing without a profile.
- Measuring in the editor or a debug build and treating it as release truth.
- Trading readability for micro-gains in non-hot code.
