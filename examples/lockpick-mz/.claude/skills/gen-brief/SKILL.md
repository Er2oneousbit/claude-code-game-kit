---
name: gen-brief
description: Write ready-to-paste prompts and briefs for external generation tools (ElevenLabs voice/SFX/music, image generators like ChatGPT/Grok/Midjourney, text/image-to-3D tools, music generators). Use when the user wants to generate art, voice lines, sound effects, music, or 3D drafts with another tool, or says "make me a prompt for X". Keeps style consistent via docs/BRIEFS.md and logs results.
---

# Generation briefs

Claude does not make the pixels or audio here. Claude writes the **brief**, keeps style consistent across dozens of generations, and tracks what came back. Fragments and tool patterns live in `docs/BRIEFS.md`.
When the project has an API tool for the job (`tools/audio/eleven_audio.py`, `tools/audio/fish_tts.py`, `tools/art/pixellab.py`) and the user has said to use it, run it with the brief instead of handing over text: one take first and report its cost, then more (SOP-12 "Price one job before many"), `--log` on everything that ships.
If the owner runs ComfyUI locally (SOP-16 "Generating pixel art locally"), offer it for concepts, variants and style references before a paid tool, and log what is kept the same way.

1. **Read context:** Art and audio direction in `docs/GDD.md`, the style fragments in `docs/BRIEFS.md`, and the asset need (what it is, where it is used, technical constraints from `docs/ENGINE.md`).
2. **Missing style bible?** If the style fragments in `docs/BRIEFS.md` are blank, propose them first (palette, camera, resolution, mood, references, voice cast, SFX character) and get a yes. Consistency is the whole point.
3. **Pick the tool and category:** image, 3D draft, voice, SFX, or music. If the user did not name a tool, recommend one from `docs/resources/ai-tools.md` (or `audio.md`, `art.md`) and say why. Tool features and limits change often, so mark specifics **(verify)** unless confirmed this session.
4. **Write the brief** using the pattern for that category from `docs/BRIEFS.md`:
   - Output: 1 primary prompt, then 2 variants that change one thing each (so results are comparable).
   - Include technical asks (view angles, background, duration, loopability, format) as separate lines.
   - Include a short "reject if" checklist (what a bad result looks like) so review is fast.
5. **Batch consistency:** for sets (a character's 12 voice lines, 20 UI icons, 15 footsteps), generate a numbered table with the shared prefix once and only the varying part per row.
6. **After generation:** when the user brings results back, review against the "reject if" list, suggest prompt tweaks (one change at a time), and when something is accepted run `/asset-intake` to log it as AI-assisted with tool, account tier or plan, date, and the prompt used.
7. **Save winners:** add prompts that worked to the Prompt Library table in `docs/BRIEFS.md`.

Rules:
- Never put credentials or API keys into prompts or files. Never read them.
- Do not write prompts that imitate a named living artist's style, a real person's voice, or copyrighted characters. Offer an original descriptive alternative.
- Commercial rights often depend on the tool's plan or tier at generation time. Record it and flag it **(verify)** for the user to confirm in the tool's terms.
- Check the store's current AI-disclosure rules before release **(verify)**.
