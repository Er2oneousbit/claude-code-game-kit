// ---------------------------------------------------------------------------
// Assets.cpp
// Purpose : Implementation of game::Assets (see Assets.hpp).
// Usage   : owned by game::Game, loaded on the first render.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): no Mix_Init (every sound is WAV, which needs no
//           decoder library; the old Mix_Init(MIX_INIT_OGG) had no Mix_Quit)
// Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): SDL3_image (no IMG_Init), SDL3_ttf (float sizes,
//           TTF_RenderText_Blended), SDL3_mixer (a mixer device, MIX_Audio, a pool of tracks for gains)
// ---------------------------------------------------------------------------
#include "game/Assets.hpp"

#include <SDL3_image/SDL_image.h>

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
constexpr int kAmbienceVolume = 40;  // of kMaxVolume (128)
constexpr int kVoices = 12;          // sound effects that can sound at once

// "assets/x" relative to the working directory, else next to the executable.
std::string find(const std::string& rel) {
    if (std::filesystem::exists(rel)) return rel;
    if (const char* base = SDL_GetBasePath()) {   // SDL3 owns the string
        const std::string candidate = std::string(base) + rel;
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
    for (MIX_Track* t : voices_) MIX_DestroyTrack(t);
    if (ambience_) MIX_DestroyTrack(ambience_);
    sounds_.clear();
    if (mixer_) MIX_DestroyMixer(mixer_);
    if (mix_) MIX_Quit();
    if (ttf_) TTF_Quit();
}

bool Assets::load_sheet(SDL_Renderer* renderer, const std::string& name, int rows) {
    const std::string path = find("assets/sprites/" + name + ".png");
    TexturePtr tex(IMG_LoadTexture(renderer, path.c_str()));
    if (!tex) {
        LOG_ERROR("assets", "cannot load " << path << ": " << SDL_GetError() << " (run python tools/make_sprites.py)");
        return false;
    }
    float fw = 0.0f;
    float fh = 0.0f;
    SDL_GetTextureSize(tex.get(), &fw, &fh);
    const int w = static_cast<int>(fw);
    const int h = static_cast<int>(fh);
    if (h != w * rows) {
        LOG_ERROR("assets", path << " is " << w << "x" << h << ", expected " << rows << " square cells in one column");
        return false;
    }
    sheets_[name] = Sheet{std::move(tex), w, rows};
    return true;
}

bool Assets::load(SDL_Renderer* renderer) {
    bool ok = true;   // SDL3_image needs no init: PNG is built in
    for (const char* n : {"hull_player", "hull_enemy", "hull_heavy", "turret_player", "turret_enemy"}) {
        ok = load_sheet(renderer, n, kDirections) && ok;
    }
    for (const char* n : {"crate", "rocks", "tree", "scrap_plate", "scrap_tire", "shell", "ground"}) {
        ok = load_sheet(renderer, n, 1) && ok;
    }

    ttf_ = TTF_Init();
    if (!ttf_) {
        LOG_ERROR("assets", "TTF_Init failed: " << SDL_GetError());
        return false;
    }
    for (int size : kFontSizes) {
        FontPtr f(TTF_OpenFont(find(kFont).c_str(), static_cast<float>(size)));
        if (!f) {
            LOG_ERROR("assets", "cannot load " << kFont << ": " << SDL_GetError());
            return false;
        }
        fonts_[size] = std::move(f);
    }

    // Sound is optional
    mix_ = MIX_Init();
    if (mix_ && (mixer_ = MIX_CreateMixerDevice(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, nullptr)) != nullptr) {
        for (const auto& [name, file] : kSounds) {
            AudioPtr a(MIX_LoadAudio(mixer_, find(file).c_str(), true));   // predecoded: short effects
            if (!a) {
                LOG_WARN("assets", "cannot load " << file << ": " << SDL_GetError());
                continue;
            }
            sounds_[name] = std::move(a);
        }
        for (int i = 0; i < kVoices; ++i) {
            if (MIX_Track* t = MIX_CreateTrack(mixer_)) voices_.push_back(t);
        }
        AudioPtr loop(MIX_LoadAudio(mixer_, find(kAmbience).c_str(), true));
        if (loop && (ambience_ = MIX_CreateTrack(mixer_)) != nullptr) {
            MIX_SetTrackAudio(ambience_, loop.get());
            MIX_SetTrackGain(ambience_, static_cast<float>(kAmbienceVolume) / kMaxVolume);
            const SDL_PropertiesID options = SDL_CreateProperties();
            SDL_SetNumberProperty(options, MIX_PROP_PLAY_LOOPS_NUMBER, -1);   // -1 loops: forever
            MIX_PlayTrack(ambience_, options);
            SDL_DestroyProperties(options);
            sounds_["ambience"] = std::move(loop);
        } else {
            LOG_WARN("assets", "cannot load " << kAmbience << ": " << SDL_GetError());
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
    if (!mixer_ || voices_.empty() || it == sounds_.end()) return;
    MIX_Track* voice = nullptr;
    for (MIX_Track* t : voices_) {          // a free track first
        if (!MIX_TrackPlaying(t)) {
            voice = t;
            break;
        }
    }
    if (!voice) {                           // else the one that started longest ago
        voice = voices_[next_voice_];
        next_voice_ = (next_voice_ + 1) % voices_.size();
    }
    MIX_SetTrackAudio(voice, it->second.get());
    MIX_SetTrackGain(voice, static_cast<float>(volume) / kMaxVolume);
    MIX_PlayTrack(voice, 0);
}

const Text& Assets::text(SDL_Renderer* renderer, const std::string& s, int size, SDL_Color color) {
    const std::string key = s + "|" + std::to_string(size) + "|" + std::to_string(color.r) + "," +
                            std::to_string(color.g) + "," + std::to_string(color.b);
    auto it = texts_.find(key);
    if (it != texts_.end()) return it->second;
    Text t;
    auto font = fonts_.find(size);
    if (font != fonts_.end() && !s.empty()) {
        if (SDL_Surface* surf = TTF_RenderText_Blended(font->second.get(), s.c_str(), 0, color)) {   // 0: to the NUL
            t.texture.reset(SDL_CreateTextureFromSurface(renderer, surf));
            t.w = surf->w;
            t.h = surf->h;
            SDL_DestroySurface(surf);
        }
    }
    return texts_.emplace(key, std::move(t)).first->second;
}

}  // namespace game
