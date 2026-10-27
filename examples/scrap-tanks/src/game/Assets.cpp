// ---------------------------------------------------------------------------
// Assets.cpp
// Purpose : Implementation of game::Assets (see Assets.hpp).
// Usage   : owned by game::Game, loaded on the first render.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): no Mix_Init (every sound is WAV, which needs no
//           decoder library; the old Mix_Init(MIX_INIT_OGG) had no Mix_Quit)
// ---------------------------------------------------------------------------
#include "game/Assets.hpp"

#include <SDL_image.h>

#include <filesystem>
#include <stdexcept>

#include "core/Log.hpp"

namespace game {

namespace {

constexpr const char* kFont = "assets/fonts/Kenney Future.ttf";
constexpr int kFontSizes[] = {16, 22, 34};
constexpr int kDirections = 32;  // tools/make_sprites.py DIRECTIONS

// Sound name -> file (ElevenLabs, docs/ASSET_LOG.md A-0005 to A-0009)
const std::pair<const char*, const char*> kSounds[] = {
    {"fire_player", "assets/audio/tank-fire.wav"},
    {"fire_raider", "assets/audio/raider-fire.wav"},
    {"hit", "assets/audio/shell-hit.wav"},
    {"destroyed", "assets/audio/tank-explode.wav"},
    {"pickup", "assets/audio/scrap-pickup.wav"},
};
// The scrapyard's wind, looping under everything from the first frame (A-0010)
constexpr const char* kAmbience = "assets/audio/scrapyard-ambience.wav";
constexpr int kAmbienceVolume = 40;  // of MIX_MAX_VOLUME (128)

// "assets/x" relative to the working directory, else next to the executable.
std::string find(const std::string& rel) {
    if (std::filesystem::exists(rel)) return rel;
    if (char* base = SDL_GetBasePath()) {
        const std::string candidate = std::string(base) + rel;
        SDL_free(base);
        if (std::filesystem::exists(candidate)) return candidate;
    }
    return rel;  // the loader reports the miss with this path
}

}  // namespace

Assets::~Assets() {
    // Free everything before shutting the libraries down
    texts_.clear();
    sheets_.clear();
    fonts_.clear();
    sounds_.clear();
    if (audio_) Mix_CloseAudio();
    if (ttf_) TTF_Quit();
    if (img_) IMG_Quit();
}

bool Assets::load_sheet(SDL_Renderer* renderer, const std::string& name, int rows) {
    const std::string path = find("assets/sprites/" + name + ".png");
    TexturePtr tex(IMG_LoadTexture(renderer, path.c_str()));
    if (!tex) {
        LOG_ERROR("assets", "cannot load " << path << ": " << IMG_GetError() << " (run python tools/make_sprites.py)");
        return false;
    }
    int w = 0;
    int h = 0;
    SDL_QueryTexture(tex.get(), nullptr, nullptr, &w, &h);
    if (h != w * rows) {
        LOG_ERROR("assets", path << " is " << w << "x" << h << ", expected " << rows << " square cells in one column");
        return false;
    }
    sheets_[name] = Sheet{std::move(tex), w, rows};
    return true;
}

bool Assets::load(SDL_Renderer* renderer) {
    img_ = (IMG_Init(IMG_INIT_PNG) & IMG_INIT_PNG) != 0;
    if (!img_) {
        LOG_ERROR("assets", "SDL_image without PNG support: " << IMG_GetError());
        return false;
    }
    bool ok = true;
    for (const char* n : {"hull_player", "hull_enemy", "hull_heavy", "turret_player", "turret_enemy"}) {
        ok = load_sheet(renderer, n, kDirections) && ok;
    }
    for (const char* n : {"crate", "rocks", "tree", "scrap_plate", "scrap_tire", "shell", "ground"}) {
        ok = load_sheet(renderer, n, 1) && ok;
    }

    ttf_ = TTF_Init() == 0;
    if (!ttf_) {
        LOG_ERROR("assets", "TTF_Init failed: " << TTF_GetError());
        return false;
    }
    for (int size : kFontSizes) {
        FontPtr f(TTF_OpenFont(find(kFont).c_str(), size));
        if (!f) {
            LOG_ERROR("assets", "cannot load " << kFont << ": " << TTF_GetError());
            return false;
        }
        fonts_[size] = std::move(f);
    }

    // Sound is optional
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) == 0 && Mix_OpenAudio(44100, MIX_DEFAULT_FORMAT, 2, 1024) == 0) {
        audio_ = true;
        for (const auto& [name, file] : kSounds) {
            ChunkPtr c(Mix_LoadWAV(find(file).c_str()));
            if (!c) {
                LOG_WARN("assets", "cannot load " << file << ": " << Mix_GetError());
                continue;
            }
            sounds_[name] = std::move(c);
        }
        if (ChunkPtr loop{Mix_LoadWAV(find(kAmbience).c_str())}) {
            Mix_VolumeChunk(loop.get(), kAmbienceVolume);
            Mix_PlayChannel(-1, loop.get(), -1);  // -1 loops: forever
            sounds_["ambience"] = std::move(loop);
        } else {
            LOG_WARN("assets", "cannot load " << kAmbience << ": " << Mix_GetError());
        }
    } else {
        LOG_WARN("assets", "no audio device, running silent: " << SDL_GetError());
    }
    loaded_ = ok;
    return ok;
}

const Sheet& Assets::sheet(const std::string& name) const {
    const auto it = sheets_.find(name);
    if (it == sheets_.end()) throw std::runtime_error("sprite sheet not loaded: " + name);
    return it->second;
}

void Assets::play(const std::string& sound, int volume) {
    const auto it = sounds_.find(sound);
    if (!audio_ || it == sounds_.end()) return;
    Mix_VolumeChunk(it->second.get(), volume);
    Mix_PlayChannel(-1, it->second.get(), 0);
}

const Text& Assets::text(SDL_Renderer* renderer, const std::string& s, int size, SDL_Color color) {
    const std::string key = s + "|" + std::to_string(size) + "|" + std::to_string(color.r) + "," +
                            std::to_string(color.g) + "," + std::to_string(color.b);
    auto it = texts_.find(key);
    if (it != texts_.end()) return it->second;
    Text t;
    auto font = fonts_.find(size);
    if (font != fonts_.end() && !s.empty()) {
        if (SDL_Surface* surf = TTF_RenderUTF8_Blended(font->second.get(), s.c_str(), color)) {
            t.texture.reset(SDL_CreateTextureFromSurface(renderer, surf));
            t.w = surf->w;
            t.h = surf->h;
            SDL_FreeSurface(surf);
        }
    }
    return texts_.emplace(key, std::move(t)).first->second;
}

}  // namespace game
