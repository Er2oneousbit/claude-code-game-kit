// ---------------------------------------------------------------------------
// Draw.hpp
// Purpose : The shell's drawing layer: text through SDL's built-in 8x8 font (SDL_RenderDebugText) scaled by the
//           player's text size, panels, focus boxes and bars in the 640x360 design space, and the record of every
//           text and fill of a frame that the accessibility sweep reads (tools/access/sweep.py).
// Usage   : shell::Draw draw(renderer); draw.begin_frame(text_scale, readable_font, line_spacing);
//           draw.panel(x, y, w, h); draw.text("menu.play", "Play", x, y, w, h, {shell::Align::Center});
//           draw.request_access("settings/audio", false);  ... after the frame: draw.access_report()
// Notes   : SDL's debug font is monospace, ASCII only and one size: it needs no font file or SDL3_ttf, which keeps
//           the starter small, and the readable-font setting (#167) makes it bold (drawn twice, one pixel apart)
//           since there is no second face to switch to. A game that ships text beyond ASCII, or wants a real
//           typeface (Atkinson Hyperlegible is the kit's readable font elsewhere), adds sdl3-ttf (docs/ENGINE.md).
//           Sizes are design pixels: the window scales them (main.cpp's letterbox presentation), so the sweep's
//           pixel rules are checked on design px times the window's scale. Focus is never colour alone: a focused
//           row gets an outline and a ">" marker.
//
// Pseudocode:
//   text(): fit = chars that fit the box -> cut the rest (fits = false) -> align -> outline? draw black at +-1
//           -> set render scale k = text_scale * mult -> SDL_RenderDebugText(x / k, y / k) (twice when bold)
//           -> record {id, text, px, fg, bg or outline or over_game, ink box, fits}
//   access_report(): the texts with the fill under each (the last opaque UI fill before it under its middle)
//     (the pseudo-locale drive reads the same report: fits, ink box, raw)
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): raw labels for the pseudo check, circle(), save_frame()
//           (#275)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace shell {

struct Rgb {
    Uint8 r = 0;
    Uint8 g = 0;
    Uint8 b = 0;
};

// ---- Style: the built-in look (a game restyles the shell here) ----
namespace style {
constexpr int kBaseW = 640;
constexpr int kBaseH = 360;
constexpr double kFontPx = 8.0;            // SDL's debug font at text_scale 1
constexpr double kTitleMult = 3.0;         // the game's name on the title screen
constexpr double kHeadingMult = 2.0;       // a screen's title
constexpr double kSubtitleMult[4] = {1.0, 1.25, 1.5, 2.0};   // small, medium, large, xl
constexpr double kRowPad = 4.0;            // px above and below a row's text
constexpr double kFocusLine = 2.0;
constexpr Uint8 kOverlayAlpha = 158;       // 62 %: the pause overlay
constexpr Rgb kBg{18, 20, 28};
constexpr Rgb kPanel{33, 38, 51};
constexpr Rgb kPanelEdge{77, 87, 107};
constexpr Rgb kRow{41, 46, 61};
constexpr Rgb kRowFocus{66, 77, 102};
constexpr Rgb kText{235, 237, 245};
constexpr Rgb kDim{158, 166, 184};
constexpr Rgb kAccent{250, 199, 82};       // amber: reads in every colour-blind mode
constexpr Rgb kFocus{255, 255, 255};
constexpr Rgb kWarn{255, 115, 89};
constexpr Rgb kBar{102, 179, 255};
constexpr Rgb kBlack{0, 0, 0};
}  // namespace style

enum class Align { Left, Center, Right };

struct TextOpts {
    Align align = Align::Left;
    double mult = 1.0;            // size: kFontPx * text_scale * mult
    Rgb color = style::kText;
    bool outline = false;         // black outline: text over the game
    bool wrap = false;            // word-wrap inside the box (else one line, cut when too long)
    bool raw = false;             // not UI copy (a key name, CREDITS.md, an arrow): the pseudo check skips its "["
};

std::string hex_of(Rgb c);
std::optional<Rgb> rgb_from_hex(const std::string& hex);   // "#rrggbb"

// Saves what the renderer drew this frame as a BMP (call before SDL_RenderPresent), in output pixels. SDL alone
// writes BMP; tools/art/frames_to_gif.py reads it. main.cpp (--screenshot, --record) and the F8 bug report use it.
bool save_frame(SDL_Renderer* renderer, const std::string& path);

class Draw {
public:
    explicit Draw(SDL_Renderer* renderer) : r_(renderer) {}

    void begin_frame(double text_scale, bool readable, double line_spacing);
    void end_frame();

    double text_scale() const { return scale_; }
    double char_w(double mult = 1.0) const { return style::kFontPx * scale_ * mult; }
    double char_h(double mult = 1.0) const { return style::kFontPx * scale_ * mult; }
    double line_h(double mult = 1.0) const { return char_h(mult) * spacing_; }
    double row_h(double mult = 1.0) const { return line_h(mult) + style::kRowPad * 2; }
    int chars_fit(double w, double mult = 1.0) const;
    double text_width(const std::string& s, double mult = 1.0) const;

    // Fills. ui = the shell's own panels and rows (the access report's backgrounds); false for game content.
    void clear(Rgb c);
    void fill(double x, double y, double w, double h, Rgb c, Uint8 alpha = 255, bool ui = true);
    void rect(double x, double y, double w, double h, Rgb c, double line = 1.0);
    void panel(double x, double y, double w, double h);
    void focus_box(double x, double y, double w, double h);
    void bar(double x, double y, double w, double h, double fraction, Rgb c = style::kBar);
    void circle(double cx, double cy, double r, Rgb c, double line = 1.0);   // an outline (the juice demo's rings)
    void clip(double x, double y, double w, double h);
    void unclip();

    // Text in a box. Returns the height drawn. Every text gets an id for the access report.
    double text(const std::string& id, const std::string& s, double x, double y, double w, double h,
                TextOpts opts = {});

    // The access sweep (#91): record the next frame; world = a screen over the game (its texts need a panel or
    // an outline). The report is ready after end_frame().
    void request_access(const std::string& screen, bool world);
    bool recording() const { return record_; }
    std::optional<nlohmann::json> take_access_report();

private:
    struct Fill {
        double x, y, w, h;
        Rgb c;
        double alpha;
        bool ui;
        int order;
    };
    struct TextRec {
        std::string id, text;
        double px;
        Rgb fg;
        bool outline;
        bool fits;
        bool raw;
        std::string why;
        double ink[4];
        int order;
    };

    SDL_Renderer* r_;
    double scale_ = 1.0;
    bool bold_ = false;
    double spacing_ = 1.0;
    int order_ = 0;
    bool record_ = false;
    bool pending_ = false;
    std::string screen_;
    bool world_ = false;
    std::vector<Fill> fills_;
    std::vector<TextRec> texts_;
    std::optional<nlohmann::json> report_;

    void glyphs(const std::string& s, double x, double y, double mult, Rgb c);
    nlohmann::json text_json(const TextRec& t) const;
};

}  // namespace shell

// {{FOOTER}}
