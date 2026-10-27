# ADR 0001: SDL companion libraries for images, the font and sound

- Status: accepted
- Date: 2026-10-21

## Context
The sprites are PNG sheets rendered by tools/make_sprites.py, the HUD needs text, and the Kenney sounds are Ogg Vorbis.
SDL2 alone loads only BMP and WAV and draws no text. The C++ overlay asks for an ADR before adding a library
(docs/ENGINE.md, "Libraries").

## Options considered
1. **SDL2_image, SDL2_ttf, SDL2_mixer** (the official SDL companions): same API style and lifetime rules as SDL2, vcpkg ports,
   zlib license. Costs: three more DLLs on Windows, a longer first build (freetype, libpng, libvorbis).
2. **Single-header libraries** (stb_image, stb_truetype, stb_vorbis) feeding SDL surfaces and audio queues: no extra DLLs,
   public domain. Costs: our own glue for font atlases and mixing, which is game-independent work.
3. **Convert assets** (PNG to BMP, Ogg to WAV, a bitmap font): no libraries. Costs: a conversion step the kit has no tool
   for, bigger files, and hand-made text rendering.

## Decision
Option 1. It is the shortest path to sprites, text and sound with code that matches every SDL2 tutorial.

## Consequences
- Good: `IMG_LoadTexture`, `TTF_RenderUTF8_Blended`, `Mix_PlayChannel`; vcpkg copies the DLLs next to the exe.
- Bad / costs: first configure builds freetype, libpng and libvorbis (about 2 minutes on the dev machine).
- What we would need to see to revisit this: a platform where the DLLs are a problem (static linking, or option 2).

## Notes
Versions resolved by vcpkg at the pinned baseline, **verified** in the first build on 2026-10-21: sdl2-image 2.8.12,
sdl2-ttf 2.24.0, sdl2-mixer 2.8.2 (with libvorbis 1.3.7 and libogg 1.3.6). All zlib-licensed (SDL libraries) **(verify the
dependency licenses before release: freetype is FTL or GPLv2, libpng and libvorbis are BSD-style)**.
