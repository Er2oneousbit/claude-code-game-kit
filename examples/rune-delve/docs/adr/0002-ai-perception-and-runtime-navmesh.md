# ADR 0002: AI Perception for the orcs' senses, a runtime NavMesh for movement

- Status: accepted
- Date: 2026-10-22

## Context
Orcs sleep until they see the mage (a sight cone, blocked by walls and columns) or hear a bolt, then chase her around
columns and through opened gates. SOP-14 splits AI into perception, decision and movement; the decision is a tested C++
state machine (`RDOrcBrain`). The level is built at runtime from data, so nothing is baked into the map.

## Options considered
1. **Unreal's AI Perception** (`UAIPerceptionComponent` with sight and hearing configs on the AI controller) and the
   **NavMesh** with `RuntimeGeneration=Dynamic`, bounded by one NavMeshBoundsVolume placed by the content script.
2. **Own line traces and grid A***, as the web and C++ examples do.

## Decision
Option 1: both are engine features a Unreal developer will meet, configurable from C++ (sense radius and angle from the
tunables) and from `Config/DefaultEngine.ini`.

## Consequences
- Good: sight respects the same box colliders that block bolts and walking; bolts make real noise
  (`UAISense_Hearing::ReportNoiseEvent`); opening a gate updates the NavMesh (`UpdateComponentInNavOctree`).
- Bad / costs: perception only counts inside the orc's own room (a rule in `ARDOrc`), so hearing does not wake the next
  room through a wall; the NavMesh builds a moment after the map loads (the boot smoke test waits for it).
- The NavMesh builds its tiles on worker threads, in real time, which is not deterministic: replays under `-fixedfps`
  finish every pending tile before the actors of a frame tick (`ARDGameMode::FinishNavBuild`), and nothing that moves
  during a delve may affect navigation (the bolt does not; `docs/TROUBLESHOOTING.md`, #8). Path following and the
  character movement tick in the same group with no order between them in the engine; the orc controller pins the
  order (path following first), or the orc brakes for a frame now and then.
- What we would need to see to revisit this: none expected.
