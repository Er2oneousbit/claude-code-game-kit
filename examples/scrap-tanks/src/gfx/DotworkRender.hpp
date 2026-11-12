// ---------------------------------------------------------------------------
// DotworkRender.hpp
// Purpose : The SDL half of the Dotwork asset importer (#60): loads every pack of the game (core::dotwork, the
//           SDL-free loader) and their PNGs as textures, and draws what they describe: a clip's frame at its pivot,
//           a sprite with its shadow, a tile map's layers, text in a bitmap font, a UI part (9-slice).
// Usage   : gfx::dotwork::Library art(renderer);  art.load_all(shell.game_dir() / "assets");
//           for (const auto& pack : art.packs()) ...   // core::dotwork::Pack: the loaded structs
//           art.draw_frame(pack, *clip, player.frame(), x, y, 2.0f);   // (x, y) is where the pivot lands
//           art.draw_map(pack, map, x, y, 2.0f, seconds);  art.draw_text(pack, font, "Hello", x, y, 2.0f, {255, 255, 255, 255});
// Notes   : PNGs load with SDL's own PNG loader (SDL_LoadPNG, SDL 3.4+): no SDL3_image or stb_image needed. Every
//           texture is nearest-filtered (SDL_SCALEMODE_NEAREST, no mipmaps), so draw at whole-number scales.
//           Textures load at load_all (a PNG that fails is an [ERROR] log line, which fails dev.py smoke) and
//           live until the Library goes, which must be before the renderer (Game owns it; main.cpp destroys the
//           game first). A failed manifest or broken asset is logged as an error and left out; unknown kinds
//           are warnings. The extra kinds load too: a background's layer images, a particle set's texture, a
//           transition's rule image, a normal map's image (texture only: SDL's 2D renderer has no lighting) and
//           a plain image are textures by path (`texture(pack, rel)`), their data in the pack's structs; the
//           object that scrolls, emits, wipes or lights with them is the game's (or the shader recipes').
//           Coordinates are the art's, y down: no conversion. Tile maps: every cell's centre is the spec's
//           core::dotwork::cell_centre (square ((col + 0.5) w, (row + 0.5) h); isometric, Godot's diamond-down
//           layout, ((col - row + 1) w / 2, (col + row + 1) h / 2): cell (0, 0) of a 16x8 set at (8, 4)) scaled
//           and moved by (x, y), map pixel (0, 0); on an isometric map cells with row > col reach left of x
//           (core::dotwork::map_bounds says how far). A tile's image is drawn with its `origin` (default: its
//           centre) on the cell's centre; animated tiles step through the next cells to the right at their fps;
//           flags flip and transpose (tile_transform).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the cell centre formula
//           shared with the loader, the extra kinds' textures loaded
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <cstddef>
#include <filesystem>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "core/DotworkAssets.hpp"

namespace gfx::dotwork {

namespace dw = core::dotwork;

class Library {
public:
    explicit Library(SDL_Renderer* renderer) : r_(renderer) {}
    Library(const Library&) = delete;
    Library& operator=(const Library&) = delete;

    // Loads every <assets_dir>/dotwork/*.assets.json and the textures its assets draw from. Returns the number
    // of packs that loaded (a pack with errors keeps its good assets and counts too). Logs every problem.
    std::size_t load_all(const std::filesystem::path& assets_dir);
    const std::vector<dw::Pack>& packs() const { return packs_; }
    std::size_t texture_count() const { return textures_.size(); }

    // The texture of a path in a pack (loaded on first use, cached); nullptr when it cannot load (logged once).
    SDL_Texture* texture(const dw::Pack& pack, const std::string& rel);

    // Frame `frame` of a clip with its pivot at (x, y); additive when the sprite's blend is add.
    void draw_frame(const dw::Pack& pack, const dw::AnimatedSprite& sprite, const dw::Clip& clip, std::size_t frame,
                    float x, float y, float scale);
    // A sprite with its pivot at (x, y), its contact shadow (when it has one) behind it.
    void draw_sprite(const dw::Pack& pack, const dw::Sprite& sprite, float x, float y, float scale);
    // Every layer of a map, first to last (objects are the caller's: draw them sorted by y with the characters).
    // `seconds` drives animated tiles.
    void draw_map(const dw::Pack& pack, const dw::Map& map, float x, float y, float scale, double seconds);
    // Text with its top-left at (x, y); a tint font takes `color`, a coloured one ignores it. A font's pages,
    // glyph rects and metrics are already at the manifest's `scale` (Dotwork upscales them): `scale` here is extra
    // on top, normally 1 (never multiply by font.scale again).
    void draw_text(const dw::Pack& pack, const dw::Font& font, const std::string& text, float x, float y, float scale,
                   SDL_Color color);
    // A UI part stretched into dst (9-slice when it has margins; the corners are drawn at `scale`). Like fonts, a
    // part's image and margins are already at its `scale`: pass 1 to draw them as they are.
    void draw_ui_part(const dw::Pack& pack, const dw::UiPart& part, const SDL_FRect& dst, float scale = 1.0f);

private:
    struct TextureDeleter {
        void operator()(SDL_Texture* t) const { SDL_DestroyTexture(t); }
    };
    using TexturePtr = std::unique_ptr<SDL_Texture, TextureDeleter>;

    SDL_Renderer* r_;
    std::vector<dw::Pack> packs_;
    std::map<std::string, TexturePtr> textures_;   // by resolved path; nullptr = failed (not retried)

    void preload(const dw::Pack& pack);
    void draw_tile(const dw::Pack& pack, const dw::Tileset& tileset, const dw::MapCell& cell, float cx, float cy,
                   float scale, double seconds, float opacity);
};

}  // namespace gfx::dotwork
