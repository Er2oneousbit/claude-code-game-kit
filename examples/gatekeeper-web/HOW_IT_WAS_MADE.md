# How Gatekeeper (web) was made

The local-model example for browser games: a guard you talk your way past, with a small language model running **in the
player's browser** (WebLLM over WebGPU). No server, no API key, nothing the player types leaves their machine. Built in one
Claude Code session (Claude Opus 5.5) on Windows 11, Node 26, Chromium with an RTX 5060 Ti, 2026-10-21, alongside its
Godot twin (`../gatekeeper-godot/`). Both follow `docs/sop/SOP-15-ai-features.md`.

## What it demonstrates
- **The model never decides anything.** It labels the player's line with one intent and speaks one sentence; trust and the
  gate are game code (`src/core/gatekeeper.ts`).
- **Playable without the model:** browsers without WebGPU, players who skip the download, slow or broken replies all land on
  the scripted guard. Headless tests and `smoke` use that path.
- **Pay for the model only if you use it:** WebLLM (about 6 MB of JavaScript) loads by dynamic import when the player asks
  for the AI guard; the page itself is 1.4 MB. The model download is cached by the browser after the first time.

## 1. Scaffold, add one dependency with an ADR
```
python scripts/new_game.py --name "Gatekeeper" --engine web --dest ../gatekeeper-web --git-init
python tools/dev.py setup
npm install --save-exact @mlc-ai/web-llm@0.2.86        # docs/adr/0001-webllm.md
```
The web overlay's rule is "no dependency without an ADR": every package ships to players.

## 2. Engine-free core first
`src/core/`: `gatekeeper.ts` (rules), `intent.ts` (intent list, label and line checks, keyword fallback, the two grammars),
`lines.ts` (scripted voice). Vitest runs them against `tests/fixtures/recorded.json`, shared with the Godot twin.

## 3. Real model runs, and what they changed
Headless Chromium has no GPU, so the real model ran with **`dev.py smoke --headed`** (a visible window; added to the kit
during this example).
| Run | What happened | Change |
|---|---|---|
| Qwen3.5 0.8B, one JSON call | Every reply "too slow" or starting with `<think>`: the model ran in thinking mode despite `enable_thinking: false` (documented for Qwen3 only) | Model without a thinking mode: **Qwen2.5 1.5B Instruct** (Apache-2.0, about 880 MB) |
| Qwen2.5 1.5B, one JSON call | Everything labelled `question`; the guard spoke as the traveler | **Two calls** (the Godot twin measured 64% to 93%): an EBNF grammar that allows only one exact label, then one sentence |
| Two calls | Lines rejected: the model copied the `[intent: ...]` note from its input into its answer | The line check strips copied notes; a grammar forbids brackets in the line |
| Final | Both scenarios reach their marker with the real model, 0.5 to 1 s per reply, no fallbacks seen in the log. That run did not fail on a fallback (the scripted guard wins the same script), so it proved less than it seemed | The real-model command now adds `--fail-on` (section 5) |

## 4. What the kit's checks caught
| Caught by | Problem | Fix |
|---|---|---|
| `dev.py build` size | WebLLM bundled into the main page (7.3 MB) | Dynamic import: 1.4 MB page, WebLLM on demand |
| `dev.py smoke --headed` | A 404 for `/favicon.ico` (headed browsers ask for it) | Kit: `<link rel="icon" href="data:,">` in the template, smoke ignores the favicon probe |
| The scripted scenario | "That armor looks well kept" missed by the keywords, counted as `other`, cost trust, lost the game | `other` costs 0, more keywords, a regression test |
| `dev.py check` | A `note` variable typed as an intent | `let note: string` |

## 5. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` / `test` / `smoke` | types clean / 58 tests (52 for the game; the other 6 test the kit's template `CoyoteTimer`, which the game never imports) / headless boot, no errors |
| `smoke --query autoplay --until GATE_OPEN` and `--query autoplay=rude --until TURNED_AWAY` | pass (scripted guard, headless) |
| Same with `--headed` and `&llm=1` (the real model in Chromium on WebGPU), now with `--fail-on "FALLBACK,(fallback),model failed to load"` | passed 2026-10-21, every intent from the model per the log; not re-run with `--fail-on` yet (it needs the GPU and the model download) |

### Later: generated sound (ElevenLabs)
The user asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Every file is a PLACEHOLDER (non-commercial terms) in `docs/ASSET_LOG.md` (credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

| Event | File |
|---|---|
| the guard speaks | `guard-talk.mp3` |
| the gate opens / you are turned away | `gate-open.mp3` / `turned-away.mp3` |
| always (Phaser starts it when the browser unlocks audio) | `gate-ambience.wav` (10 s loop) |

- One generation for both twins: `../gatekeeper-godot` plays the same files, logged there as copies.
- Verified: `check`, 42 tests, `smoke`, and every file decoded in headless Chromium.

### Later: review fixes (2026-10-26)
A review with Claude (Fable 5.1) found nine problems and proved the code ones with failing tests; those now live in `tests/` as regression tests
(`stale_reply`, `controller_extras`, `webllm_brain`; shared fakes in `tests/support/fakePage.ts`).
- A reply that landed after "Start over" changed the new game (one greeting could then open the gate): a run counter drops it.
- A worker that failed to start or a stalled download left the AI guard loading forever: `load()` gives up after
  `LOAD_STALL_MS` without progress or on a worker error, and the scripted guard takes over.
- An engine error was reported as "model too slow" and cost 12 s on every later line: it is now a fatal `model error`,
  and the controller hands the rest of the game to the scripted guard.
- Smaller: text typed while Bram thinks is kept, one intro after a failed `llm=1` load, one restart per double click,
  player text cut to `MAX_INPUT` before it is stored or sent, and tighter tests for the grammar and the trust clamp.
- The real-model smoke command fails on fallbacks (section 5).

## 6. Honest limits
- WebGPU: current Chrome and Edge on desktop. Other browsers get the scripted guard (`webGpuAvailable()` decides).
- The first visit downloads about 880 MB and needs about 1.6 GB of GPU memory (WebLLM's own figures).
- Small-model quirks remain ("Good evening. I am not for sale." copies an example). The rules keep it fair.
- No human playtest yet.

## 7. Outside the kit
Nothing for the game. A five-line Playwright probe found the favicon 404; the fix went into the kit.
