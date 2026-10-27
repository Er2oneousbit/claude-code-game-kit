# ADR 0002: Unity AI Navigation for the ghosts and the bots

- Status: accepted
- Date: 2026-10-21

## Context
Ghosts patrol, chase and search around crypts and gravestones; the autoplay bots need paths too. SOP-14's Unity row
points at the AI Navigation package (NavMeshSurface, NavMeshAgent).

## Options considered
1. **AI Navigation 2.0.16** (`com.unity.ai.navigation`, Unity's official package): runtime NavMesh bake from colliders,
   NavMeshAgent for movement, `NavMesh.CalculatePath` for the bots.
2. **Own grid A*** (as the kit's web and C++ examples do): no package, but re-implements what Unity ships.

## Decision
Option 1. The level is built at runtime, and `NavMeshSurface.BuildNavMesh()` bakes it from the same box colliders that
block the keeper and the ghosts' sight.

## Consequences
- Good: one source of truth for "where can you walk"; agents avoid each other for free.
- Bad / costs: `NavMesh.CalculatePath` does not snap its ends to the mesh (`SetDestination` does): sample both ends with
  `NavMesh.SamplePosition` first, or every path is invalid (found the hard way, see docs/TROUBLESHOOTING.md).
- What we would need to see to revisit this: none expected.

## Notes
Version from Unity's package registry, **verified** by installing it on 6000.6.6f1 (2026-10-21).
