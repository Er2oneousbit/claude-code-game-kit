# Licenses: cheat sheet for a commercial release

Read this before pulling in anything you did not make yourself.

> **Read this caveat.** Written from general knowledge plus video notes, not live-checked. Sites change terms, go offline, or rename
> licenses. The license that matters is the one on the **specific asset page on the day you download it**. Save the license text in
> `docs/licenses/` and log the asset in `docs/ASSET_LOG.md` via `/asset-intake`. Anything marked **(verify)** is the most likely to have changed.

| License | Commercial OK | Attribution | Notes |
|---|---|---|---|
| CC0 / Public Domain | Yes | No | Safest. Prefer when quality is equal. |
| CC BY | Yes | **Yes** | Keep credits file current. |
| CC BY-SA | Yes | Yes | ShareAlike can infect derived assets. Avoid for anything you will modify and ship. |
| CC BY-NC / NC-ND | **No** | Yes | Not for a commercial release. Prototype only, then replace. |
| OFL (fonts) | Yes | No (keep license file) | Do not sell the font alone. |
| Site-specific "free license" | Read it | Varies | Pixabay, Zapsplat, Mixkit etc. Read per site. **(verify)** |
| GPL (code/assets) | Depends | Yes | Avoid in closed-source builds. |

AI-generated content: Steam asks developers to disclose AI content that ships to players (pre-generated) and content generated at runtime (live, with guardrails). Efficiency tools used only in development are not the focus. Rules evolve, so
check Valve's current policy before submitting. Summary and sources in `docs/sop/SOP-04-assets-and-licensing.md` (evidence E23). **(verify)** Log any AI-assisted asset in `ASSET_LOG.md`.

Back to the index: `docs/RESOURCES.md`.
