// ---------------------------------------------------------------------------
// Assets.hpp
// Purpose : Everything loaded from assets/: sprite sheets (SDL2_image), the HUD font (SDL2_ttf) and
//           sounds (SDL2_mixer), RAII-owned, plus a cache of rendered text (ADR 0001).
// Usage   : Assets a; if (!a.load(renderer)) quit;  a.sheet("hull_player"), a.text(r, "WAVE 1", 24, color)
// Notes   : Paths are tried relative to the working directory (dev.py run and smoke start in the
//           project root), then next to the executable. Sound is optional: no audio device (a server,
//           headless smoke) logs a warning and the game runs silent.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL.h>
#include <SDL_mixer.h>
#include <SDL_ttf.h>

#include <map>
#include <memory>
#include <string>
#include <utility>

namespace game {

struct TextureDeleter { void operator()(SDL_Texture* t) const { if (t) SDL_DestroyTexture(t); } };
struct FontDeleter    { void operator()(TTF_Font* f) const    { if (f) TTF_CloseFont(f); } };
struct ChunkDeleter   { void operator()(Mix_Chunk* c) const   { if (c) Mix_FreeChunk(c); } };
using TexturePtr = std::unique_ptr<SDL_Texture, TextureDeleter>;
using FontPtr    = std::unique_ptr<TTF_Font, FontDeleter>;
using ChunkPtr   = std::unique_ptr<Mix_Chunk, ChunkDeleter>;

// One sprite sheet: square cells, one column, `rows` directions (tools/make_sprites.py)
struct Sheet {
    TexturePtr texture;
    int cell = 0;
    int rows = 1;
};

struct Text {
    TexturePtr texture;
    int w = 0;
    int h = 0;
};

class Assets {
public:
    Assets() = default;
    ~Assets();
    Assets(const Assets&) = delete;
    Assets& operator=(const Assets&) = delete;

    // Loads everything; logs and returns false on a missing or broken file.
    bool load(SDL_Renderer* renderer);
    bool loaded() const { return loaded_; }

    const Sheet& sheet(const std::string& name) const;
    void play(const std::string& sound, int volume = MIX_MAX_VOLUME / 2);
    // Rendered text, cached by (text, size, color).
    const Text& text(SDL_Renderer* renderer, const std::string& s, int size, SDL_Color color);

private:
    bool load_sheet(SDL_Renderer* renderer, const std::string& name, int rows);

    bool loaded_ = false;
    bool ttf_ = false;
    bool img_ = false;
    bool audio_ = false;
    std::map<std::string, Sheet> sheets_;
    std::map<int, FontPtr> fonts_;
    std::map<std::string, ChunkPtr> sounds_;
    std::map<std::string, Text> texts_;
};

}  // namespace game
