// ---------------------------------------------------------------------------
// DotworkShowcase.hpp
// Purpose : The starter scene's Dotwork art (#60): when the game has Dotwork packs (assets/dotwork/*.assets.json),
//           the play screen shows a tile map, a label in the pack's font, a prop on the floor and a character
//           walking along it. With no packs it does nothing, so a fresh game looks as before.
// Usage   : DotworkShowcase art;  art.load(renderer, shell.game_dir() / "assets");
//           art.update(dt);  art.draw(floor_y, "label");      (Game.cpp: play_update, play_draw)
// Notes   : PROTOTYPE: it picks the first map, font and sprite (a prop) and the first animated sprite with a
//           walk_e clip (a character), else the first animated sprite's first clip. Replace it with the game's
//           own scene; the loader and draws it uses (gfx::dotwork::Library, core::dotwork) stay. Art is drawn at
//           whole-number scales (kArtScale), pivots on the floor line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <filesystem>
#include <memory>
#include <string>

#include "core/DotworkAssets.hpp"
#include "gfx/DotworkRender.hpp"

namespace game {

class DotworkShowcase {
public:
    // Loads every pack under assets_dir and picks what to show. False when there is nothing to show.
    bool load(SDL_Renderer* renderer, const std::filesystem::path& assets_dir);
    bool active() const { return art_ && (map_.item || font_.item || prop_.item || walker_.item); }

    void update(double dt);   // game seconds
    void draw(float floor_y, const std::string& label);

private:
    template <typename T>
    struct Pick {
        const core::dotwork::Pack* pack = nullptr;
        const T* item = nullptr;
    };

    std::unique_ptr<gfx::dotwork::Library> art_;
    Pick<core::dotwork::Map> map_;
    Pick<core::dotwork::Font> font_;
    Pick<core::dotwork::Sprite> prop_;
    Pick<core::dotwork::AnimatedSprite> walker_;
    const core::dotwork::Clip* walk_east_ = nullptr;
    const core::dotwork::Clip* walk_west_ = nullptr;   // may be the east clip when there is no west one
    bool walks_ = false;     // the walker has walk clips (else it plays in place)
    core::dotwork::ClipPlayer player_;
    double seconds_ = 0.0;   // animated tiles
    double x_ = 0.0;         // the walker's feet
    double dir_ = 1.0;       // +1 east, -1 west
};

}  // namespace game

// {{FOOTER}}
