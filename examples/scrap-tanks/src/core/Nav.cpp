// ---------------------------------------------------------------------------
// Nav.cpp
// Purpose : Implementation of core::NavGrid (see Nav.hpp for the algorithm).
// Usage   : built once per arena by core::Sim; find_path() is called by raiders and bots.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): flood fill for reachable() (Fable review)
// ---------------------------------------------------------------------------
#include "core/Nav.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>

namespace core {

namespace {
constexpr double kSqrt2 = 1.41421356237309504880;
}

NavGrid::NavGrid(Rect bounds, std::vector<Circle> obstacles, double cell, double clearance, std::optional<Vec2> home)
    : bounds_(bounds),
      cell_(cell),
      clearance_(clearance),
      cols_(static_cast<int>(std::round((bounds.max_x - bounds.min_x) / cell))),
      rows_(static_cast<int>(std::round((bounds.max_y - bounds.min_y) / cell))) {
    for (const Circle& o : obstacles) grown_.push_back({o.c, o.r + clearance});
    blocked_.assign(static_cast<size_t>(cols_) * static_cast<size_t>(rows_), 0);
    for (int r = 0; r < rows_; ++r) {
        for (int c = 0; c < cols_; ++c) {
            const Vec2 p = center(c, r);
            bool blocked = !inside(bounds_, p, clearance_);
            for (const Circle& g : grown_) {
                if (distance(p, g.c) < g.r) blocked = true;
            }
            blocked_[static_cast<size_t>(r * cols_ + c)] = blocked ? 1 : 0;
        }
    }
    if (home) {
        flood_from(*home);
    } else {
        reach_.resize(blocked_.size());
        for (size_t i = 0; i < blocked_.size(); ++i) reach_[i] = blocked_[i] ? 0 : 1;
    }
}

void NavGrid::flood_from(Vec2 home) {
    reach_.assign(blocked_.size(), 0);
    const auto start = nearest_walkable(home);
    if (!start) return;
    std::vector<std::pair<int, int>> stack{*start};
    reach_[static_cast<size_t>(start->second * cols_ + start->first)] = 1;
    while (!stack.empty()) {
        const auto [c, r] = stack.back();
        stack.pop_back();
        for (int dr = -1; dr <= 1; ++dr) {
            for (int dc = -1; dc <= 1; ++dc) {
                // The same moves as find_path(), so "reachable" and "has a path" never disagree
                if ((dc == 0 && dr == 0) || !walkable(c + dc, r + dr)) continue;
                if (dc != 0 && dr != 0 && (!walkable(c + dc, r) || !walkable(c, r + dr))) continue;
                unsigned char& seen = reach_[static_cast<size_t>((r + dr) * cols_ + c + dc)];
                if (!seen) {
                    seen = 1;
                    stack.push_back({c + dc, r + dr});
                }
            }
        }
    }
}

bool NavGrid::reachable(Vec2 p) const {
    const auto cell = nearest_walkable(p);
    return cell && reach_[static_cast<size_t>(cell->second * cols_ + cell->first)] != 0;
}

Vec2 NavGrid::center(int c, int r) const {
    return {bounds_.min_x + (c + 0.5) * cell_, bounds_.min_y + (r + 0.5) * cell_};
}

std::pair<int, int> NavGrid::cell_of(Vec2 p) const {
    const int c = static_cast<int>(std::floor((p.x - bounds_.min_x) / cell_));
    const int r = static_cast<int>(std::floor((p.y - bounds_.min_y) / cell_));
    return {std::clamp(c, 0, cols_ - 1), std::clamp(r, 0, rows_ - 1)};
}

bool NavGrid::walkable(int c, int r) const {
    return c >= 0 && r >= 0 && c < cols_ && r < rows_ && blocked_[static_cast<size_t>(r * cols_ + c)] == 0;
}

bool NavGrid::walkable_at(Vec2 p) const {
    const auto [c, r] = cell_of(p);
    return walkable(c, r);
}

std::optional<std::pair<int, int>> NavGrid::nearest_walkable(Vec2 p) const {
    const auto [c0, r0] = cell_of(p);
    if (walkable(c0, r0)) return std::make_pair(c0, r0);
    for (int ring = 1; ring < std::max(cols_, rows_); ++ring) {
        std::optional<std::pair<int, int>> best;
        double best_d = std::numeric_limits<double>::infinity();
        for (int dr = -ring; dr <= ring; ++dr) {
            for (int dc = -ring; dc <= ring; ++dc) {
                if (std::max(std::abs(dc), std::abs(dr)) != ring || !walkable(c0 + dc, r0 + dr)) continue;
                const double d = distance(center(c0 + dc, r0 + dr), p);
                if (d < best_d) {
                    best_d = d;
                    best = std::make_pair(c0 + dc, r0 + dr);
                }
            }
        }
        if (best) return best;
    }
    return std::nullopt;
}

std::vector<Vec2> NavGrid::find_path(Vec2 from, Vec2 to) const {
    const auto start = nearest_walkable(from);
    const auto goal = nearest_walkable(to);
    if (!start || !goal) return {};
    const Vec2 goal_point = walkable_at(to) ? to : center(goal->first, goal->second);
    const auto idx = [this](int c, int r) { return r * cols_ + c; };
    const int s = idx(start->first, start->second);
    const int g = idx(goal->first, goal->second);
    if (s == g) return {goal_point};

    const size_t n = static_cast<size_t>(cols_) * static_cast<size_t>(rows_);
    std::vector<double> cost(n, std::numeric_limits<double>::infinity());
    std::vector<int> parent(n, -1);
    std::vector<unsigned char> closed(n, 0);
    const auto h = [&](int i) {
        const double dc = std::abs(i % cols_ - goal->first);
        const double dr = std::abs(i / cols_ - goal->second);
        return (dc + dr + (kSqrt2 - 2.0) * std::min(dc, dr)) * cell_;
    };
    using Item = std::pair<double, int>;  // (f, index), smallest f first
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> open;
    cost[static_cast<size_t>(s)] = 0.0;
    open.push({h(s), s});
    while (!open.empty()) {
        const int cur = open.top().second;
        open.pop();
        if (cur == g) break;
        if (closed[static_cast<size_t>(cur)]) continue;
        closed[static_cast<size_t>(cur)] = 1;
        const int c = cur % cols_;
        const int r = cur / cols_;
        for (int dr = -1; dr <= 1; ++dr) {
            for (int dc = -1; dc <= 1; ++dc) {
                if ((dc == 0 && dr == 0) || !walkable(c + dc, r + dr)) continue;
                if (dc != 0 && dr != 0 && (!walkable(c + dc, r) || !walkable(c, r + dr))) continue;  // no corner cutting
                const int nb = idx(c + dc, r + dr);
                const double ng = cost[static_cast<size_t>(cur)] + ((dc != 0 && dr != 0) ? kSqrt2 : 1.0) * cell_;
                if (ng < cost[static_cast<size_t>(nb)]) {
                    cost[static_cast<size_t>(nb)] = ng;
                    parent[static_cast<size_t>(nb)] = cur;
                    open.push({ng + h(nb), nb});
                }
            }
        }
    }
    if (parent[static_cast<size_t>(g)] == -1) return {};

    std::vector<Vec2> cells;
    for (int i = g; i != s; i = parent[static_cast<size_t>(i)]) cells.push_back(center(i % cols_, i / cols_));
    std::reverse(cells.begin(), cells.end());
    cells.back() = goal_point;
    return smooth(from, cells);
}

std::vector<Vec2> NavGrid::smooth(Vec2 from, const std::vector<Vec2>& points) const {
    std::vector<Vec2> out;
    Vec2 anchor = from;
    size_t i = 0;
    while (i < points.size()) {
        size_t far = i;
        for (size_t j = points.size() - 1; j > i; --j) {
            if (line_of_sight(anchor, points[j], grown_)) {
                far = j;
                break;
            }
        }
        out.push_back(points[far]);
        anchor = points[far];
        i = far + 1;
    }
    return out;
}

}  // namespace core
