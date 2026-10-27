// ---------------------------------------------------------------------------
// Arena.hpp
// Purpose : The scrapyard as data: bounds, cover (crates, rocks, trees as circles), the player's
//           start, raider spawn points, and the candidate spots raiders and bots pick cover from.
// Usage   : const core::Arena& a = core::scrapyard(); a.cover, a.spots, a.spawns
// Notes   : Engine-free. Meters; x right, y toward the camera. Each cover radius matches its sprite
//           (tools/make_sprites.py renders cover at 2.25x), so what you see is what stops a shell.
//           tests/test_arena.cpp guards it: everything reachable, no spawn inside cover.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <string>
#include <vector>

#include "core/Geom.hpp"

namespace core {

enum class CoverKind { Crate, Rocks, Tree };

struct Cover {
    CoverKind kind;
    Circle shape;
};

struct Arena {
    Rect bounds;
    Vec2 player_start;
    double player_heading;
    std::vector<Vec2> spawns;   // raider entry points, along the far edge
    std::vector<Cover> cover;
    std::vector<Vec2> spots;    // candidate standing spots: a grid plus a ring around each piece of cover

    std::vector<Circle> blockers() const {
        std::vector<Circle> out;
        for (const Cover& c : cover) out.push_back(c.shape);
        return out;
    }
};

// Cover sizes: the sprites are rendered to match (tools/make_sprites.py)
constexpr double kCrateR = 1.0;
constexpr double kRocksR = 1.5;
constexpr double kTreeR = 0.55;

inline const Arena& scrapyard() {
    static const Arena arena = [] {
        Arena a;
        a.bounds = {0.0, 0.0, 38.0, 24.0};
        a.player_start = {19.0, 21.0};
        a.player_heading = -kPi / 2;  // facing up the screen
        a.spawns = {{3.0, 2.5}, {35.0, 2.5}, {19.0, 2.0}, {2.0, 10.0}, {36.0, 10.0}};
        const auto crate = [&](double x, double y) { a.cover.push_back({CoverKind::Crate, {{x, y}, kCrateR}}); };
        const auto rocks = [&](double x, double y) { a.cover.push_back({CoverKind::Rocks, {{x, y}, kRocksR}}); };
        const auto tree = [&](double x, double y) { a.cover.push_back({CoverKind::Tree, {{x, y}, kTreeR}}); };
        // Mirrored left/right, so no side is safer (tests/test_arena.cpp checks it). A wall is n crates side by
        // side around a center x, so changing kCrateR keeps the layout symmetric.
        const auto wall = [&](double cx, double y, int n) {
            for (int i = 0; i < n; ++i) crate(cx + (i - (n - 1) / 2.0) * 2.0 * kCrateR, y);
        };
        wall(10.0, 17.0, 3); wall(28.0, 17.0, 3);   // lower walls, either side of the start
        rocks(19.0, 15.5);                          // center rock in front of the start
        rocks(4.5, 13.0);  rocks(33.5, 13.0);       // side rocks
        wall(13.6, 11.5, 2); wall(24.4, 11.5, 2);   // middle walls
        rocks(19.0, 9.0);                           // center rock
        rocks(9.0, 7.0);   rocks(29.0, 7.0);        // upper rocks
        wall(16.4, 4.5, 2);  wall(21.6, 4.5, 2);    // upper walls, a shell-wide gap in the middle
        tree(4.0, 19.5); tree(34.0, 19.5);
        tree(14.0, 20.0); tree(24.0, 20.0);
        tree(3.5, 4.5);  tree(34.5, 4.5);
        // Spots: a 2 m grid, plus 8 points hugging each piece of cover (where hiding works best)
        const auto clear = [&](Vec2 p) {
            if (!inside(a.bounds, p, 1.2)) return false;
            for (const Cover& c : a.cover) {
                if (distance(p, c.shape.c) < c.shape.r + 1.15) return false;
            }
            return true;
        };
        for (double y = 2.0; y <= 22.0; y += 2.0) {
            for (double x = 2.0; x <= 36.0; x += 2.0) {
                if (clear({x, y})) a.spots.push_back({x, y});
            }
        }
        for (const Cover& c : a.cover) {
            for (int k = 0; k < 8; ++k) {
                const Vec2 p = c.shape.c + from_angle(k * kPi / 4.0) * (c.shape.r + 1.25);
                if (clear(p)) a.spots.push_back(p);
            }
        }
        return a;
    }();
    return arena;
}

inline const char* cover_name(CoverKind k) {
    switch (k) {
        case CoverKind::Crate: return "crate";
        case CoverKind::Rocks: return "rocks";
        case CoverKind::Tree: return "tree";
    }
    return "?";
}

}  // namespace core
