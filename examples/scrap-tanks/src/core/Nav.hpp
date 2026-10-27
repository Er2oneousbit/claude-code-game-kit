// ---------------------------------------------------------------------------
// Nav.hpp
// Purpose : Grid pathfinding for the raiders and the autoplay bots: an occupancy grid built from
//           the cover circles, A* over it, and string pulling so paths are straight lines.
// Usage   : core::NavGrid nav(bounds, obstacles, 0.5, 1.0);  // cell size, clearance (tank radius)
//           std::vector<Vec2> path = nav.find_path(from, to);  // ends at `to` (or the nearest open spot); empty = none
//           core::NavGrid nav(bounds, obstacles, 0.5, 1.0, home);  // also floods the cells reachable from `home`
// Notes   : 8-connected, no corner cutting, octile heuristic, binary heap. A goal inside cover snaps to
//           the nearest walkable cell. Smoothing keeps a point only when the straight line to the next
//           one would clip a grown circle.
//           Grid rounding can seal walkable cells between cover into islands no path reaches (three arena
//           spots near (19, 6.25)). reachable() says whether a point is on the home component, so spot
//           pickers skip island spots instead of sending a tank to a goal find_path() cannot reach.
//
// Pseudocode:
//   blocked[cell] = cell center within (obstacle radius + clearance) of any obstacle, or near the edge
//   A*: open heap by f = g + h; pop best; expand 8 neighbors (diagonals only if both sides open); relax g
//   walk parents back from the goal; string-pull against the grown circles
//   reachable: one flood fill from `home` at construction, same moves as A* (so reachable == has a path)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): reachable() from a home cell (Fable review)
// ---------------------------------------------------------------------------
#pragma once

#include <optional>
#include <utility>
#include <vector>

#include "core/Geom.hpp"

namespace core {

class NavGrid {
public:
    // `home`: flood the cells reachable from there (core::Sim passes the player start). Without it,
    // reachable() is the same as walkable.
    NavGrid(Rect bounds, std::vector<Circle> obstacles, double cell, double clearance,
            std::optional<Vec2> home = std::nullopt);

    std::vector<Vec2> find_path(Vec2 from, Vec2 to) const;
    bool walkable(int c, int r) const;
    bool walkable_at(Vec2 p) const;
    Vec2 center(int c, int r) const;
    std::pair<int, int> cell_of(Vec2 p) const;
    std::optional<std::pair<int, int>> nearest_walkable(Vec2 p) const;
    // Does find_path() from `home` reach `p`? Uses the cell find_path() would snap `p` to.
    bool reachable(Vec2 p) const;

    // Obstacles grown by the clearance: a segment that misses all of them is safe for the agent.
    const std::vector<Circle>& grown() const { return grown_; }
    int cols() const { return cols_; }
    int rows() const { return rows_; }

private:
    std::vector<Vec2> smooth(Vec2 from, const std::vector<Vec2>& points) const;
    void flood_from(Vec2 home);

    Rect bounds_;
    double cell_;
    double clearance_;
    int cols_;
    int rows_;
    std::vector<Circle> grown_;
    std::vector<unsigned char> blocked_;
    std::vector<unsigned char> reach_;  // 1 = on the home component (all walkable cells without a home)
};

}  // namespace core
