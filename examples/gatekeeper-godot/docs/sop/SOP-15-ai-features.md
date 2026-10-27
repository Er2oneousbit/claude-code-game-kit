# SOP-15: Language models in your game (cloud and local)

## Goal
Use a language model only where it adds something classic code cannot (open-ended talk, flavor text, a character that
answers anything), and ship it without leaked keys, surprise bills, broken builds or store trouble.
Enemy and NPC *behavior* is not this SOP: classic game AI is faster, free per call and predictable (`SOP-14`, F20).

No skill runs this SOP: ask Claude to follow it when a language model comes up (`/game-ai` is for behavior).

> ### Reality check: making your own LLM
> **Training a model from scratch is not a game-dev task.** Published numbers for small models (E44, F25):
> - Llama 3.2 **1B**: about **370,000 H100 GPU-hours** of pretraining. The 3B: 460,000 GPU-hours on up to 9 trillion tokens.
> - SmolLM3 **3B**: 384 H100 GPUs for 24 days (about 220,000 GPU-hours) on 11.2 trillion tokens.
> - Phi-4-mini **3.8B**: 512 A100 GPUs for 21 days on 5 trillion tokens.
>
> That is a data center for weeks plus a curated text corpus of trillions of words. Nobody publishes the dollar cost,
> but rented GPU-hours put it far beyond any indie budget. Your RTX card would need decades.
>
> **What you can do instead, in order of effort:**
> 1. **Prompt a public small model** (step 4). Free, works today, enough for nearly every game.
> 2. **Give it examples and force its output shape** (a grammar or JSON schema, step 5).
> 3. **Fine-tune** an existing 1 to 4B model with LoRA when prompting truly is not enough (a consistent voice for a
>    character, your game's vocabulary). That fits one consumer GPU: Unsloth lists about 5 GB of VRAM for a 2B model in
>    bf16 LoRA and 10 GB for a 4B, and exports to GGUF (E44). It still needs good examples you write or curate (often thousands, depending
>    on the task **(verify)** for yours), and an evaluation to prove it got better. Record it in an ADR.
>
> "Our own LLM" in a game pitch almost always means option 1 or 3.

## 1. Do you need a language model at all?
Use one when the player types or says **anything** and the game must answer in character, or when you need lots of
varied flavor text. Do not use one for: enemy behavior, pathfinding, game rules, scoring, quest logic, anything that must
be fair or repeatable. **The game decides, the model only words it.**

## 2. Cloud API or local model
| | Cloud API (Claude, other hosted models) | Local small model (shipped with the game) |
|---|---|---|
| Quality | Best | Good for short, guided lines; weaker at long reasoning |
| Cost | Per call, grows with players | Zero per call; bigger download, players' GPU or CPU |
| Latency | Network round trip, typically seconds | Depends on the player's hardware |
| Offline | No | Yes |
| Keys and servers | **You must run a server** (step 3) | None |
| Privacy | Player text goes to a third party: privacy policy needed | Stays on the device |
| Shipped examples | Suck Up! (a reviewer names ChatGPT; E46, grade C) | inZOI Smart Zoi and NARAKA (on-device NVIDIA ACE model), PUBG Ally (beta) (E45) |

A few shipped or beta games announce small models on the player's machine (E45, vendor announcements). Cloud APIs suit
jams, prototypes and games where the conversation *is* the game.

## 3. Cloud route rules (F23)
1. **Never put the API key in the game.** Not in web code, not in a desktop build, not in a `VITE_` variable, not
   "obfuscated". Anthropic: never call the API directly from client-side code (E43). The game calls **your server**, the
   server holds the key in an environment variable and calls the model.
2. **Your server enforces limits:** per-player request rate, input length, output tokens, a daily spend cap. The provider
   also has organization-wide limits: a 429 means slow down (honor `retry-after`); a spend cap hit also returns 429 and
   retrying does not help until the cap resets (E43).
3. **Every call has a fallback:** a timeout (a few seconds) and canned lines when the server is down, the cap is hit, or
   the player is offline. The game must stay playable.
4. **Guardrails:** a system prompt that fixes the character and topic, input length limits, and an output check before
   display. Players will try to make your NPC say anything (prompt injection); assume they succeed sometimes and keep the
   blast radius at "a weird line of text". When a model's output feeds the rules (an intent label), treat it like a
   button press the player may fake: bound what one label can do (first-time-only bonuses, clamps, a turn cap). In
   the Gatekeeper examples no single line opens the gate, but two well-chosen ones can, and that is the designed limit (K01).
5. **Policies:** tell players they are talking to AI (the Anthropic Usage Policy requires disclosure in consumer chat
   products, E43, **(verify which Usage Policy version applies)**); products for minors have extra duties (age checks, moderation, E43). On Steam, live-generated content
   needs a description of your guardrails in the content survey (E22, E23, F11).
6. **Keys leak anyway:** keep `.env` out of git (the kit's `.gitignore` does), run `tools/publish_check.py` (`SOP-13`; it reports file names and line numbers, never the matched text),
   and if a key ever reaches a repo or a build, revoke it in the provider console first.

Prototype exception (tip, K01): to try a cloud feature on your own machine before building the server, the game may
read **the player's own key** from an environment variable at runtime (`OS.get_environment("FISH_API_KEY")` in Godot).
Nothing is in the build, every player pays for their own use, and without a key the feature is off and the game plays
as before. Rules 3 to 6 still apply. It is not a release design: a released game cannot ask every player for a key.
Worked example: the live voice in `examples/gatekeeper-godot` (Fish Audio text to speech).

## 4. Local route: pick a model by license first (F24)
The weights ship to every player, so the license matters more than the benchmark. Small instruct models checked
2026-10-21 (E41), newest first within each family:

| Model | Sizes | License | Shipping duties | GGUF builds |
|---|---|---|---|---|
| Qwen3.5 | 0.8B, 2B, 4B | Apache-2.0 | License and NOTICE file, mark modified files | Yes (incl. ggml-org) |
| Gemma 4 | E2B (about 2.3B effective), E4B | Apache-2.0 (earlier Gemma had custom terms) | Apache-2.0; check whether Google's prohibited-use policy applies **(verify)** | Yes (official) |
| Ministral 3 | 3B (plus vision) | Apache-2.0 | Apache-2.0 | Yes (official) |
| Granite 4.2 | 3B | Apache-2.0 | Apache-2.0 | Yes (official) |
| SmolLM3 | 3B (SmolLM2: 135M, 360M, 1.7B) | Apache-2.0 | Apache-2.0 | Yes |
| Phi-4-mini | 3.8B | MIT | Keep the copyright notice | Community builds |
| Llama 3.2 | 1B, 3B | Llama 3.2 Community License | Include the license, display "Built with Llama", derivative model names start with "Llama", follow Meta's use policy, separate license above 700M monthly users | Community builds |

Sizing rule of thumb: a 4-bit quantized model takes very roughly half a gigabyte per billion parameters on disk and in
memory, so 1 to 2B models are the realistic start for a game that also renders. Measure on your minimum spec (`SOP-10`).

**Runtimes** (E42):
| Engine | Option | License | Notes |
|---|---|---|---|
| Any native | llama.cpp (GGUF) | MIT | CUDA, Vulkan, Metal, CPU; grammars and JSON schema |
| Godot | NobodyWho | EUPL-1.2 (fine for commercial use; changes to the plugin itself must be shared) | Godot 4.5+, desktop and Android, no web export |
| Godot | godot-llm | MIT | Last release 2024: treat as unmaintained |
| Unity | LLMUnity | Apache-2.0 | Unity 2021 LTS to Unity 6, PC, mobile, VR; grammar or JSON schema |
| Unreal | Llama-Unreal | MIT | Release for UE 5.8; prebuilt for Windows |
| Web | WebLLM | Apache-2.0 | Needs WebGPU in the player's browser; JSON mode |
| Web | transformers.js | Apache-2.0 | CPU (WASM) by default, WebGPU optional and still experimental in many browsers |
| C++ (Windows, RTX focus) | NVIDIA In-Game Inferencing (NVIGI) SDK | SDK MIT; NVIDIA models under NVIDIA's community model license | Schedules inference alongside the game's rendering; bundles small Qwen and Nemotron models |

Ship it like an asset: log the model in `docs/ASSET_LOG.md` (type `model`, AI-assisted `live`), keep its license text in
`docs/licenses/`, and add a first-run download with progress and a size warning if you do not bundle it.

## 5. Patterns that work
- **Game state in, words out.** Build the prompt from facts the game owns (mood, quest stage, what the player did); the
  model writes the line. It never changes health, inventory or quest flags directly.
- **Force the output shape (F26):** a grammar or JSON schema, for example `{"mood": "angry|calm", "line": "..."}`, then
  validate in code and fall back on failure. llama.cpp does not put the schema in the prompt and silently skips schema
  features it does not support (E42), so describe the format in the prompt too and keep schemas simple.
- **Keep it short:** small context, one or two sentences out, a token cap. Stream the text if the engine allows.
- **Cache and reuse:** identical situations can reuse a line; pre-generate barks during loading when you can.
- **Stay in character:** a fixed system prompt per character plus a few example lines beats long instructions.

## Worked examples (in the kit repo)
`examples/gatekeeper-web` (WebLLM in the browser) and `examples/gatekeeper-godot` (NobodyWho plugin): talk your way past a
guard. Same rules, prompts, guardrails and recorded test fixtures in both; both verified with the real model (K01).
What building them taught, measured rather than guessed:
- **One job per call.** Asked for `{intent, line}` in one go, a 1.5B model mislabelled most lines and spoke as the player.
  Two calls (classify with output constrained to one exact label and no history; then speak one constrained sentence)
  went from 64% to 93% on a 14-line eval, at about 190 ms per reply on a desktop GPU. Keep a small labelled eval
  (the Godot Gatekeeper example's eval_guard.gd script) and run it after every prompt, model or sampler change.
- **Avoid "thinking" models for snappy NPCs.** Qwen3.5 0.8B answered in thinking mode in WebLLM even with thinking switched
  off (the switch is documented for Qwen3 only **(verify)**): slow, and `<think>` before the JSON. A model without a thinking mode
  (Qwen2.5 1.5B Instruct) fixed it.
- **Models copy the format of their input.** A `[intent: ...]` note in the prompt came back inside the reply. Constrain the
  output (grammar or regex) and strip what you know they copy.
- **Constrained output fixes the shape, not the sense.** Schema-valid JSON still had the wrong label. The rules must not trust it.
- **Package the runtime carefully.** A Godot `.gdextension` committed without its binary prints load errors on every boot;
  keep the whole plugin folder and the model out of git and install both with a checksum-verifying setup script.

## 6. Test it
- **No live model in `test` or `smoke`.** Put the model behind an interface and use a fake that returns recorded
  responses, so tests are fast, free and deterministic.
- **Golden cases:** a list of situations with recorded outputs that must still parse and pass the validator.
- **Failure cases:** timeout, empty reply, invalid JSON, refusal text, offline. Each must land on the fallback.
- **Manual pass with the real model** on minimum-spec hardware before release: speed, memory, and tone.

## Done when
- No key in the client (cloud), or the model and its license are logged and shipped correctly (local).
- Every call has a timeout and a fallback; the game is playable with the model off.
- Output is constrained and validated; game rules never depend on raw model text.
- Disclosure is in place (in-game note, store survey) and the privacy policy covers player text if it leaves the device.

## Common mistakes
- A key in a web build "just for the jam". Bots scrape public pages for keys; revoke it and move it to a server.
- Letting the model decide damage, rewards or quest outcomes. Players will talk it into anything.
- Picking a model by leaderboard and finding the license forbids your use, or forgetting its attribution duties.
- No fallback: the API has an outage on launch day and every NPC goes silent.
- Planning to "train our own model" for a game. Prompt or fine-tune an existing one (see the reality check above).
