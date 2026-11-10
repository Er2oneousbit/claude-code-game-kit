// ---------------------------------------------------------------------------
// Draw.cpp
// Purpose : Implementation of the shell's drawing layer (see Draw.hpp).
// Usage   : compiled into game_lib; call through Draw.hpp.
// Notes   : SDL_RenderDebugText draws at the renderer's current scale, so a text of size k is drawn with
//           SDL_SetRenderScale(k) at coordinates divided by k, then the scale goes back to 1. The record keeps
//           design-space boxes; the sweep multiplies them by the window's scale itself.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "shell/Draw.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <utility>

#include "core/ShellLogic.hpp"

namespace shell {

using nlohmann::json;

namespace {

constexpr double kOpaque = 0.9;   // a fill this opaque hides what is under it (the sweep's COVER_ALPHA)

SDL_FRect frect(double x, double y, double w, double h) {
    return SDL_FRect{static_cast<float>(x), static_cast<float>(y), static_cast<float>(w), static_cast<float>(h)};
}

bool inside(double px, double py, double x, double y, double w, double h) {
    return px >= x && px <= x + w && py >= y && py <= y + h;
}

}  // namespace

std::string hex_of(Rgb c) {
    char buf[8];
    std::snprintf(buf, sizeof buf, "#%02x%02x%02x", c.r, c.g, c.b);
    return buf;
}

std::optional<Rgb> rgb_from_hex(const std::string& hex) {
    if (hex.size() != 7 || hex[0] != '#') {
        return std::nullopt;
    }
    Uint8 parts[3] = {0, 0, 0};
    for (int i = 0; i < 3; ++i) {
        char* end = nullptr;
        const std::string pair = hex.substr(static_cast<std::size_t>(1 + 2 * i), 2);
        const unsigned long v = std::strtoul(pair.c_str(), &end, 16);
        if (end == nullptr || *end != '\0') {
            return std::nullopt;
        }
        parts[i] = static_cast<Uint8>(v);
    }
    return Rgb{parts[0], parts[1], parts[2]};
}

void Draw::begin_frame(double text_scale, bool readable, double line_spacing) {
    scale_ = std::max(0.5, text_scale);
    bold_ = readable;
    spacing_ = std::max(1.0, line_spacing);
    order_ = 0;
    fills_.clear();
    texts_.clear();
    record_ = pending_;
    pending_ = false;
    SDL_SetRenderScale(r_, 1.0f, 1.0f);
    SDL_SetRenderDrawBlendMode(r_, SDL_BLENDMODE_BLEND);
}

int Draw::chars_fit(double w, double mult) const {
    const double cw = char_w(mult);
    return cw > 0 ? static_cast<int>(std::floor((w + 0.5) / cw)) : 0;
}

double Draw::text_width(const std::string& s, double mult) const {
    return static_cast<double>(s.size()) * char_w(mult);
}

void Draw::clear(Rgb c) {
    SDL_SetRenderDrawColor(r_, c.r, c.g, c.b, 255);
    SDL_RenderClear(r_);
    fills_.push_back({0, 0, style::kBaseW, style::kBaseH, c, 1.0, true, order_++});
}

void Draw::fill(double x, double y, double w, double h, Rgb c, Uint8 alpha, bool ui) {
    SDL_SetRenderDrawColor(r_, c.r, c.g, c.b, alpha);
    const SDL_FRect rc = frect(x, y, w, h);
    SDL_RenderFillRect(r_, &rc);
    fills_.push_back({x, y, w, h, c, alpha / 255.0, ui, order_++});
}

void Draw::rect(double x, double y, double w, double h, Rgb c, double line) {
    SDL_SetRenderDrawColor(r_, c.r, c.g, c.b, 255);
    for (int i = 0; i < static_cast<int>(line); ++i) {
        const SDL_FRect rc = frect(x + i, y + i, w - 2 * i, h - 2 * i);
        SDL_RenderRect(r_, &rc);
    }
}

void Draw::panel(double x, double y, double w, double h) {
    fill(x, y, w, h, style::kPanel);
    rect(x, y, w, h, style::kPanelEdge);
}

void Draw::focus_box(double x, double y, double w, double h) {
    fill(x, y, w, h, style::kRowFocus);
    rect(x, y, w, h, style::kFocus, style::kFocusLine);
    // the ">" marker: focus is never colour alone
    glyphs(">", x + 3, y + (h - char_h()) / 2, 1.0, style::kAccent);
}

void Draw::bar(double x, double y, double w, double h, double fraction, Rgb c) {
    fill(x, y, w, h, style::kRow);
    fill(x, y, w * std::min(1.0, std::max(0.0, fraction)), h, c);
}

void Draw::circle(double cx, double cy, double r, Rgb c, double line) {
    constexpr int kSegments = 32;
    constexpr double kTau = 6.28318530717958647692;
    SDL_SetRenderDrawColor(r_, c.r, c.g, c.b, 255);
    for (int i = 0; i < static_cast<int>(line); ++i) {
        SDL_FPoint pts[kSegments + 1];
        for (int s = 0; s <= kSegments; ++s) {
            const double a = kTau * s / kSegments;
            pts[s] = SDL_FPoint{static_cast<float>(cx + (r - i) * std::cos(a)), static_cast<float>(cy + (r - i) * std::sin(a))};
        }
        SDL_RenderLines(r_, pts, kSegments + 1);
    }
}

bool save_frame(SDL_Renderer* renderer, const std::string& path) {
    // Read in output pixels: switch off the logical presentation for the read, then restore it
    int lw = 0;
    int lh = 0;
    SDL_RendererLogicalPresentation mode = SDL_LOGICAL_PRESENTATION_DISABLED;
    SDL_GetRenderLogicalPresentation(renderer, &lw, &lh, &mode);
    SDL_SetRenderLogicalPresentation(renderer, 0, 0, SDL_LOGICAL_PRESENTATION_DISABLED);
    SDL_Surface* surface = SDL_RenderReadPixels(renderer, nullptr);
    const bool ok = surface && SDL_SaveBMP(surface, path.c_str());
    SDL_SetRenderLogicalPresentation(renderer, lw, lh, mode);
    SDL_DestroySurface(surface);
    return ok;
}

void Draw::clip(double x, double y, double w, double h) {
    const SDL_Rect rc{static_cast<int>(x), static_cast<int>(y), static_cast<int>(w), static_cast<int>(h)};
    SDL_SetRenderClipRect(r_, &rc);
}

void Draw::unclip() {
    SDL_SetRenderClipRect(r_, nullptr);
}

void Draw::glyphs(const std::string& s, double x, double y, double mult, Rgb c) {
    const float k = static_cast<float>(scale_ * mult);
    SDL_SetRenderScale(r_, k, k);
    SDL_SetRenderDrawColor(r_, c.r, c.g, c.b, 255);
    SDL_RenderDebugText(r_, static_cast<float>(x) / k, static_cast<float>(y) / k, s.c_str());
    if (bold_) {   // the readable font: bold, one design pixel to the right
        SDL_RenderDebugText(r_, static_cast<float>(x + 1.0) / k, static_cast<float>(y) / k, s.c_str());
    }
    SDL_SetRenderScale(r_, 1.0f, 1.0f);
}

double Draw::text(const std::string& id, const std::string& s, double x, double y, double w, double h, TextOpts o) {
    const double cw = char_w(o.mult);
    const double ch = char_h(o.mult);
    const double lh = line_h(o.mult);
    const int fit = std::max(1, chars_fit(w, o.mult));
    std::vector<std::string> lines;
    bool fits = true;
    std::string why;
    if (o.wrap) {
        lines = core::wrap_chars(s, static_cast<std::size_t>(fit));
        const int max_lines = std::max(1, static_cast<int>(std::floor((h + 0.5) / lh)));
        if (static_cast<int>(lines.size()) > max_lines) {
            lines.resize(static_cast<std::size_t>(max_lines));
            fits = false;
            why = "more lines than the box holds";
        }
    } else {
        std::string one = s;
        if (static_cast<int>(one.size()) > fit) {
            one = one.substr(0, static_cast<std::size_t>(fit));
            fits = false;
            why = "wider than its box";
        }
        lines.push_back(one);
        if (ch > h + 0.5) {
            fits = false;
            why = "taller than its box";
        }
    }
    const double block_h = static_cast<double>(lines.size()) * lh;
    double ty = y + std::max(0.0, (h - block_h) / 2);   // vertically centred in the box
    double ink_x = x;
    double ink_w = 0;
    for (const std::string& line : lines) {
        const double tw = static_cast<double>(line.size()) * cw;
        double tx = x;
        if (o.align == Align::Center) {
            tx = x + (w - tw) / 2;
        } else if (o.align == Align::Right) {
            tx = x + w - tw;
        }
        if (ink_w == 0 || tx < ink_x) {
            ink_x = tx;
        }
        ink_w = std::max(ink_w, tw);
        if (o.outline) {
            for (const auto& [dx, dy] : {std::pair{-1.0, 0.0}, std::pair{1.0, 0.0}, std::pair{0.0, -1.0}, std::pair{0.0, 1.0}}) {
                glyphs(line, tx + dx, ty + (lh - ch) / 2 + dy, o.mult, style::kBlack);
            }
        }
        glyphs(line, tx, ty + (lh - ch) / 2, o.mult, o.color);
        ty += lh;
    }
    if (record_ && !s.empty() && !id.empty()) {   // an empty id: drawn, not part of the report
        TextRec rec;
        rec.id = id;
        rec.text = s.substr(0, 60);
        rec.px = ch;
        rec.fg = o.color;
        rec.outline = o.outline;
        rec.fits = fits;
        rec.raw = o.raw;
        rec.why = why;
        rec.ink[0] = ink_x;
        rec.ink[1] = y + std::max(0.0, (h - block_h) / 2);
        rec.ink[2] = ink_w;
        rec.ink[3] = block_h;
        rec.order = order_++;
        texts_.push_back(rec);
    }
    return block_h;
}

void Draw::request_access(const std::string& screen, bool world) {
    pending_ = true;
    screen_ = screen;
    world_ = world;
    report_.reset();
}

json Draw::text_json(const TextRec& t) const {
    const double cx = t.ink[0] + t.ink[2] / 2;
    const double cy = t.ink[1] + t.ink[3] / 2;
    json out = {{"node", t.id}, {"text", t.text}, {"state", ""}, {"px", t.px}, {"fg", hex_of(t.fg)},
                {"ink", json::array({t.ink[0], t.ink[1], t.ink[2], t.ink[3]})}, {"fits", t.fits}};
    if (!t.why.empty()) {
        out["why"] = t.why;
    }
    if (t.raw) {
        out["raw"] = true;   // not UI copy: the pseudo-locale check skips its "[" (Drive.cpp)
    }
    // the panel under the text: the last opaque UI fill drawn before it under its middle
    const Fill* card = nullptr;
    json layers = json::array();   // translucent UI fills over the game, top first
    for (const Fill& f : fills_) {
        if (!f.ui || f.order > t.order || !inside(cx, cy, f.x, f.y, f.w, f.h)) {
            continue;
        }
        if (f.alpha >= kOpaque) {
            card = &f;
            layers = json::array();
        } else {
            layers.insert(layers.begin(), json::array({hex_of(f.c), f.alpha}));
        }
    }
    if (t.outline) {
        out["outline"] = hex_of(style::kBlack);
    } else if (card && !(world_ && card->order == 0)) {   // over the game the clear colour is not a background
        out["bg"] = hex_of(card->c);
    } else if (!layers.empty()) {
        out["over_game"] = layers;
    }
    bool covered = false;
    for (const Fill& f : fills_) {
        if (f.ui && f.order > t.order && f.alpha >= kOpaque && inside(cx, cy, f.x, f.y, f.w, f.h)) {
            covered = true;
        }
    }
    out["covered"] = covered;
    out["card"] = card ? json{{"order", card->order}, {"rect", json::array({card->x, card->y, card->w, card->h})}}
                       : json::object();
    return out;
}

void Draw::end_frame() {
    if (!record_) {
        return;
    }
    json texts = json::array();
    for (const TextRec& t : texts_) {
        texts.push_back(text_json(t));
    }
    report_ = json{{"screen", screen_}, {"design", json::array({style::kBaseW, style::kBaseH})},
                   {"scaling", "letterbox"}, {"texts", texts}};
    record_ = false;
}

std::optional<json> Draw::take_access_report() {
    std::optional<json> out;
    out.swap(report_);
    return out;
}

}  // namespace shell

// {{FOOTER}}
