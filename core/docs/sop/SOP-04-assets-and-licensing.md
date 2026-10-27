# SOP-04: Assets and Licensing

## Goal
Every asset in the repo has known provenance and a license compatible with release.

## Steps
1. **Find candidates** via `docs/RESOURCES.md` (index into `docs/resources/`). Prefer CC0, then CC BY.
2. **Verify the license on the specific asset page.** Not the site's general claims. Check commercial use, modification,
   redistribution, attribution wording, and any "no AI training" or "no game engine redistribution" clauses.
3. **Log it** before importing (`/asset-intake`): source URL, author, license, attribution text, AI-assisted, modified.
4. **Store license evidence** (text or screenshot) in `docs/licenses/` named by asset ID.
5. **Import using naming conventions** from `docs/ENGINE.md` or `docs/ENGINE_FLOW.md` ("Assets and audio"; RPG Maker MZ gives folder and format rules there instead of file prefixes); 3D asset names are in SOP-11. Keep originals (source files) separate from imported/optimized versions.
6. **Tag placeholders.** NC or temporary assets are marked `PLACEHOLDER` in the log and replaced before release. An unknown
   license means the asset does not go in at all.
7. **Credits.** Keep `CREDITS.md` generated from the log. Check it in `/release-check`.

## AI-assisted assets
- Write prompts and briefs with `/gen-brief` (`docs/BRIEFS.md`), keep style fragments consistent, save winning prompts to the Prompt Library.
- Record the generator's account plan or tier at generation time: commercial terms often depend on it **(verify in the tool's terms)**.
- Log the tool, date, prompt summary, and how much hand editing happened.
- Check the tool's terms about commercial use and ownership.
- Check the store's current AI disclosure rules before submission (Steam has them, verify the latest).
- Prefer using AI as reference or draft, then redo by hand when the final asset needs to be defensible.

## Cloning commercial games with AI (learning exercise only, F17)
- Prompting an agent to recreate a famous game from screenshots is a popular demo and a fine private exercise to learn what the tools can do.
- Never ship it. The name, UI, characters, maps, logos, sounds and art belong to someone else. A "clone with a new name" is still a copy if the look is recognizable.
- If a model's own brief includes an IP warning, keep it. Do not strip it so the model behaves.
- Use the exercise to find the techniques you want (lighting, fog, UI polish), then apply them to your original game.

## Steam AI disclosure: sort every use of AI into three buckets
Source: the Steamworks Content Survey page, "Generative AI Content" part (E23, read 2026-10-19), plus a video explaining it (E22). Grade A (F11). **Policies change, re-read the live page before you submit.**
| Bucket | Example | Disclose on Steam? |
|---|---|---|
| AI-assisted development | Claude debugs the upgrade system, writes build or test tools that never ship. Nothing AI-made reaches the player. | Steam says efficiency gains from tools are not the focus of this section. Generally not the target of the survey. Still your call to describe honestly if a question fits. |
| Pre-generated content | AI portraits, icons, textures, music, voice, text, AI-translated localization that ship in the build | Yes. Describe the implementation. Valve reviews it like any other content (illegal or infringing material, matches your marketing). |
| Live-generated content | An NPC backed by a language model, runtime image generation | Yes, plus describe your guardrails against illegal content. Valve said it does not want live-generated adult-only sexual content at this time. |
AI-written game code that ships is AI-made output in the build; the official page does not single it out, so check the
current form for where it fits **(verify)**.
Rules of thumb from the video (tips, E22 grade C, consistent with the official page):
- Follow the output: what did the AI make, and did it reach the player? That decides the bucket, not whether you "used AI".
- **Store page and marketing art** (capsules, screenshots, trailer, description text): Valve's page above talks about content in the
  game, but reporting on the January 2026 form says it also asks about AI-made store assets **(verify on the current form)**. Log
  AI-made store assets in `ASSET_LOG.md` too (type `store`), so `/release-check` can include them either way.
- Disclosure is not permission. If an asset infringes someone's rights, disclosing it does not make it safe. You are responsible for everything you ship, however you made it.
- Do not try to outsmart the survey. Answer accurately. If unsure where something fits, ask Valve or re-read the docs.
- Live AI means moderation work (filter input and output, decide what gets logged and blocked) and a running bill after the game is sold. Budget for success before building around it.
- Mixed projects are normal: heavy AI for code with human art, music and writing is one valid combination.

## itch.io AI disclosure (tip, E53, grade C) **(verify against itch.io's current creator guidelines)**
- Since November 2024 every **asset** page (art, sound, fonts for other developers) must answer the generative-AI question;
  pages that do not can be unlisted.
- **Game** pages have the same field: "Yes" adds an AI-Generated tag with what it covers (Graphics, Sound, Text & Dialog,
  Code), "No" adds a "No AI" tag. Whether a game must fill it was not confirmed (reports from 2024). Answer from itch.io's own
  categories, not the Steam buckets: AI-written code that ships counts under Code there. Say it in the description too.

Track it as you go: `docs/ASSET_LOG.md` column "AI-assisted?" should say `no`, `dev-only`, `pre-generated` or `live`. Locale files made with AI translation count as pre-generated.

## Audio specifics
- Source files: WAV 48 kHz (or 44.1 kHz) 16 or 24-bit. Ship compressed (OGG) if size matters.
- Normalize peaks around -1 dBFS for SFX, loudness-match music tracks to each other. Add short fades to avoid clicks.
- Loops: verify loop points in the engine, not just the editor.

## Art specifics
- Pixel art: integer scaling, nearest-neighbor filtering, one palette, consistent pixel density.
- Keep layered source files (`.aseprite`, `.kra`, `.blend`) in the repo or LFS, exports in the assets folder.

## Done when
- Every third-party, AI-assisted or shipped media file (art, audio, fonts, models) maps to a row in `ASSET_LOG.md`. Engine and
  project files (scripts, scenes, `.meta`, the project's own maps and Blueprints) do not need rows.

## Common mistakes
- "I will log it later."
- Using a CC BY-NC asset because it was perfect and the game is "just a prototype".
- Forgetting attribution wording differs per author.
