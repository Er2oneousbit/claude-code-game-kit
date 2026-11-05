# Bozzetto licence register

Every model Bozzetto loads, with its licence, pinned in `models.lock.json` (repo, commit, path, SHA-256). Checked
2026-11-04 against each repo's model card and licence file. Re-check them before you ship: licences can change
upstream. Not legal advice (SOP-04, SOP-21).

| Role | File | Repo (pinned) | Upstream | Licence | Commercial use |
|---|---|---|---|---|---|
| Image to 3D (TRELLIS.2 4B, int8) | trellis_2_int8_convrot.safetensors | Comfy-Org/TRELLIS.2 @ 430a9d09 | microsoft/TRELLIS.2-4B | MIT | yes |
| Shape VAE | trellis_2_shape_vae_bf16.safetensors | Comfy-Org/TRELLIS.2 @ 430a9d09 | microsoft/TRELLIS.2-4B | MIT | yes |
| Texture VAE | trellis_2_texture_vae_bf16.safetensors | Comfy-Org/TRELLIS.2 @ 430a9d09 | microsoft/TRELLIS.2-4B | MIT | yes |
| Image encoder | dino_v3_vit_l.safetensors | Comfy-Org/TRELLIS.2 @ 430a9d09 | Meta DINOv3 ViT-L | DINOv3 License | yes, with a list of prohibited uses (below) |
| Background removal | birefnet.safetensors | Comfy-Org/BiRefNet @ 884af709 | ZhengPeng7/BiRefNet | MIT | yes |
| Reference image (`--prompt` only) | flux-2-klein-4b.safetensors, qwen_3_4b.safetensors, flux2-vae-klein.safetensors | as in Dotwork's `models.lock.json` | black-forest-labs/FLUX.2-klein-4B | Apache-2.0 | yes |

The licence texts are in `licenses/` next to this file. The first `make` that writes the asset log copies them into
the game's `docs/licenses/` as `bozzetto-*`, so `tools/credits.py` puts them in THIRD_PARTY_LICENSES.md.

## DINOv3: read this one
TRELLIS.2 conditions on DINOv3 image features, so every model Bozzetto makes passes through DINOv3. Its licence is
worldwide and royalty-free with no revenue cap or region list, and asks for a copy of the licence with anything that
redistributes the DINOv3 materials. Section 1.b.v says you will not use them "for any activities subject to the
International Traffic in Arms Regulations (ITAR) or end uses prohibited by Trade Controls, including those related
to military or warfare purposes, nuclear industries or applications, espionage, or the development or use of guns or
illegal weapons." **Open question, not decided here:** whether that line covers game props such as swords or guns.
Decide it for your game (and ask a lawyer if it matters) before you ship such a model. The asset log row credits
"Built with DINOv3" in its attribution column; that wording comes from the research notes, the licence text read on
2026-11-04 does not demand it **(verify)**.

## Rigging (`rig`, optional)
| Route | What | Licence | Commercial use |
|---|---|---|---|
| UniRig (`--with unirig`) | VAST-AI-Research/UniRig code, and the VAST-AI/UniRig skeleton and skin checkpoint, downloaded by UniRig itself | MIT (code LICENSE; the model card's metadata) | yes |
| (its training data) | Seed3D/Articulation-XL2.0, which the checkpoint was trained on | CC-BY-4.0: credit it (the asset log row and `docs/licenses/bozzetto-rig-*` do) | yes, with attribution |
| Tripo3D API (`--with tripo`) | rig, rig check and clip retargeting, run on Tripo's servers | Tripo's terms: outputs from paid credits are the user's and are not used for training (5.2.2); outputs from free credits stay Tripo's (5.2.1) | on paid credits |

Not used: SkinTokens (UniRig's successor, MIT) adds training data from VRoid Hub and ModelsResource (models taken
from commercial games); Puppeteer is pinned to CUDA 11.8. Read 2026-11-05 (E151, E153). `rig/licenses/` holds the
UniRig licence and the Articulation-XL2.0 notice; the first UniRig `rig make` copies them into the game.

## Never loaded
| Piece | Why |
|---|---|
| RMBG-2.0 (briaai) | CC BY-NC 4.0 (non-commercial). Upstream TRELLIS.2's own pipeline uses it; ComfyUI's TRELLIS.2 nodes use BiRefNet instead. `make` refuses a workflow that names it, `check` warns. |
| nvdiffrast (NVIDIA) | NVIDIA Source Code License (non-commercial). Upstream TRELLIS.2 needs it for texture baking; ComfyUI's built-in bake nodes do not. Same refusal. |
| Hunyuan3D 2.x | Licence excludes the EU, the UK and South Korea, plus a monthly-user cap: not used. |
| Stable Fast 3D, SPAR3D | Stability AI Community Licence (a US$1M revenue cap): not used. |

## Software Bozzetto talks to (installed by you, not bundled)
| Software | Licence | How Bozzetto uses it |
|---|---|---|
| ComfyUI 0.43.0+ (TRELLIS.2 nodes built in) | GPL-3.0 | over HTTP (127.0.0.1) |
| Blender 4.2+ or the bpy module | GPL-3.0 (the models you export are yours) | runs cleanup.py, turntable.py and the kit's Blender tools headless |

## Bozzetto's own files
Every `.py` file and the two workflow JSON files are part of the kit and ship under the kit's licence.
