# How Gatekeeper (Godot) was made

The local-model example for native games: a guard you talk your way past, with a small language model running inside
Godot through the NobodyWho plugin. Built in one Claude Code session (Claude Opus 5.5) on Windows 11, Godot 4.7.2,
an RTX 5060 Ti, 2026-10-21, alongside its browser twin (`../gatekeeper-web/`). Both follow `docs/sop/SOP-15-ai-features.md`.

## Iteration timeline: how the game changed after it first worked
| # | Day | Prompted by | What changed | Proof |
|---|---|---|---|---|
| 1 | 10-21 | Measure the model, do not guess (section 3) | Two constrained model calls per turn instead of one free one | Eval 64% to 93% on 14 labelled lines |
| 2 | 10-22 | Owner: a voice for the guard, but "not shipping an API key; the game could read it from the environment as a proof of concept" | Bram speaks every line through Fish Audio with the player's own key, read at runtime; off without a key | 5 lines spoken live, then from the cache in 0 to 1 ms; a bad key and no key both leave the game playable |
| 3 | 10-22 | The first live run logged no speech at all | Autoplay quit before the first reply arrived; it now waits for queued lines | `VOICE_OK` per line |
| 4 | 10-22 | A recording of the game "sounded like white noise" | Nothing wrong in the game: the recording was 32-bit and had been read as 16-bit. The kit's `wavfile.py` now reads 32-bit | 14.5 s of sound where the log says 14.4 s of speech |

## What it demonstrates
- **The model never decides anything.** It labels the player's line with one intent from a fixed list and speaks one
  sentence. Trust, turns and the gate are game code (`scripts/core/gate_rules.gd`). You cannot talk the model into opening
  the gate, because opening it is not the model's job.
- **Playable without the model.** A keyword classifier and scripted lines play the same game; every model step has a
  timeout and falls back to them. Tests and `smoke` never touch the model.
- **Nothing big in git.** The plugin binary (143 MB) and the model (1.1 GB) are logged in `docs/ASSET_LOG.md` with license
  evidence, and `tools/setup_ai.py` downloads them and checks the SHA-256 recorded when they were logged.

## 1. Scaffold and verify the plugin before writing the game
```
python scripts/new_game.py --name "Gatekeeper" --engine godot --dest ../gatekeeper-godot --git-init
python tools/fetch_asset.py --url <NobodyWho v12.1.0 release zip> --license EUPL-1.2 --type plugin --to addons/nobodywho --take ...
python tools/fetch_asset.py --url <Qwen2.5-1.5B-Instruct GGUF> --license Apache-2.0 --type model --to models --take ...
```
Research found that **NobodyWho v12 (five days old) rewrote its entire API**: tutorials and model memory describe the old
one. A ten-line probe script confirmed the new API on Godot 4.7.2 before any game code: `NobodyWhoChat.create(path, config)`
awaitable, JSON-schema and regex samplers, headless works, the model loads in about 2 s on this GPU.
**Kit change:** `fetch_asset.py` learned the `plugin` and `model` types and accepts weak-copyleft licenses (EUPL, MPL, LGPL).

## 2. Engine-free core first (SOP-01, SOP-15)
`scripts/core/`: `gate_rules.gd` (trust rules), `gate_intent.gd` (the intent list, strict checks for the model's label and
line, the keyword fallback), `guard_lines.gd` (scripted voice). GUT tests run them against `tests/fixtures/recorded.json`:
model outputs good and broken, **the same file the web twin tests**.

## 3. Measure the model instead of guessing (`tools/eval_guard.gd`)
14 labelled player lines, two per intent, through the real model:
| Version | Accuracy | Notes |
|---|---|---|
| One call, JSON `{intent, line}`, examples inside the system prompt | about 1 in 5 | The model spoke as the traveler ("I am here for the gate.") and labelled most lines `question` |
| One call, examples as real chat turns | 9/14 (64%) | Better, still mixed up "who is talking" |
| **Two calls: classify (regex: one exact label, no history), then speak (regex: one sentence)** | **13/14 (93%)**, about 190 ms | Shipped. The miss: "Banana." labelled `bribe` |
A 1.5B model asked for two jobs at once does both badly; one job per call fixed it. Both calls share one loaded model.

## 4. What the checks caught
| Caught by | Problem | Fix |
|---|---|---|
| GUT (unexpected engine errors) | `JSON.parse_string` prints an engine ERROR for every malformed reply, which would also fail `dev.py smoke` | `JSON.new().parse()` returns the error quietly |
| The autoplay script with the model | It never ended when the conversation did not, and hung the check | Autoplay quits when its script runs out |
| The scripted scenario | A line the keyword classifier missed ("That armor looks well kept") counted as `other`, which cost trust and lost the game | `other` costs 0, more flattery keywords, a test for that line |
| The web twin's model run | Small models copy `[intent: ...]` notes from the prompt into their reply | The line check strips copied notes; this twin's regex already forbade brackets |

## 5. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` / `test` / `smoke` | 10 scripts / 24 GUT tests (2026-10-22, with the voice tests) / clean boot |
| `-- --autoplay --voice` with a Fish Audio key, then again | 5 lines spoken, 1.7 to 2.0 s each from the API; the rerun 0 to 1 ms each from the cache |
| Same with a bad key / no key | one `VOICE_FAIL HTTP 401`, voice off, gate still opens / `VOICE_OFF`, unchanged game |
| `godot --headless --path . -- --autoplay` and `--autoplay=rude` (scripted guard) | `GATE_OPEN` / `TURNED_AWAY` |
| Same with `--llm` (the real model) | `GATE_OPEN` / `TURNED_AWAY`, every intent from the model, 170 to 220 ms per reply, no fallbacks |
| `godot --headless --path . --script res://tools/eval_guard.gd` | 13/14 (93%) |
| `python tools/setup_ai.py` | verified install; a tampered checksum is refused |

### Later: a live voice (Fish Audio, proof of concept)
Bram's lines are written while you play, so recorded voice files cannot match them: the voice has to be made live.
`scripts/game/guard_voice.gd` sends each guard line to Fish Audio's text-to-speech API and plays the MP3 that comes
back. The key is the player's own, read from `FISH_API_KEY` at runtime, so nothing secret is in the project or a build.
- Built in this order: the kit tool first (`python tools/audio/fish_tts.py check`, `voices --licensed`, one `say` line),
  which showed the developer API wallet at $0 (billed apart from the subscription), so the free model `s2.1-pro-free`
  became the default; and that "licensed" voices still include imitations of real people, so the default is an
  original-sounding one ("Calm Reflective Male").
- The text always shows first; the voice queues behind it and never blocks the game. Off in headless runs (smoke and
  CI spend nothing) unless `--voice`; a 401/402/403 turns it off for the session; repeats come from a cache.
- Autoplay quit before the first reply arrived (no `VOICE_OK` at all): it now waits for queued lines, at most
  `Tuning.VOICE_DRAIN_S`.
- Checked by ear, without ears: Godot's movie writer recorded a windowed run, and the recording holds 14.5 s of sound
  where the log reports 14.4 s of speech, with a speech-like spectrum. A first analysis said "white noise": the movie
  writer records 32-bit samples and they had been read as 16-bit. The kit's `tools/audio/wavfile.py` reads 32-bit now.

### Later: generated sound (ElevenLabs)
The owner asked for API audio in the other example games (2026-10-23), after Graveyard Shift had it. The Kenney sounds
were replaced by sound effects generated with the kit's `tools/audio/eleven_audio.py`, plus an ambience loop the game
never had. Free plan: every file is PLACEHOLDER in `docs/ASSET_LOG.md` (non-commercial, credit in the README); the old
Kenney rows stay, marked removed. Every file was measured before use (peak, loudness, silence at the start, the jump at
a loop's seam, flat-topped samples), then peak-normalized: one-shots to -3 dBFS, loops to -6 (the log says Modified, the
evidence file keeps the shipped file's SHA-256, the `.gen.json` next to it the generated one).

The files are the web twin's (one generation, logged in both): `gate-open.mp3`, `turned-away.mp3`, `guard-talk.mp3` and
`gate-ambience.wav`. Godot imports MP3 as is; the ambience loops in code (`AudioStreamWAV.LOOP_FORWARD` over its whole
length), so its import settings stay default.
- Verified: `check` (Godot imported all four), 24 GUT tests (GUT copied in for the run, then removed), `smoke`.

## 6. Honest limits
- 93% on 14 lines is a small sample. The guard still says odd things now and then ("I will not open the gate", right before
  the rules open it). That is the design working: the model voices, the rules decide, and the ending line is scripted.
- Only the Windows plugin binary is installed by `setup_ai.py` (edit `PLUGIN_FILES` for Linux or macOS). Exported builds:
  the model must ship next to the game or download on first run; loading it from inside a `.pck` is unverified.
- No human playtest yet.
- The live voice is a proof of concept: about 2 s behind the text, one voice, and only for players with their own
  Fish Audio key. A release would call its own server (SOP-15).

## 7. Outside the kit
Nothing for the game itself. The plugin API probe and the eval were written for this example and kept (`tools/eval_guard.gd`).
