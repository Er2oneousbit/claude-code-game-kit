// ---------------------------------------------------------------------------
// Ease.hpp
// Purpose : The standard easing curves (quad, cubic, sine, back, elastic, bounce) for tweens, UI pops and
//           camera moves. Pure functions, no SDL.
// Usage   : const double k = core::ease(core::Ease::OutBack, elapsed / duration);
//           value = from + (to - from) * k;
//           from data:  if (auto e = core::ease_from_name("out_cubic")) { ... core::ease(*e, t) ... }
// Notes   : t is clamped to 0..1 (back and elastic still overshoot inside that range). Names match the
//           reference (tools/golden_vectors.py EASES); an unknown name is an error (ease_from_name returns
//           std::nullopt), never a silent linear. Checked against data/golden/juice.json.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>
#include <cmath>
#include <optional>
#include <string_view>
#include <utility>

namespace core {

// ---- Constants (from the usual easing formulas, as in the reference) ----
constexpr double kEasePi = 3.14159265358979323846;
constexpr double kEaseBackC1 = 1.70158;               // back overshoot
constexpr double kEaseBackC3 = kEaseBackC1 + 1.0;
constexpr double kEaseElasticC4 = 2.0 * kEasePi / 3.0;
constexpr double kEaseBounceN1 = 7.5625;
constexpr double kEaseBounceD1 = 2.75;

enum class Ease {
    Linear, InQuad, OutQuad, InOutQuad, InCubic, OutCubic, InOutCubic,
    InSine, OutSine, InOutSine, InBack, OutBack, OutElastic, OutBounce,
};

// Names as data files and the golden vectors spell them.
constexpr std::pair<std::string_view, Ease> kEaseNames[] = {
    {"linear", Ease::Linear},         {"in_quad", Ease::InQuad},       {"out_quad", Ease::OutQuad},
    {"in_out_quad", Ease::InOutQuad}, {"in_cubic", Ease::InCubic},     {"out_cubic", Ease::OutCubic},
    {"in_out_cubic", Ease::InOutCubic}, {"in_sine", Ease::InSine},     {"out_sine", Ease::OutSine},
    {"in_out_sine", Ease::InOutSine}, {"in_back", Ease::InBack},       {"out_back", Ease::OutBack},
    {"out_elastic", Ease::OutElastic}, {"out_bounce", Ease::OutBounce},
};

inline std::optional<Ease> ease_from_name(std::string_view name) {
    for (const auto& [n, e] : kEaseNames) {
        if (n == name) {
            return e;
        }
    }
    return std::nullopt;
}

inline double ease_bounce_out(double t) {
    const double n1 = kEaseBounceN1;
    const double d1 = kEaseBounceD1;
    if (t < 1.0 / d1) {
        return n1 * t * t;
    }
    if (t < 2.0 / d1) {
        t -= 1.5 / d1;
        return n1 * t * t + 0.75;
    }
    if (t < 2.5 / d1) {
        t -= 2.25 / d1;
        return n1 * t * t + 0.9375;
    }
    t -= 2.625 / d1;
    return n1 * t * t + 0.984375;
}

// The eased value for progress t (clamped to 0..1).
inline double ease(Ease kind, double t) {
    t = std::min(std::max(t, 0.0), 1.0);
    const double u = 1.0 - t;
    const double w = -2.0 * t + 2.0;  // the in_out curves' second half
    switch (kind) {
        case Ease::Linear:     return t;
        case Ease::InQuad:     return t * t;
        case Ease::OutQuad:    return 1.0 - u * u;
        case Ease::InOutQuad:  return t < 0.5 ? 2.0 * t * t : 1.0 - w * w / 2.0;
        case Ease::InCubic:    return t * t * t;
        case Ease::OutCubic:   return 1.0 - u * u * u;
        case Ease::InOutCubic: return t < 0.5 ? 4.0 * t * t * t : 1.0 - w * w * w / 2.0;
        case Ease::InSine:     return 1.0 - std::cos(t * kEasePi / 2.0);
        case Ease::OutSine:    return std::sin(t * kEasePi / 2.0);
        case Ease::InOutSine:  return -(std::cos(kEasePi * t) - 1.0) / 2.0;
        case Ease::InBack:     return kEaseBackC3 * t * t * t - kEaseBackC1 * t * t;
        case Ease::OutBack:    return 1.0 + kEaseBackC3 * (t - 1.0) * (t - 1.0) * (t - 1.0)
                                      + kEaseBackC1 * (t - 1.0) * (t - 1.0);
        case Ease::OutElastic:
            if (t <= 0.0) return 0.0;
            if (t >= 1.0) return 1.0;
            return std::pow(2.0, -10.0 * t) * std::sin((t * 10.0 - 0.75) * kEaseElasticC4) + 1.0;
        case Ease::OutBounce:  return ease_bounce_out(t);
    }
    return t;  // unreachable with a valid enum; keeps compilers that do not see that quiet
}

}  // namespace core

// {{FOOTER}}
