# Style Guide

Goal: a stranger (or you in six months) can open any file, understand why it exists, and change it safely.

## Principles
1. Small, single-purpose functions and files. If you need "and" to describe it, split it.
2. Comments explain **why**, not what. Name things so the what is obvious.
3. Fail loudly, with context (what failed, with which input, what to try).
4. Every system has a debug switch or log channel.
5. Constants and tunables in one place (data file or constants module).
6. Prototype first, refine later. Mark prototype code with `PROTOTYPE:` so it is greppable.

## File header (every new source file and tool script)
Fill in purpose, usage, and notes. Keep the Claude line so provenance is clear.

**GDScript / Python**
```
# ---------------------------------------------------------------------------
# <file name>
# Purpose : <one line>
# Usage   : <how other code or the user calls this>
# Notes   : <gotchas, assumptions, links to docs/adr/NNNN>
# Authored: Written with Claude (<model name>, <model id>)
# ---------------------------------------------------------------------------
```

**C++**
```
// ---------------------------------------------------------------------------
// <file name>
// Purpose : <one line>
// Usage   : <how other code calls this>
// Notes   : <gotchas, assumptions, links to docs/adr/NNNN>
// Authored: Written with Claude (<model name>, <model id>)
// ---------------------------------------------------------------------------
```

## File footer
No footer line is required (the project profile sets none).

## Pseudocode-first blocks
For non-trivial functions, put the pseudocode in the header comment of the function, then implement under it.
Keep the pseudocode after implementation. It is the map.

## Naming
- Files: `snake_case` for GDScript and Python, `PascalCase.cpp/.hpp` for C++ classes, UE prefixes per `docs/ENGINE.md`.
- Booleans read as questions: `is_grounded`, `has_key`.
- Units in names when ambiguous: `speed_px_s`, `duration_ms`.

## Errors and logging
- Use the engine logger or `src/core/Log` wrapper. No bare `print`/`printf` in committed game code.
- Channels: `core`, `input`, `physics`, `ai`, `ui`, `audio`, `save`, `net`. Add more as needed, keep names lowercase.
- Debug toggles via a single debug config, not scattered `#ifdef`s.
- Validate at boundaries (file load, input, network, save data). Trust internal calls after that.

## Tests
- Pure logic (math, state machines, inventory, scoring, RNG with seed) gets unit tests with no engine dependency.
- Name tests after behavior: `test_jump_buffer_expires_after_100ms`.
- A bug fix lands with a test that failed before the fix when feasible.

## Config format
Pick by context and say which and why in the ADR:
- Tunables designers poke: JSON or TOML (or engine resources if the engine edits them natively).
- Engine-native data: Godot `.tres`, Unreal DataTables or DataAssets.
- Anything needing comments: TOML or YAML.

## Commit messages
`type(scope): summary` where type is `feat fix refactor test docs chore perf`. Body explains why.
