// ---------------------------------------------------------------------------
// Shell.hpp
// Purpose : The runtime shell around the game: the screen stack (title, main menu, settings, credits, loading, play,
//           pause, "What now?", dialogue history), input routing from SDL keys and gamepads to the shell's actions
//           through the player's bindings, the settings applied at runtime, the user-data folder (settings.json),
//           string tables, subtitles and captions, menu narration (#165) and the scripted smoke scenarios
//           (shell/Drive.hpp). The settings logic itself is src/core (Settings, Bindings, Menu, ShellLogic).
// Usage   : shell::Shell shell(options); shell.play = {...the game's play screen...}; shell.init(window, renderer);
//           then shell.handle_event(e), shell.update(dt), shell.render(renderer); shell.quit_requested()
//           the game: shell.settings()["access"]["game_speed"], shell.say_line("guide.welcome"),
//           shell.set_objective(shell.t("play.objective")), shell.is_down("attack"), shell.palette("player")
//           analog (#274): shell.stick() (deadzone, invert_y), shell.right_trigger() (0..1), shell.held_actions(),
//           shell.move_vector() (held move_* plus the stick, length <= 1)
// Notes   : Only the top screen updates and gets input; the pause menu draws over the frozen play screen. Actions
//           go to the top screen in sorted order until one is used, so Escape (ui_cancel and pause) backs out of
//           a menu but pauses the game. Automated runs (dev.py smoke) never change the window mode, never pause
//           on focus loss and never speak; the drive scripts press the same actions a player would, and the real
//           keyboard, mouse and pads are not read (#276: handle_event drops them, the stick and triggers rest).
//           Text is SDL's built-in 8x8 font (shell/Draw.hpp): ASCII only, so the shell ships English only; a
//           translation with accents needs sdl3-ttf (docs/ENGINE.md). The pseudo locale (#275) is the ASCII form for that reason:
//           bracketed and 40 % longer, no accents.
//           The left stick works two ways: as d-pad presses with hysteresis for the menus (the pad:dpad_* bindings),
//           and as an analog vector for the game (stick(), held_actions()); triggers likewise press pad:l2 / pad:r2
//           past half travel and give 0..1 through left_trigger() / right_trigger(). Axes follow SDL: +y is down.
//           Debug builds (no NDEBUG) add the juice demo to the main menu, the pseudo locale to the language list
//           and F8, the bug report: bug_<time>/ in the user-data folder (screenshot.bmp, log_tail.txt,
//           settings.json, info.txt), printed as BUG_REPORT <folder>. The shell also keeps the crash context
//           (core/Report.hpp) current, so main.cpp's crash file names the screen, locale and settings.
//
// Pseudocode:
//   event -> binding string (core::key_binding / pad_binding) -> capturing? rebind : actions_for(bindings)
//     -> a held subtitle line takes ui_accept first -> top screen's action handler
//   update: poll the pads' axes -> drive step -> top screen -> subtitle track (subtitle_hold) -> narration
//     -> captions, notice
//   render: Draw frame (text scale, readable font, line spacing) -> screens from the last opaque one up
//     -> subtitles and captions -> notice -> (access sweep) the frame's text report -> (F8) the bug report
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): analog stick and triggers for the game (#274); crash
//           context, F8 bug report, pseudo locale, juice demo screen (#275); data/ found next to the exe when the
//           working directory has none (game_dir())
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): credits_at_top for show:credits (#284)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the Display tab's Apply and keep-or-revert confirm,
//           counted in real time (#308); hud_scale() and play.hud_scale_changed for a game HUD (#309)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

#include <chrono>
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

#include "core/Analog.hpp"
#include "core/HudScale.hpp"
#include "core/I18n.hpp"
#include "core/Menu.hpp"
#include "core/Report.hpp"
#include "core/ShellLogic.hpp"
#include "shell/Draw.hpp"

namespace shell {

class Drive;
class JuiceDemo;

// Debug builds get the juice demo, the pseudo locale in the language list and the F8 bug report.
#ifdef NDEBUG
constexpr bool kDebugBuild = false;
#else
constexpr bool kDebugBuild = true;
#endif

struct RunOptions {
    bool automated = false;      // a smoke run: scripted input, no window changes, no speech
    std::string drive;           // the scenario (automated runs; "" = walk into the game)
    std::string data_dir;        // settings.json lives here ("" = SDL's preferences folder)
    std::string locale;          // beats settings.language for this run ("" = the setting)
    std::string game_name;
    std::string game_slug;
    std::string version;
};

// The play screen is the game's: src/game/Game.cpp fills these in. The shell handles pause itself.
struct PlayHooks {
    std::function<void()> enter;
    std::function<void(double dt)> update;
    std::function<void(Draw& draw)> draw;
    std::function<bool(const std::string& action)> action;   // true when the game used the action
    // The player's HUD text factor (ui_scale * text_scale, core/HudScale.hpp) changed, and once at the start (#309)
    std::function<void(double scale)> hud_scale_changed;
};

enum class ScreenId { Title, MainMenu, Settings, Credits, Loading, Play, Pause, Help, History, Juice };

const char* screen_name(ScreenId id);   // "title", "main_menu", "settings", ..., "juice_demo"

struct Screen {
    ScreenId id = ScreenId::Title;
    bool transparent = false;            // draws over the screen below (pause)
    core::MenuList list;                 // main menu, pause
    std::optional<core::MenuList> consent;   // the title's telemetry question
    double t = 0.0;
    int frames = 0;
    int steps_done = 0;                  // loading
    ScreenId next = ScreenId::Play;      // loading: what comes after
    double offset = 0.0;                 // credits, help, history: scroll
    std::optional<std::vector<std::string>> credits;   // CREDITS.md lines (nullopt: the placeholder)
};

class Shell {
public:
    explicit Shell(RunOptions options);
    ~Shell();
    Shell(const Shell&) = delete;
    Shell& operator=(const Shell&) = delete;

    PlayHooks play;

    // Loads data and settings, opens the first screen. False on a problem that stops the game (logged).
    bool init(SDL_Window* window, SDL_Renderer* renderer);
    void handle_event(const SDL_Event& event);
    void update(double dt);
    void render(SDL_Renderer* renderer);
    bool quit_requested() const { return quit_; }

    // ---- for the game ----
    nlohmann::json& settings() { return settings_; }
    const nlohmann::json& settings() const { return settings_; }
    std::string t(const std::string& key, const core::TrArgs& args = {}) const;
    bool access_flag(const char* key) const;          // settings.access.<key> as a bool
    double access_number(const char* key, double fallback) const;
    double game_speed() const { return access_number("game_speed", 1.0); }
    double timing_scale() const { return access_number("timing_scale", 1.0); }
    double hud_scale() const;                         // ui_scale * text_scale: what a HUD multiplies text by (#309)
    bool is_down(const std::string& action) const;    // a bound key or button of the action is held (or the stick: move_*)
    // analog input (#274), zero without a pad; core::analog::Vec2 is the kit's own (core/Analog.hpp)
    core::analog::Vec2 stick() const;                 // the left stick: deadzone (radial, rescaled), invert_y; +y down
    double left_trigger() const;                      // 0 at rest .. 1 fully in
    double right_trigger() const;
    std::set<std::string> held_actions() const;       // game actions held now (no ui_*), the stick's move_* included
    core::analog::Vec2 move_vector() const;           // the held move_* actions plus the stick, length 0..1
    void set_run_seed(const std::string& seed) { seed_ = seed; }   // named in crash files and bug reports
    void notice(const std::string& text);             // a short message over any screen ("Bug report saved.")
    Rgb palette(const std::string& name, Rgb fallback) const;   // data/access/colours.json for the colour-blind mode
    // The folder holding data/ and CREDITS.md: "" (the working directory) when it has data/i18n, as for dev.py run
    // and smoke, else the exe's folder, where the build copies them (a shipped game started from anywhere). Join
    // the game's own files to it the same way: shell.game_dir() / "assets/spr_player.png".
    const std::filesystem::path& game_dir() const { return game_dir_; }
    bool say_line(const std::string& id);             // a dialogue line as a subtitle (settings permitting)
    bool caption(const std::string& event_id);        // a sound caption ("[thud]") with captions_sfx on
    void set_objective(const std::string& text) { objective_ = text; }
    std::pair<std::string, std::string> prompt(const std::string& action) const;   // glyph name, label
    void push(ScreenId id);
    void pop();
    void replace(ScreenId id);
    void reset(ScreenId id);
    const Screen* top() const { return stack_.empty() ? nullptr : &stack_.back(); }
    Screen* top() { return stack_.empty() ? nullptr : &stack_.back(); }

private:
    friend class Drive;

    struct Capture {
        std::string action;
        std::size_t slot;
    };
    struct Caption {
        std::string text;
        double t;
    };
    struct StackOp {
        enum Kind { Push, Pop, Replace, Reset } kind;
        ScreenId id;
    };

    RunOptions opts_;
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    std::unique_ptr<Draw> draw_;
    std::unique_ptr<Drive> drive_;
    bool quit_ = false;
    double time_ = 0.0;

    std::filesystem::path data_dir_;
    std::filesystem::path game_dir_;      // where data/ and CREDITS.md are read from (game_dir())
    nlohmann::json settings_;
    bool settings_existed_ = false;
    core::StringTables tables_;
    std::string locale_ = core::kFallbackLocale;
    nlohmann::json presets_;
    nlohmann::json colours_;
    nlohmann::json dialogue_;
    std::vector<core::SubtitleLine> lines_;

    std::vector<Screen> stack_;
    std::unique_ptr<core::SettingsMenu> settings_menu_;
    std::optional<Capture> capturing_;
    std::string message_;                 // the settings hint line's message
    double message_t_ = 0.0;
    std::optional<std::chrono::steady_clock::time_point> real_last_;   // the display confirm counts real time (#308)
    core::HudScaleWatch hud_watch_;       // play.hud_scale_changed (#309)
    bool asked_consent_ = false;
    bool consent_answered_ = false;
    int dispatch_depth_ = 0;              // inside a screen's action handler: stack changes wait
    std::vector<StackOp> pending_ops_;

    std::string last_device_ = "keyboard";
    std::set<std::string> held_;          // bindings held right now (keys, buttons, triggers past half travel)
    std::map<std::string, bool> stick_dirs_;   // the stick as d-pad presses for the menus (not in held_)
    std::map<std::string, bool> triggers_;
    std::vector<SDL_Gamepad*> gamepads_;
    struct PadAxes {
        double lx = 0, ly = 0;            // the left stick, -1..1, +y down (SDL)
        double lt = 0, rt = 0;            // the triggers, 0..1
    };
    PadAxes pad_;                         // raw, polled every update: the furthest stick, the deepest triggers
    std::optional<PadAxes> pad_override_; // drives and tests set the pad's axes here

    // debug builds and reports (#275)
    std::unique_ptr<JuiceDemo> juice_;
    ScreenId loading_next_ = ScreenId::Play;   // what the next loading screen opens
    std::string seed_;
    std::string notice_;
    double notice_t_ = 0.0;
    bool bug_requested_ = false;          // F8: the report is written once the frame is drawn
    std::string last_bug_report_;
    bool plant_ = false;                  // drive pseudo-plant: one label too small for its text on the main menu

    core::SubtitleTrack track_;
    core::LineHistory history_;
    std::string objective_;
    std::map<std::string, Caption> captions_;

    // narration (#165)
    const Screen* narrated_top_ = nullptr;
    std::string last_narration_;
    std::thread speech_thread_;
    std::mutex speech_mutex_;
    std::condition_variable speech_cv_;
    std::deque<std::string> speech_queue_;
    bool speech_stop_ = false;

    // setup
    void load_tables();
    void load_dialogue();
    nlohmann::json load_json(const std::filesystem::path& file, const char* what);
    void apply_settings();
    void apply_display();
    std::filesystem::path settings_file() const { return data_dir_ / "settings.json"; }
    bool save_settings();
    core::Bindings bindings() const;
    bool has_text(const std::string& key) const;
    std::string binding_label(const std::string& glyph_name) const;
    std::string glyph_set() const;
    std::string pad_set() const;
    std::vector<std::string> locales() const;

    // input
    void key_event(const SDL_KeyboardEvent& e, bool down);
    void key_down(const std::string& binding, bool repeat);   // a key went down (drives press keys through it)
    void poll_pads();
    double input_number(const char* key, double fallback) const;   // settings.input.<key>
    bool input_flag(const char* key) const;
    std::vector<std::string> stick_actions() const;
    core::report::RunInfo run_info() const;
    void write_bug_report();
    std::string line_text(const core::SubtitleLine& line) const;   // through the string table, pseudo-aware
    void pad_button_event(const SDL_GamepadButtonEvent& e, bool down);
    void pad_axis_event(const SDL_GamepadAxisEvent& e);
    void binding_pressed(const std::string& binding, bool repeat);
    bool dispatch(const std::string& action);
    bool inject(const std::string& action) { return dispatch(action); }
    void simulate(const std::string& binding, const std::string& device);
    void begin_capture(const std::string& action, std::size_t slot);
    void finish_capture(const std::optional<std::string>& binding);
    bool screen_action(Screen& s, const std::string& action);
    void open_main_menu();
    void quit();
    void finish(const std::string& marker, int code);
    void say(const std::string& text);    // the settings hint message
    std::string focus_id() const;

    // screens
    Screen make_screen(ScreenId id);
    void flush_stack_ops();
    void update_screen(Screen& s, double dt);
    void draw_screen(Screen& s);
    void draw_title(Screen& s);
    void draw_main_menu(Screen& s);
    void draw_settings();
    void draw_display_confirm(core::SettingsMenu& menu);   // "Keep these display settings?" (#308)
    void draw_credits(Screen& s);
    void credits_at_top();                // show:credits: the first lines in view (they roll up from below)
    void draw_loading(const Screen& s);
    void draw_play();
    void draw_pause(Screen& s);
    void draw_text_page(Screen& s, const std::string& title_key, const std::vector<std::string>& lines,
                        const std::string& prefix);
    std::vector<std::string> help_page_lines() const;
    std::vector<std::string> history_page_lines() const;
    double draw_list(core::MenuList& list, double x, double y, double w, double label_w, double max_h,
                     const std::string& prefix, bool center);
    void draw_value(const core::Row& row, double x, double y, double w, double h, bool focused,
                    const std::string& lid);
    void draw_subtitles();
    void draw_notice();
    void draw_hint(const std::string& id, const std::string& action, const std::string& hint_key, double x, double y,
                   double w, TextOpts o);

    // narration
    void narrate_update();
    void speak(const std::string& line);
    std::string describe(const core::Row& row) const;
    void speech_worker();
};

}  // namespace shell

// {{FOOTER}}
