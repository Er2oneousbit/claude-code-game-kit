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
// Notes   : Only the top screen updates and gets input; the pause menu draws over the frozen play screen. Actions
//           go to the top screen in sorted order until one is used, so Escape (ui_cancel and pause) backs out of
//           a menu but pauses the game. Automated runs (dev.py smoke) never change the window mode, never pause
//           on focus loss and never speak; the drive scripts press the same actions a player would. Text is SDL's
//           built-in 8x8 font (shell/Draw.hpp): ASCII only, so the shell ships English only; a translation with
//           accents needs sdl3-ttf (docs/ENGINE.md).
//
// Pseudocode:
//   event -> binding string (core::key_binding / pad_binding) -> capturing? rebind : actions_for(bindings)
//     -> a held subtitle line takes ui_accept first -> top screen's action handler
//   update: drive step -> top screen -> subtitle track (subtitle_hold) -> narration -> captions
//   render: Draw frame (text scale, readable font, line spacing) -> screens from the last opaque one up
//     -> subtitles and captions -> (access sweep) the frame's text report
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include <SDL3/SDL.h>

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

#include "core/I18n.hpp"
#include "core/Menu.hpp"
#include "core/ShellLogic.hpp"
#include "shell/Draw.hpp"

namespace shell {

class Drive;

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
};

enum class ScreenId { Title, MainMenu, Settings, Credits, Loading, Play, Pause, Help, History };

const char* screen_name(ScreenId id);   // "title", "main_menu", "settings", ...

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
    bool is_down(const std::string& action) const;    // a bound key or button of the action is held
    Rgb palette(const std::string& name, Rgb fallback) const;   // data/access/colours.json for the colour-blind mode
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
    bool asked_consent_ = false;
    bool consent_answered_ = false;
    int dispatch_depth_ = 0;              // inside a screen's action handler: stack changes wait
    std::vector<StackOp> pending_ops_;

    std::string last_device_ = "keyboard";
    std::set<std::string> held_;          // bindings held right now
    std::map<std::string, bool> stick_dirs_;
    std::map<std::string, bool> triggers_;
    std::vector<SDL_Gamepad*> gamepads_;

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
    void draw_credits(const Screen& s);
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

    // narration
    void narrate_update();
    void speak(const std::string& line);
    std::string describe(const core::Row& row) const;
    void speech_worker();
};

}  // namespace shell
