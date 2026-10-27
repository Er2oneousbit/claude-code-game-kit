# ADR 0001: NobodyWho plugin, two constrained calls per reply

- Status: accepted
- Date: 2026-10-21

## Context
A native game with a small model on the player's machine (SOP-15 local route). The guard must classify the player's line
into one intent the rules understand, and say something in character, fast, without ever deciding the outcome.

## Options considered
1. **NobodyWho** (EUPL-1.2 Godot plugin on llama.cpp): in-process, Vulkan GPU with CPU fallback, regex and JSON-schema
   constrained sampling, one loaded model shared by several chats.
2. **llama.cpp server as a sidecar process**: any engine, but process management and ports when shipping.
3. **One call returning JSON {intent, line}** vs **two calls (label, then line)**.

## Decision
NobodyWho with two calls: a classifier chat constrained by regex to one exact label (no history, so it cannot drift), and a
speaker chat constrained to one sentence. Measured with tools/eval_guard.gd: one call 64% at best, two calls 93%.

## Consequences
- Good: about 190 ms per reply on an RTX 5060 Ti; labels can never be invalid; the game parses without the plugin.
- Bad / costs: 143 MB plugin binary per platform and a 1.1 GB model, both outside git (tools/setup_ai.py); EUPL obligations
  if the plugin itself is modified; two calls per turn.
- Revisit if: a model with a reliable single structured answer is small enough, or the plugin API changes again (v12 was a rewrite).

## Notes
NobodyWho v12.1.0 API verified by a probe on Godot 4.7.2 before use. Sources: E42 in docs/EVIDENCE.md.
