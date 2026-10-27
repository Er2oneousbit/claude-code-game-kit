# ADR 0003: The ghosts run a C# state machine, not a Unity Behavior graph

- Status: accepted
- Date: 2026-10-21

## Context
The concept asked for Unity's Behavior package. The kit's workflow has Claude write C# while humans edit visual assets
(docs/ENGINE_FLOW.md, "Claude and Unity"), and this example is built without the editor UI.

## Options considered
1. **Unity Behavior 1.0.16** (`com.unity.behavior`): graph-based behavior trees with a Blackboard. Checked in the package
   source: `BehaviorGraph.Graphs`, `BehaviorGraphModule.Root` wiring and the `Node` constructor are internal; graphs are
   compiled from an authoring asset made in the graph window. C# can add custom nodes, not build the graph.
2. **A finite state machine in C#** (SOP-14's first choice): five clear modes (patrol, suspicious, hunt, search, return),
   engine-free and unit tested.

## Decision
Option 2. The ghosts have a handful of modes, which is where SOP-14 says an FSM belongs, and it keeps the whole AI in
reviewable, tested code. The package was installed to check this and then removed.

## Consequences
- Good: `Assets/Scripts/Core/GhostBrain.cs`, EditMode tests for every transition, no editor-only assets.
- Bad / costs: no visual graph for a designer to tweak.
- What we would need to see to revisit this: a designer who wants to own the ghost logic in the editor (then use
  Behavior, with C# custom nodes for perception).
