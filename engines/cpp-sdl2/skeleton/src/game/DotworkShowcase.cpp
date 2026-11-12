// ---------------------------------------------------------------------------
// DotworkShowcase.cpp
// Purpose : Implementation of game::DotworkShowcase (see DotworkShowcase.hpp).
// Usage   : Game.cpp creates one in init() and calls update() and draw() from the play screen.
// Notes   : PROTOTYPE layout in the 640x360 design space: the map in the top right corner (at kArtScale when it
//           fits the corner, else 1x), the label under it, the prop and the walker standing on the floor line.
//
// Pseudocode:
//   load: Library::load_all -> pick map, font, prop (a sprite with role props first), walker (walk_e / walk_w)
//   update: advance the clip; walk; at an edge turn round and switch to the other direction's clip
//   draw: map (+ its objects by y) -> label -> prop -> walker
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the map box from map_bounds (#285), so an
//           isometric map's left half is not drawn off the box
// ---------------------------------------------------------------------------
#include "game/DotworkShowcase.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

#include "shell/Draw.hpp"   // the design space (shell::style::kBaseW)

namespace game {

namespace {

namespace dw = core::dotwork;

// ---- Tunables ----
constexpr float kArtScale = 2.0f;          // whole numbers only (nearest filtering)
constexpr float kMargin = 16.0f;           // design px from the screen's edges
constexpr float kMapBoxW = 288.0f;         // the corner the map may fill at kArtScale (design px)
constexpr float kMapBoxH = 176.0f;
constexpr double kWalkSpeed = 48.0;        // design px per second
constexpr double kWalkLeft = 160.0;        // the walker paces between these x (design px)
constexpr double kWalkRight = 560.0;
constexpr float kPropX = 96.0f;            // the prop's pivot on the floor
constexpr float kLabelY = 48.0f;           // the label's top without a map (below the shell's key hints)
constexpr SDL_Color kLabelColor{250, 199, 82, 255};

// Which animated sprite walks: a character with walk clips, then anything with walk clips, then anything.
int walker_score(const dw::AnimatedSprite& a) {
    if (a.clips.empty()) {
        return 0;
    }
    if (!a.directed("walk", "e")) {
        return 1;
    }
    return a.role == "characters" ? 3 : 2;
}

}  // namespace

bool DotworkShowcase::load(SDL_Renderer* renderer, const std::filesystem::path& assets_dir) {
    art_ = std::make_unique<gfx::dotwork::Library>(renderer);
    if (art_->load_all(assets_dir) == 0) {
        art_.reset();
        return false;
    }
    for (const auto& pack : art_->packs()) {
        if (!map_.item && !pack.maps.empty()) {
            map_ = {&pack, &pack.maps.front()};
        }
        if (!font_.item && !pack.fonts.empty()) {
            font_ = {&pack, &pack.fonts.front()};
        }
        for (const auto& s : pack.sprites) {
            if (!prop_.item || (prop_.item->role != "props" && s.role == "props")) {
                prop_ = {&pack, &s};
            }
        }
        for (const auto& a : pack.animated_sprites) {
            if (walker_score(a) > (walker_.item ? walker_score(*walker_.item) : 0)) {
                walker_ = {&pack, &a};
            }
        }
    }
    if (walker_.item) {
        walk_east_ = walker_.item->directed("walk", "e");
        walks_ = walk_east_ != nullptr;
        if (walks_) {
            const dw::Clip* west = walker_.item->directed("walk", "w");
            walk_west_ = west ? west : walk_east_;
        } else {
            walk_east_ = walk_west_ = &walker_.item->clips.front();   // it plays its first clip where it stands
        }
    }
    x_ = kWalkRight;   // starts at the right, walking west (away from the box, which starts on the left)
    dir_ = -1.0;
    player_.play(walk_west_);
    return active();
}

void DotworkShowcase::update(double dt) {
    if (!art_) {
        return;
    }
    seconds_ += dt;
    player_.update(dt);
    if (!walks_) {
        return;
    }
    x_ += dir_ * kWalkSpeed * dt;
    if ((dir_ > 0 && x_ >= kWalkRight) || (dir_ < 0 && x_ <= kWalkLeft)) {
        x_ = std::clamp(x_, kWalkLeft, kWalkRight);
        dir_ = -dir_;
        player_.play(dir_ > 0 ? walk_east_ : walk_west_);
    }
}

void DotworkShowcase::draw(float floor_y, const std::string& label) {
    if (!art_) {
        return;
    }
    float label_x = kMargin, label_y = kLabelY;   // under the map when there is one
    if (map_.item) {
        const dw::Map& m = *map_.item;
        // What the cells cover (an isometric map reaches left of its pixel 0: bounds.left is negative there)
        const dw::MapBounds bounds = dw::map_bounds(m);
        const float map_w = static_cast<float>(bounds.w), map_h = static_cast<float>(bounds.h);
        const float fit = map_w * kArtScale <= kMapBoxW && map_h * kArtScale <= kMapBoxH ? kArtScale : 1.0f;
        const float box_x = static_cast<float>(shell::style::kBaseW) - kMargin - map_w * fit;   // the box's left
        const float mx = box_x - static_cast<float>(bounds.left) * fit;                          // map pixel 0
        art_->draw_map(*map_.pack, m, mx, kMargin, fit, seconds_);
        label_x = box_x;
        label_y = kMargin + map_h * fit + kMargin / 2;
        std::vector<const dw::MapObject*> objects;   // props on the map, sorted by y (feet)
        for (const auto& o : m.objects) {
            objects.push_back(&o);
        }
        std::stable_sort(objects.begin(), objects.end(), [](const auto* l, const auto* r) { return l->y < r->y; });
        for (const auto* o : objects) {
            if (const dw::Sprite* s = map_.pack->sprite(o->asset)) {
                art_->draw_sprite(*map_.pack, *s, mx + static_cast<float>(o->x) * fit, kMargin + static_cast<float>(o->y) * fit, fit);
            }
        }
    }
    if (font_.item) {
        // A font's pages are already drawn at its `scale`: only make up the rest of kArtScale (1:1 when it is there)
        const float extra = std::max(1.0f, std::round(kArtScale / static_cast<float>(std::max(1.0, font_.item->scale))));
        art_->draw_text(*font_.pack, *font_.item, label, label_x, label_y, extra, kLabelColor);
    }
    if (prop_.item) {
        art_->draw_sprite(*prop_.pack, *prop_.item, kPropX, floor_y, kArtScale);
    }
    if (walker_.item && player_.clip()) {
        art_->draw_frame(*walker_.pack, *walker_.item, *player_.clip(), player_.frame(), static_cast<float>(x_), floor_y,
                         kArtScale);
    }
}

}  // namespace game

// {{FOOTER}}
