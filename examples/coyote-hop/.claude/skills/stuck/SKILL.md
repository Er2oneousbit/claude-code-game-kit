---
name: stuck
description: Break out of a debugging or design loop. Use when 3 attempts have failed, the user says "I'm stuck" or "this makes no sense", or Claude notices it is repeating the same idea. Forces a new angle with a fresh-perspective checklist.
---

# Stuck: change the angle

Stop making edits. Do this instead.

1. **Write the ledger:** every hypothesis tried, the one change made for each, and the exact result. If there is no ledger, reconstruct it and say what is uncertain.
2. **List assumptions** the whole effort rests on (is the right file loaded, is the build stale, is this the branch and engine version we think, is the input what we think). Pick the assumption trusted most and try to prove it false with a direct check.
3. **Boring checklist:** clean rebuild, cache or import folder reset, correct scene or level loaded, correct config, different machine or user profile, last known good commit.
4. **Invert the problem:** instead of "why does X fail", ask "what would have to be true for X to work?" and check each condition.
5. **Shrink:** build the smallest standalone repro (new empty scene, 20-line test). Does it fail there? That splits the world in two.
6. **Change the layer:** if you have been looking at game code, look at input data, timing and init order, engine settings, platform differences, threading, or the asset import.
7. **Outside view:** delegate to the `researcher` subagent with the exact error text and engine version for known issues. For build or test failures use `build-doctor`. Report findings labeled **verified** or **unverified**.
8. **Present 3 genuinely different next moves** (not variations of the last one), with the cheapest check for each, and recommend one.

Tone: calm, a little wry. Being stuck is normal. Do not tell the user to take a break, just give them a new angle.
