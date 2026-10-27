# ADR 0001: WebLLM for the local AI guard

- Status: accepted
- Date: 2026-10-21

## Context
The example needs a language model in the browser with no server and no API key (SOP-15: keys never ship in a client).
The player's text must stay on their machine. The game must stay playable without the model.

## Options considered
1. **WebLLM** (`@mlc-ai/web-llm`, Apache-2.0): runs prebuilt small models on WebGPU, OpenAI-style API, JSON and EBNF grammar
   constraints, Web Worker support, browser-cached downloads.
2. **transformers.js** (Apache-2.0): ONNX Runtime, CPU by default, WebGPU still experimental in many browsers.
3. **A cloud API through our own server**: best quality, but a server, a key, a bill per player and player text leaving the device.

## Decision
WebLLM, because grammar-constrained output on WebGPU is exactly what a classifier-plus-one-line design needs, and it keeps
everything on the player's machine.

## Consequences
- Good: no server or key; replies in 0.5 to 1 s on a desktop GPU; the dependency loads only when the player asks for the AI guard.
- Bad / costs: WebGPU only (desktop Chrome and Edge today); about 880 MB first download for Qwen2.5 1.5B; 6 MB of JavaScript.
- Revisit if: WebGPU support or CPU speed makes transformers.js competitive, or the game needs a much larger model.

## Notes
Verified in this project with `dev.py smoke --headed` and the real model (HOW_IT_WAS_MADE.md). Sources: E42 in docs/EVIDENCE.md.
