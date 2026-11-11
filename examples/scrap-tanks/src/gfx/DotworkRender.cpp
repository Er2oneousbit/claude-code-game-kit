// ---------------------------------------------------------------------------
// DotworkRender.cpp
// Purpose : Implementation of gfx::dotwork::Library (see DotworkRender.hpp).
// Usage   : owned by the game (src/game/DotworkShowcase.cpp shows the starter scene's use).
// Notes   : Source rects come straight from the manifest (frame rects, atlas cells, glyphs); destinations are
//           offset by the pivot and multiplied by the scale. Blend, alpha and colour mods are set on each draw,
//           since one texture can be drawn several ways (a sheet in two sprites, a font in two colours).
//
// Pseudocode:
//   load_all: each manifest -> load (log errors, warnings) -> file check (log) -> preload the textures it draws
//   draw_map: each layer -> each cell -> its atlas cell (+ animation frame) -> flip/turn -> centre on the cell
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "gfx/DotworkRender.hpp"

#include <cmath>

#include "core/AtomicFile.hpp"
#include "core/Log.hpp"

namespace gfx::dotwork {

namespace {

constexpr const char* kLog = "dotwork";

SDL_FRect frect(const dw::Rect& r) {
    return {static_cast<float>(r.x), static_cast<float>(r.y), static_cast<float>(r.w), static_cast<float>(r.h)};
}

}  // namespace

std::size_t Library::load_all(const std::filesystem::path& assets_dir) {
    std::size_t loaded = 0;
    for (const auto& path : dw::find_manifests(assets_dir)) {
        dw::Pack pack = dw::load_manifest(path);
        for (const auto& e : pack.errors) {
            LOG_ERROR(kLog, e);
        }
        for (const auto& w : pack.warnings) {
            LOG_WARN(kLog, w);
        }
        if (pack.base_dir.empty()) {   // not readable at all (no format, another major version)
            continue;
        }
        for (const auto& p : dw::check_files(pack)) {
            LOG_ERROR(kLog, core::path_to_utf8(path.filename()) << ": " << p);
        }
        packs_.push_back(std::move(pack));
        ++loaded;
    }
    for (const auto& pack : packs_) {   // a PNG SDL cannot decode is an error now, not mid-game
        preload(pack);
    }
    if (loaded > 0) {
        LOG_INFO(kLog, "loaded " << loaded << " Dotwork packs, " << textures_.size() << " textures");
    }
    return loaded;
}

void Library::preload(const dw::Pack& pack) {
    for (const auto& a : pack.animated_sprites) {
        for (const auto& c : a.clips) {
            for (std::size_t i = 0; i < c.frames.size(); ++i) {
                texture(pack, c.texture_of(i));
            }
        }
    }
    for (const auto& s : pack.sprites) {
        texture(pack, s.image);
        if (!s.shadow_image.empty()) {
            texture(pack, s.shadow_image);
        }
    }
    for (const auto& i : pack.icons) {
        for (const auto& s : i.sizes) {
            texture(pack, s.image);
        }
    }
    for (const auto& p : pack.portraits) {
        for (const auto& e : p.expressions) {
            texture(pack, e.image);
        }
    }
    for (const auto& t : pack.tilesets) {
        for (const auto& at : t.atlases) {
            texture(pack, at.image);
        }
    }
    for (const auto& f : pack.fonts) {
        for (const auto& p : f.pages) {
            texture(pack, p);
        }
    }
    for (const auto& k : pack.ui_kits) {
        for (const auto& p : k.parts) {
            texture(pack, p.image);
        }
    }
}

SDL_Texture* Library::texture(const dw::Pack& pack, const std::string& rel) {
    const std::string path = core::path_to_utf8(pack.resolve(rel));
    const auto it = textures_.find(path);
    if (it != textures_.end()) {
        return it->second.get();
    }
    TexturePtr tex;
    if (SDL_Surface* surface = SDL_LoadPNG(path.c_str())) {
        tex.reset(SDL_CreateTextureFromSurface(r_, surface));
        SDL_DestroySurface(surface);
    }
    if (tex) {
        SDL_SetTextureScaleMode(tex.get(), SDL_SCALEMODE_NEAREST);   // pixel art: no smoothing (and no mipmaps)
    } else {
        LOG_ERROR(kLog, "cannot load " << path << ": " << SDL_GetError());
    }
    SDL_Texture* raw = tex.get();
    textures_.emplace(path, std::move(tex));
    return raw;
}

void Library::draw_frame(const dw::Pack& pack, const dw::AnimatedSprite& sprite, const dw::Clip& clip,
                         std::size_t frame, float x, float y, float scale) {
    if (frame >= clip.frames.size()) {
        return;
    }
    SDL_Texture* tex = texture(pack, clip.texture_of(frame));
    if (!tex) {
        return;
    }
    const dw::Rect& r = clip.frames[frame].rect;
    const SDL_FRect src = frect(r);
    const SDL_FRect dst{x - static_cast<float>(clip.pivot.x) * scale, y - static_cast<float>(clip.pivot.y) * scale,
                        static_cast<float>(r.w) * scale, static_cast<float>(r.h) * scale};
    SDL_SetTextureBlendMode(tex, sprite.blend == dw::Blend::Add ? SDL_BLENDMODE_ADD : SDL_BLENDMODE_BLEND);
    SDL_RenderTexture(r_, tex, &src, &dst);
}

void Library::draw_sprite(const dw::Pack& pack, const dw::Sprite& sprite, float x, float y, float scale) {
    if (!sprite.shadow_image.empty()) {
        if (SDL_Texture* shadow = texture(pack, sprite.shadow_image)) {
            float w = 0, h = 0;
            SDL_GetTextureSize(shadow, &w, &h);
            const float cx = x + static_cast<float>(sprite.shadow_offset.x) * scale;
            const float cy = y + static_cast<float>(sprite.shadow_offset.y) * scale;
            const SDL_FRect dst{cx - w * scale / 2, cy - h * scale / 2, w * scale, h * scale};
            SDL_SetTextureBlendMode(shadow, SDL_BLENDMODE_BLEND);
            SDL_RenderTexture(r_, shadow, nullptr, &dst);
        }
    }
    SDL_Texture* tex = texture(pack, sprite.image);
    if (!tex) {
        return;
    }
    const SDL_FRect dst{x - static_cast<float>(sprite.pivot.x) * scale, y - static_cast<float>(sprite.pivot.y) * scale,
                        static_cast<float>(sprite.w) * scale, static_cast<float>(sprite.h) * scale};
    SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND);
    SDL_RenderTexture(r_, tex, nullptr, &dst);
}

void Library::draw_tile(const dw::Pack& pack, const dw::Tileset& tileset, const dw::MapCell& cell, float cx,
                        float cy, float scale, double seconds, float opacity) {
    const dw::Atlas* atlas = tileset.atlas(cell.tile.atlas);
    const dw::Tile* tile = tileset.tile(cell.tile);
    if (!atlas || !tile) {
        return;
    }
    SDL_Texture* tex = texture(pack, atlas->image);
    if (!tex) {
        return;
    }
    int col = tile->col;
    if (tile->animated && tile->anim_frames > 1 && tile->anim_fps > 0.0) {
        col += static_cast<int>(std::floor(seconds * tile->anim_fps)) % tile->anim_frames;
    }
    const float tw = static_cast<float>(atlas->tile_w), th = static_cast<float>(atlas->tile_h);
    const SDL_FRect src{static_cast<float>(col) * tw, static_cast<float>(tile->row) * th, tw, th};
    const float ox = tile->origin ? static_cast<float>(tile->origin->x) : tw / 2;
    const float oy = tile->origin ? static_cast<float>(tile->origin->y) : th / 2;
    const SDL_FRect dst{cx - ox * scale, cy - oy * scale, tw * scale, th * scale};
    SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND);
    SDL_SetTextureAlphaModFloat(tex, opacity);
    if (cell.flags == 0) {
        SDL_RenderTexture(r_, tex, &src, &dst);
    } else {
        const dw::TileTransform t = dw::tile_transform(cell.flags);
        const SDL_FlipMode flip = t.flip_h ? SDL_FLIP_HORIZONTAL : t.flip_v ? SDL_FLIP_VERTICAL : SDL_FLIP_NONE;
        SDL_RenderTextureRotated(r_, tex, &src, &dst, t.angle, nullptr, flip);
    }
    SDL_SetTextureAlphaModFloat(tex, 1.0f);
}

void Library::draw_map(const dw::Pack& pack, const dw::Map& map, float x, float y, float scale, double seconds) {
    const dw::Tileset* tileset = pack.tileset(map.tileset);
    if (!tileset) {
        return;
    }
    const bool iso = tileset->shape == "isometric";
    const float w = static_cast<float>(map.tile_w) * scale, h = static_cast<float>(map.tile_h) * scale;
    for (const auto& layer : map.layers) {
        const float opacity = static_cast<float>(layer.opacity);
        for (const auto& cell : layer.cells) {
            const float col = static_cast<float>(cell.x), row = static_cast<float>(cell.y);
            const float cx = iso ? x + (col - row) * w / 2 : x + col * w + w / 2;
            const float cy = iso ? y + (col + row + 1) * h / 2 : y + row * h + h / 2;
            draw_tile(pack, *tileset, cell, cx, cy, scale, seconds, opacity);
        }
    }
}

void Library::draw_text(const dw::Pack& pack, const dw::Font& font, const std::string& text, float x, float y,
                        float scale, SDL_Color color) {
    for (const auto& q : dw::layout_text(font, text)) {
        SDL_Texture* tex = texture(pack, font.pages.at(static_cast<std::size_t>(q.glyph->page)));
        if (!tex) {
            continue;
        }
        const dw::Glyph& g = *q.glyph;
        const SDL_FRect src{static_cast<float>(g.x), static_cast<float>(g.y), static_cast<float>(g.w),
                            static_cast<float>(g.h)};
        const SDL_FRect dst{x + static_cast<float>(q.x) * scale, y + static_cast<float>(q.y) * scale,
                            static_cast<float>(g.w) * scale, static_cast<float>(g.h) * scale};
        SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND);
        if (font.tint) {
            SDL_SetTextureColorMod(tex, color.r, color.g, color.b);
            SDL_SetTextureAlphaMod(tex, color.a);
        }
        SDL_RenderTexture(r_, tex, &src, &dst);
        SDL_SetTextureColorMod(tex, 255, 255, 255);
        SDL_SetTextureAlphaMod(tex, 255);
    }
}

void Library::draw_ui_part(const dw::Pack& pack, const dw::UiPart& part, const SDL_FRect& dst, float scale) {
    SDL_Texture* tex = texture(pack, part.image);
    if (!tex) {
        return;
    }
    SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND);
    if (part.margins) {
        const auto& m = *part.margins;   // left, top, right, bottom
        SDL_RenderTexture9Grid(r_, tex, nullptr, static_cast<float>(m[0]), static_cast<float>(m[2]),
                               static_cast<float>(m[1]), static_cast<float>(m[3]), scale, &dst);
    } else {
        SDL_RenderTexture(r_, tex, nullptr, &dst);
    }
}

}  // namespace gfx::dotwork
