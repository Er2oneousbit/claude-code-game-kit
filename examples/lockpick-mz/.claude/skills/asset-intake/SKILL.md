---
name: asset-intake
description: Find, vet, and log third-party or AI-assisted assets (music, SFX, art, fonts, 3D, tools, plugins). Use when the user wants to find or add music, sound effects, sprites, fonts, models, or asks "where can I get X". Consults docs/RESOURCES.md, verifies licenses, and logs to ASSET_LOG.md before anything enters the repo.
---

# Asset intake

Follow `docs/sop/SOP-04-assets-and-licensing.md`. Lists: `docs/RESOURCES.md` is the index into `docs/resources/`.

## A. Finding
1. Clarify the need if vague: mood, genre, length, loopable or one-shot, style, palette or resolution, budget.
2. Read the matching file: `docs/resources/audio.md` (music, SFX), `art.md` (2D, 3D, UI, fonts, VFX), `ai-tools.md` (generators, MCP servers), `world-and-levels.md`, `licenses.md`.
3. Suggest 3 to 5 options with license notes. Prefer CC0, then CC BY. Say clearly which came from the list and which from a live web search.
4. Warn about license traps (NC, ShareAlike on derivatives, site-specific terms).

To generate instead of find, hand off to `/gen-brief`, then come back here to log the result.

## B. Vetting (before download is used)
1. Open the specific asset page and read its license. Quote the key terms in your notes, never assume from site reputation.
2. Check: commercial use, modification, redistribution inside a game, attribution wording, AI-training clauses, platform restrictions.
3. Unknown or unclear license: do not import. Tell the user why.

## C. Logging
1. Add a row to `docs/ASSET_LOG.md` (next free `A-NNNN` ID): type, repo path, source URL, author, license, attribution text, AI-assisted (`no`, `dev-only`, `pre-generated`, `live`; see SOP-04), modified yes/no, date, notes.
2. Save license evidence in `docs/licenses/A-NNNN.txt` (text of the license or page summary with URL and date).
3. Import using the naming conventions in `docs/ENGINE.md` or `docs/ENGINE_FLOW.md` ("Assets and audio"); 3D names are in SOP-11.
4. Mark temporary or NC assets `PLACEHOLDER` in Notes.
5. A Dotwork pack (`tools/art/dotwork/`) logs itself: `python tools/art/dotwork/dotwork.py log --pack NAME --dry-run`, then without `--dry-run`, writes the row and the evidence file from its manifest (models, licenses, seeds). Check the row, do not retype it.
6. Report the row you added and any attribution that must appear in credits.

If the license check cannot be completed (site unreachable, ambiguous), say what is unknown and ask the user to decide.
