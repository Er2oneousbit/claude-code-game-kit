# Dotwork licence register

Every model Dotwork loads, with its licence, pinned in `models.lock.json` (repo, commit, path, SHA-256). Checked
2026-10-29 against each repo's model card. Re-check the cards before you ship: licences can change upstream.

| Role | File | Repo | Licence | Commercial use |
|---|---|---|---|---|
| Image model | flux-2-klein-4b.safetensors | Comfy-Org/flux2-klein (base: black-forest-labs/FLUX.2-klein-4B) | apache-2.0 | yes |
| Image VAE | flux2-vae-klein.safetensors | Comfy-Org/flux2-klein | apache-2.0 | yes |
| Text encoder (klein) | qwen_3_4b.safetensors | Comfy-Org/z_image_turbo | apache-2.0 | yes |
| Pixel-art LoRA | spritekiln_klein_pixel_art.safetensors | Limbicnation/pixel-art-lora | apache-2.0 | yes |
| Rotation model | qwen-image-edit-2511-Q4_K_M.gguf | unsloth/Qwen-Image-Edit-2511-GGUF | apache-2.0 | yes |
| Rotation LoRA | qwen-image-edit-2511-multiple-angles-lora.safetensors | fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA | apache-2.0 | yes |
| Rotation speed LoRA | Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors | lightx2v/Qwen-Image-Edit-2511-Lightning | apache-2.0 | yes |
| Rotation text encoder + VAE | qwen_2.5_vl_7b.safetensors, qwen_image_vae.safetensors | Comfy-Org/Qwen-Image_ComfyUI | apache-2.0 | yes |
| Animation model | wan2.2_i2v_{high,low}_noise_14B_Q4_K_M.gguf | QuantStack/Wan2.2-I2V-A14B-GGUF | apache-2.0 | yes |
| Animation speed LoRAs | wan2.2_i2v_lightning_4step_{high,low}.safetensors | lightx2v/Wan2.2-Lightning | apache-2.0 | yes |
| Pixel-animate LoRA | spritekiln_wan22_pixel_animate.safetensors | styly-agents/Wan2-2-pixel-animate | apache-2.0 | yes |
| Animation text encoder | umt5_xxl_fp16.safetensors | Comfy-Org/Wan_2.1_ComfyUI_repackaged | apache-2.0 | yes |
| Animation VAE | wan_2.1_vae.safetensors | Comfy-Org/Wan_2.2_ComfyUI_Repackaged | apache-2.0 | yes |

## Do not use
| File | Why |
|---|---|
| flux2-vae.safetensors from Comfy-Org/flux2-dev | FLUX.2 [dev] licence (non-commercial); a different file from the klein VAE (different SHA-256). Dotwork replaces it in every SpriteKiln workflow it loads. |

## Software Dotwork talks to (installed by you, not bundled)
| Software | Licence | How Dotwork uses it |
|---|---|---|
| ComfyUI | GPL-3.0 | over HTTP (127.0.0.1) |
| SpriteKiln (nodes + workflows) | GPL-3.0 | its nodes run inside your ComfyUI; Dotwork reads its workflow JSON from your clone at run time |
| ComfyUI-GGUF | Apache-2.0 | its loader node runs inside your ComfyUI |
| Godot 4 | MIT | runs headless against your game (import, map painting, verify) |
| Aseprite (optional) | proprietary | runs headless for the hand-polish round trip |

## Dotwork's own files
`glyphs/*.txt` (pixel fonts authored as text), `palettes/*.hex` (extracted from dotwork's own renders), the material
catalog and every `.py` file are part of Dotwork and ship under the kit's licence.
