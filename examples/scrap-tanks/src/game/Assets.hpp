// ---------------------------------------------------------------------------
// Assets.hpp
// Purpose : Everything loaded from assets/: sprite sheets (SDL3_image), the HUD font (SDL3_ttf) and
//           sounds (SDL3_mixer), RAII-owned, plus a cache of rendered text (ADR 0001).
// Usage   : Assets a; if (!a.load(renderer)) quit;  a.sheet("hull_player"), a.text(r, "WAVE 1", 24, color)
// Notes   : Paths are tried relative to the working directory (dev.py run and smoke start in the
//           project root), then next to the executable. Sound is optional: no audio device (a server,
//           headless smoke) logs a warning and the game runs silent. Sound effects play on a small pool of
//           mixer tracks (kVoices): a new sound takes a free track, else the one that started longest ago.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): SDL3 and its image, font and mixer libraries
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>
#include <SDL3_mixer/SDL_mixer.h>
#include <SDL3_ttf/SDL_ttf.h>

#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace game {

struct TextureDeleter { void operator()(SDL_Texture* t) const { if (t) SDL_DestroyTexture(t); } };
struct FontDeleter    { void operator()(TTF_Font* f) const    { if (f) TTF_CloseFont(f); } };
struct AudioDeleter   { void operator()(MIX_Audio* a) const   { if (a) MIX_DestroyAudio(a); } };
using TexturePtr = std::unique_ptr<SDL_Texture, TextureDeleter>;
using FontPtr    = std::unique_ptr<TTF_Font, FontDeleter>;
using AudioPtr   = std::unique_ptr<MIX_Audio, AudioDeleter>;

constexpr int kMaxVolume = 128;   // play()'s volume scale (SDL2_mixer's MIX_MAX_VOLUME, kept for the game's numbers)

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
    void play(const std::string& sound, int volume = kMaxVolume / 2);
    // Rendered text, cached by (text, size, color).
    const Text& text(SDL_Renderer* renderer, const std::string& s, int size, SDL_Color color);

private:
    bool load_sheet(SDL_Renderer* renderer, const std::string& name, int rows);

    bool loaded_ = false;
    bool ttf_ = false;
    bool mix_ = false;
    MIX_Mixer* mixer_ = nullptr;          // nullptr: no audio device, the game runs silent
    std::vector<MIX_Track*> voices_;      // sound effects, reused round the pool
    size_t next_voice_ = 0;
    MIX_Track* ambience_ = nullptr;
    std::map<std::string, Sheet> sheets_;
    std::map<int, FontPtr> fonts_;
    std::map<std::string, AudioPtr> sounds_;
    std::map<std::string, Text> texts_;
};

}  // namespace game
