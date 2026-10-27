# ADR 0001: Built-in render pipeline, the legacy Input Manager, immediate-mode HUD

- Status: accepted
- Date: 2026-10-21

## Context
The project was created headless (`Unity -batchmode -createProject`, the adopt-first route in docs/ENGINE.md): Unity 6.6
gives the Built-in Render Pipeline and the Input Manager. The Unity ENGINE.md asks for an ADR on render pipeline, input
and UI choices. The slice needs night lighting, keyboard and gamepad, and a small HUD, all built from code.

## Options considered
1. **Keep the defaults** (Built-in RP, `Input.GetAxisRaw` with the default axes, `OnGUI` HUD): nothing to install,
   everything in C#, works headless. Costs: legacy input and IMGUI are older APIs; IMGUI does not show in camera captures.
2. **URP + Input System + UI Toolkit**: modern, better looking. Costs: three packages, renderer assets and UI documents
   (assets a human usually edits), more to set up headless.

## Decision
Option 1 for the slice: the smallest set that a code-only workflow can drive and test.

## Consequences
- Good: no packages for rendering, input or UI; the keyboard and the gamepad's left stick share one axis.
- Bad / costs: `dev.py smoke --screenshot` captures the camera, not the IMGUI HUD.
- What we would need to see to revisit this: a release that needs rebinding (Input System) or a styled menu (UI Toolkit).
