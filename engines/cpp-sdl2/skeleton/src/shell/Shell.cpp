// ---------------------------------------------------------------------------
// Shell.cpp
// Purpose : Implementation of the shell (see Shell.hpp): setup, input, the screens and their drawing, subtitles,
//           narration.
// Usage   : compiled into game_lib; the game drives it through Shell.hpp.
// Notes   : Layout numbers are design pixels (640x360) and tunables at the top. Every visible string goes through
//           t(), so a translation (data/i18n/<locale>.json) changes it; text that is not UI copy (key names,
//           CREDITS.md, arrows) is drawn raw, which the pseudo-locale check skips. The settings menu
//           (core::SettingsMenu) is built when the settings screen opens and dropped when it closes.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): analog input (#274); crash context, F8 bug report,
//           pseudo locale, juice demo (#275); data/ and CREDITS.md from game_dir() (next to the exe when the working
//           directory has no data/, so a shipped build runs from any folder)
//           2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): no real keyboard, mouse or pad in a drive (#276)
// ---------------------------------------------------------------------------
#include "shell/Shell.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <iterator>
#include <system_error>

#include "core/AtomicFile.hpp"
#include "core/Bindings.hpp"
#include "core/Log.hpp"
#include "core/Settings.hpp"
#include "shell/Drive.hpp"
#include "shell/JuiceDemo.hpp"

namespace shell {

using nlohmann::json;
namespace fs = std::filesystem;

namespace {

// ---- Tunables ----
const char* kI18nDir = "data/i18n";
const char* kPresetsFile = "data/input/presets.json";
const char* kColoursFile = "data/access/colours.json";
const char* kDialogueDir = "data/dialogue";
const char* kCreditsFile = "CREDITS.md";
constexpr double kMessageS = 3.0;             // a settings message stays this long
constexpr double kBlinkS = 0.6;               // the title prompt
constexpr int kLoadingSteps = 4;              // placeholder steps so the bar visibly moves
constexpr double kLoadingMinS = 0.6;
constexpr int kLoadingMinFrames = 6;          // automated runs
constexpr double kMenuW = 240;
constexpr double kPauseW = 280, kPauseH = 180;
constexpr double kListPad = 40, kRowInset = 24;
constexpr double kContentX = 44, kContentW = 552, kLabelW = 290;
constexpr double kAreaX = 60, kAreaY = 56, kAreaW = 520, kAreaH = 260;   // credits and text pages
constexpr double kScrollPxS = 18, kStepPx = 24;
constexpr double kSubtitleW = 520, kSubtitleBottom = 14, kSubtitlePad = 6;
constexpr double kCaptionMinS = 1.0;
constexpr double kStickOn = 0.5, kStickOff = 0.3;   // the left stick as a d-pad (hysteresis)
constexpr double kTriggerOn = 0.5, kTriggerOff = 0.3;
constexpr double kArrowW = 12;
constexpr double kSliderTextChars = 6;        // "100%" and the like
constexpr double kCellGap = 8;
const char* kAnyKeyExcept[] = {"key:escape", "pad:east"};   // these do not count as "press any key"
const char* kControlActions[] = {"move_left", "move_right", "jump", "attack", "interact", "pause"};
const char* kScreenTitleKeys[] = {"", "", "settings.title", "credits.title", "loading.title", "", "pause.title",
                                  "help.title", "history.title", "juice.title"};   // by ScreenId, for the narration
const char* kBugKey = "key:f8";               // the bug report (debug builds)
constexpr double kNoticeS = 3.0;              // a notice ("Bug report saved.") stays this long
const char* kMoveActions[] = {"move_left", "move_right", "move_up", "move_down"};

// settings.json's text for a report: never throws (a crash file must not fail on a broken string)
std::string settings_text(const json& settings) {
    return settings.dump(2, ' ', false, json::error_handler_t::replace);
}

std::string speech_command(const std::string& text) {
#ifdef _WIN32
    std::string quoted;
    for (const char c : text) {
        if (c == '\'') quoted += "''";
        else if (c != '"') quoted += c;
    }
    return "powershell -NoProfile -Command \"Add-Type -AssemblyName System.Speech; "
           "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('" + quoted + "')\"";
#else
    std::string quoted = "'";
    for (const char c : text) {
        if (c == '\'') quoted += "'\\''";
        else quoted += c;
    }
    quoted += "'";
#ifdef __APPLE__
    return "say " + quoted;
#else
    return "spd-say " + quoted;
#endif
#endif
}

// Where data/ and CREDITS.md are: the working directory when it has data/i18n (dev.py run and smoke start the game
// from the project root, so an edit to data/ shows without a rebuild), else the exe's folder, where the build copies
// them (cmake/copy_game_data.cmake), so a shipped game started from another folder still finds its strings.
// Neither: the working directory, and load_tables() warns.
fs::path find_game_dir() {
    std::error_code ec;
    if (fs::is_directory(core::path_from_utf8(kI18nDir), ec)) {
        return fs::path();
    }
    const char* base = SDL_GetBasePath();   // owned by SDL; nullptr when the platform cannot say
    if (base) {
        const fs::path exe_dir = core::path_from_utf8(base);
        if (fs::is_directory(exe_dir / core::path_from_utf8(kI18nDir), ec)) {
            return exe_dir;
        }
    }
    return fs::path();
}

}  // namespace

const char* screen_name(ScreenId id) {
    switch (id) {
        case ScreenId::Title: return "title";
        case ScreenId::MainMenu: return "main_menu";
        case ScreenId::Settings: return "settings";
        case ScreenId::Credits: return "credits";
        case ScreenId::Loading: return "loading";
        case ScreenId::Play: return "play";
        case ScreenId::Pause: return "pause";
        case ScreenId::Help: return "help";
        case ScreenId::History: return "history";
        case ScreenId::Juice: return "juice_demo";
    }
    return "?";
}

Shell::Shell(RunOptions options) : opts_(std::move(options)) {}

Shell::~Shell() {
    core::report::clear_crash_callbacks();   // a crash after this point must not call into a shell that is gone
    {
        std::lock_guard<std::mutex> lock(speech_mutex_);
        speech_stop_ = true;
    }
    speech_cv_.notify_all();
    if (speech_thread_.joinable()) {
        speech_thread_.join();
    }
    for (SDL_Gamepad* pad : gamepads_) {
        SDL_CloseGamepad(pad);
    }
}

// ---- Setup ---------------------------------------------------------------------------------------------------
json Shell::load_json(const fs::path& file, const char* what) {
    std::string error;
    const std::optional<std::string> text = core::read_file(file, &error);
    if (!text) {
        if (!error.empty()) {
            LOG_WARN("shell", what << ": " << core::path_to_utf8(file) << " cannot be read: " << error);
        }
        return json();
    }
    json data = json::parse(*text, nullptr, false);
    if (data.is_discarded()) {
        LOG_WARN("shell", what << ": " << core::path_to_utf8(file) << " is not valid JSON");
        return json();
    }
    return data;
}

void Shell::load_tables() {
    json all = json::object();
    std::error_code ec;
    const fs::path dir = game_dir_ / core::path_from_utf8(kI18nDir);
    for (const auto& entry : fs::directory_iterator(dir, ec)) {
        if (!entry.is_regular_file() || entry.path().extension() != ".json") {
            continue;
        }
        const json table = load_json(entry.path(), "i18n");
        if (table.is_object()) {
            all[core::path_to_utf8(entry.path().stem())] = table;
        }
    }
    tables_ = core::string_tables_from_json(all);
    if (tables_.empty()) {
        LOG_WARN("shell", "no string tables in " << core::path_to_utf8(dir) << ": labels show their keys");
        return;
    }
    std::string names;
    for (const auto& table : tables_) {
        names += (names.empty() ? "" : ", ") + table.first;
    }
    LOG_INFO("shell", "string tables " << names << " from " << core::path_to_utf8(fs::absolute(dir, ec)));
}

void Shell::load_dialogue() {
    std::error_code ec;
    std::vector<fs::path> files;
    for (const auto& entry : fs::directory_iterator(game_dir_ / core::path_from_utf8(kDialogueDir), ec)) {
        if (entry.is_regular_file() && core::path_to_utf8(entry.path().filename()).find(".built.json") != std::string::npos) {
            files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());
    if (files.empty()) {
        return;
    }
    dialogue_ = load_json(files.front(), "dialogue");
    lines_ = core::subtitle_lines_from_json(dialogue_);
}

bool Shell::init(SDL_Window* window, SDL_Renderer* renderer) {
    window_ = window;
    renderer_ = renderer;
    draw_ = std::make_unique<Draw>(renderer);
    if (!opts_.data_dir.empty()) {
        data_dir_ = core::path_from_utf8(opts_.data_dir);
    } else {
        char* pref = SDL_GetPrefPath("", opts_.game_slug.c_str());
        if (!pref) {
            LOG_ERROR("shell", "no preferences folder: " << SDL_GetError());
            return false;
        }
        data_dir_ = core::path_from_utf8(pref);
        SDL_free(pref);
    }
    std::error_code ec;
    fs::create_directories(data_dir_, ec);
    const core::SettingsLoad loaded = core::settings_load_file(settings_file());
    settings_ = loaded.settings;
    settings_existed_ = fs::exists(settings_file(), ec);
    for (const std::string& p : loaded.problems) {
        LOG_WARN("settings", "fixed " << p);
    }
    // crash files from here on land in the data folder and name the screen, locale and settings (#275)
    core::report::CrashContext crash;
    crash.data_dir = data_dir_;
    crash.base = run_info();
    crash.info = [this] { return run_info(); };
    crash.settings = [this] { return settings_text(settings_); };
    core::report::set_crash_context(std::move(crash));
    game_dir_ = find_game_dir();
    load_tables();
    presets_ = load_json(game_dir_ / core::path_from_utf8(kPresetsFile), "presets");
    colours_ = load_json(game_dir_ / core::path_from_utf8(kColoursFile), "colours");
    load_dialogue();
    apply_settings();
    if (settings_existed_) {
        apply_display();
    }
    LOG_INFO("shell", "data folder " << core::path_to_utf8(data_dir_) << ", locale " << locale_
                                     << (opts_.automated ? ", automated" : ""));
    if (opts_.automated) {
        drive_ = std::make_unique<Drive>(*this, opts_.drive.empty() ? "default" : opts_.drive);
    }
    push(ScreenId::Title);
    return true;
}

void Shell::apply_settings() {
    const json& lang = settings_["language"];
    locale_ = !opts_.locale.empty() ? opts_.locale : (lang.is_string() ? lang.get<std::string>() : core::kFallbackLocale);
}

// Window mode, size and vsync. Never in automated runs (the smoke window must stay as it is).
void Shell::apply_display() {
    if (opts_.automated || !window_) {
        return;
    }
    const json& d = settings_["display"];
    const std::string mode = d["mode"].is_string() ? d["mode"].get<std::string>() : "windowed";
    if (mode == "windowed") {
        SDL_SetWindowFullscreen(window_, false);
        if (d["resolution"].is_array() && d["resolution"].size() == 2) {
            SDL_SetWindowSize(window_, d["resolution"][0].get<int>(), d["resolution"][1].get<int>());
        }
    } else {
        SDL_SetWindowFullscreen(window_, true);   // SDL3: borderless desktop fullscreen unless a mode is set
    }
    if (renderer_) {
        SDL_SetRenderVSync(renderer_, d["vsync"].is_boolean() && d["vsync"].get<bool>() ? 1 : 0);
    }
}

bool Shell::save_settings() {
    std::string error;
    if (!core::settings_save_file(settings_file(), settings_, &error)) {
        LOG_ERROR("settings", "not saved: " << error);
        return false;
    }
    LOG_INFO("settings", "saved " << core::path_to_utf8(settings_file()));
    return true;
}

core::Bindings Shell::bindings() const {
    return core::bindings_from_json(settings_["input"]["bindings"]);
}

// ---- Text ----------------------------------------------------------------------------------------------------
std::string Shell::t(const std::string& key, const core::TrArgs& args) const {
    if (locale_ == core::kPseudoLocale) {
        return core::tr_pseudo(tables_, key, args);   // the ASCII pseudo form: the 8x8 font has no accents
    }
    return core::tr(tables_, locale_, key, args);
}

// A dialogue line's text: dialogue.<id> from the string table when it has one, else the file's own text (pseudo-ised
// in the pseudo locale, so the layout check sees it as translated content)
std::string Shell::line_text(const core::SubtitleLine& line) const {
    const std::string key = "dialogue." + line.id;
    if (has_text(key)) {
        return t(key);
    }
    return locale_ == core::kPseudoLocale ? core::pseudo_ascii(line.text) : line.text;
}

core::report::RunInfo Shell::run_info() const {
    core::report::RunInfo info;
    info.game = opts_.game_name;
    info.version = opts_.version;
    info.build = kDebugBuild ? "debug" : "release";
    info.os = SDL_GetPlatform();
    info.screen = top() ? screen_name(top()->id) : "";
    info.locale = locale_;
    info.seed = seed_;
    return info;
}

void Shell::notice(const std::string& text) {
    notice_ = text;
    notice_t_ = kNoticeS;
}

bool Shell::has_text(const std::string& key) const {
    for (const std::string& loc : core::locale_chain(locale_)) {
        const auto table = tables_.find(loc);
        if (table != tables_.end() && table->second.count(key)) {
            return true;
        }
    }
    return false;
}

std::vector<std::string> Shell::locales() const {
    std::vector<std::string> out;
    for (const auto& [loc, table] : tables_) {
        out.push_back(loc);
    }
    if (out.empty()) {
        out.emplace_back(core::kFallbackLocale);
    }
    return out;
}

std::string Shell::binding_label(const std::string& glyph_name) const {
    if (has_text("glyph." + glyph_name)) {
        return t("glyph." + glyph_name);
    }
    return core::glyph_fallback_label(glyph_name);
}

std::string Shell::glyph_set() const {
    const json& g = settings_["input"]["glyphs"];
    return core::glyph_set(g.is_string() ? g.get<std::string>() : "auto", last_device_);
}

std::string Shell::pad_set() const {
    const std::string gset = glyph_set();
    return gset == "keyboard" ? "generic" : gset;
}

std::pair<std::string, std::string> Shell::prompt(const std::string& action) const {
    const std::string gset = glyph_set();
    const std::string binding = core::prompt_binding(bindings(), action, gset);
    if (binding.empty()) {
        return {"unknown", t("controls.unbound")};
    }
    const std::string gname = core::glyph_name(gset, binding);
    return {gname, binding_label(gname)};
}

bool Shell::access_flag(const char* key) const {
    const json& v = settings_["access"][key];
    return v.is_boolean() && v.get<bool>();
}

double Shell::access_number(const char* key, double fallback) const {
    const json& v = settings_["access"][key];
    return v.is_number() ? v.get<double>() : fallback;
}

Rgb Shell::palette(const std::string& name, Rgb fallback) const {
    const json& mode = settings_["access"]["colorblind"];
    const auto hex = core::palette_colour(colours_, mode.is_string() ? mode.get<std::string>() : "none", name);
    if (hex) {
        if (const auto rgb = rgb_from_hex(*hex)) {
            return *rgb;
        }
    }
    return fallback;
}

bool Shell::say_line(const std::string& id) {
    const core::SubtitleLine* line = core::find_line(lines_, id);
    if (!line) {
        LOG_WARN("dialogue", "no line " << id << " in " << kDialogueDir);
        return false;
    }
    if (!core::subtitle_allowed(*line, settings_) || !track_.play(*line, time_)) {
        return false;
    }
    history_.record(line->name, line_text(*line));   // for "What now?" and the history page (#167)
    return true;
}

bool Shell::caption(const std::string& event_id) {
    if (!access_flag("captions_sfx") || !dialogue_.is_object() || !dialogue_.contains("captions") ||
        !dialogue_["captions"].is_object() || !dialogue_["captions"].contains(event_id)) {
        return false;
    }
    const json& c = dialogue_["captions"][event_id];
    const std::string key = "caption." + event_id;
    std::string text = has_text(key) ? t(key) : (c.contains("text") && c["text"].is_string() ? c["text"].get<std::string>() : "");
    if (!has_text(key) && locale_ == core::kPseudoLocale) {
        text = core::pseudo_ascii(text);
    }
    const double min_s = c.contains("min_s") && c["min_s"].is_number() ? c["min_s"].get<double>() : kCaptionMinS;
    captions_[event_id] = {text, std::max(min_s, kCaptionMinS)};
    return true;
}

void Shell::say(const std::string& text) {
    message_ = text;
    message_t_ = kMessageS;
}

// ---- Screens -------------------------------------------------------------------------------------------------
Screen Shell::make_screen(ScreenId id) {
    Screen s;
    s.id = id;
    auto label = [this](const char* key) { return [this, key] { return t(key); }; };
    switch (id) {
        case ScreenId::Title:
            if (!asked_consent_ && settings_["telemetry"]["consent"] == "unset") {
                asked_consent_ = true;
                auto answer = [this](const char* value) {
                    return [this, value] {
                        settings_["telemetry"]["consent"] = value;
                        if (std::string(value) != "unset") {
                            save_settings();
                        }
                        LOG_INFO("telemetry", "consent " << value);
                        consent_answered_ = true;   // the dialog goes after this callback returns (it owns it)
                    };
                };
                s.consent = core::MenuList({core::button_row("yes", label("consent.yes"), answer("yes")),
                                            core::button_row("no", label("consent.no"), answer("no")),
                                            core::button_row("later", label("consent.later"), answer("unset"))});
                s.consent->focus("later");
            }
            break;
        case ScreenId::MainMenu: {
            std::vector<core::Row> rows = {
                core::button_row("play", label("menu.play"), [this] { push(ScreenId::Loading); }),
                core::button_row("settings", label("menu.settings"), [this] { push(ScreenId::Settings); }),
                core::button_row("credits", label("menu.credits"), [this] { push(ScreenId::Credits); }),
            };
            if constexpr (kDebugBuild) {   // the juice demo (#275): debug builds only
                rows.push_back(core::button_row("juice", label("menu.juice"), [this] {
                    loading_next_ = ScreenId::Juice;
                    push(ScreenId::Loading);
                }));
            }
            rows.push_back(core::button_row("quit", label("menu.quit"), [this] { quit(); }));
            s.list = core::MenuList(std::move(rows));
            break;
        }
        case ScreenId::Settings: {
            core::SettingsHooks hooks;
            hooks.tr = [this](const std::string& key, const core::TrArgs& args) { return t(key, args); };
            hooks.changed = [this](const std::string& section) {
                apply_settings();
                if (section == "display") {
                    apply_display();
                }
            };
            hooks.capture = [this](const std::string& action, std::size_t slot) { begin_capture(action, slot); };
            hooks.say = [this](const std::string& text) { say(text); };
            hooks.locales = [this] { return locales(); };
            hooks.locale_name = [this](const std::string& loc) {
                const auto table = tables_.find(loc);
                if (table != tables_.end() && table->second.count("language.name")) {
                    return table->second.at("language.name");
                }
                return loc;
            };
            hooks.binding_label = [this](const std::string& binding, std::size_t slot) {
                if (binding.empty()) {
                    return t("controls.unbound");
                }
                return binding_label(core::glyph_name(slot == core::kKeyboardSlot ? "keyboard" : pad_set(), binding));
            };
            hooks.close = [this] {
                save_settings();
                pop();
            };
            hooks.presets = presets_;
            hooks.debug_build = kDebugBuild;   // the pseudo locale in the language list (its ASCII form, #275)
            settings_menu_ = std::make_unique<core::SettingsMenu>(settings_, std::move(hooks));
            break;
        }
        case ScreenId::Credits: {
            const std::optional<std::string> text = core::read_file(game_dir_ / core::path_from_utf8(kCreditsFile));
            if (text) {
                s.credits = core::credits_lines(*text);
            }
            break;
        }
        case ScreenId::Loading:
            s.next = loading_next_;
            loading_next_ = ScreenId::Play;
            break;
        case ScreenId::Play:
            if (play.enter) {
                play.enter();
            }
            break;
        case ScreenId::Juice:
            juice_ = std::make_unique<JuiceDemo>(*this);   // a fresh demo each visit
            juice_->enter();
            break;
        case ScreenId::Pause:
            s.transparent = true;
            s.list = core::MenuList({
                core::button_row("resume", label("pause.resume"), [this] { pop(); }),
                core::button_row("help", label("pause.help"), [this] { push(ScreenId::Help); }),          // #167
                core::button_row("history", label("pause.history"), [this] { push(ScreenId::History); }),
                core::button_row("settings", label("menu.settings"), [this] { push(ScreenId::Settings); }),
                core::button_row("quit", label("pause.quit"), [this] { reset(ScreenId::Title); }),
            });
            break;
        case ScreenId::Help:
            break;
        case ScreenId::History:
            s.offset = 1e9;   // clamped when drawn: open at the newest line
            break;
    }
    return s;
}

// A row's callback (Resume, Back, Quit to title) changes the stack that owns the row: inside dispatch() the change
// waits until the callback has returned, so no std::function is destroyed while it runs.
void Shell::push(ScreenId id) {
    if (dispatch_depth_ > 0) {
        pending_ops_.push_back({StackOp::Push, id});
        return;
    }
    stack_.push_back(make_screen(id));
    LOG_INFO("shell", "screen " << screen_name(id));
}

void Shell::pop() {
    if (dispatch_depth_ > 0) {
        pending_ops_.push_back({StackOp::Pop, ScreenId::Title});
        return;
    }
    if (stack_.empty()) {
        return;
    }
    if (stack_.back().id == ScreenId::Settings) {
        settings_menu_.reset();
        capturing_.reset();
    }
    if (stack_.back().id == ScreenId::Juice) {
        juice_.reset();
    }
    stack_.pop_back();
}

void Shell::replace(ScreenId id) {
    if (dispatch_depth_ > 0) {
        pending_ops_.push_back({StackOp::Replace, id});
        return;
    }
    pop();
    push(id);
}

void Shell::reset(ScreenId id) {
    if (dispatch_depth_ > 0) {
        pending_ops_.push_back({StackOp::Reset, id});
        return;
    }
    while (!stack_.empty()) {
        pop();
    }
    push(id);
}

void Shell::flush_stack_ops() {
    std::vector<StackOp> ops;
    ops.swap(pending_ops_);
    for (const StackOp& op : ops) {
        switch (op.kind) {
            case StackOp::Push: push(op.id); break;
            case StackOp::Pop: pop(); break;
            case StackOp::Replace: replace(op.id); break;
            case StackOp::Reset: reset(op.id); break;
        }
    }
}

void Shell::open_main_menu() {
    push(ScreenId::MainMenu);
}

void Shell::quit() {
    LOG_INFO("shell", "quit");
    if (drive_) {
        finish("DRIVE_DONE " + drive_->name(), drive_->exit_code());
    } else {
        quit_ = true;
    }
}

void Shell::finish(const std::string& marker, int code) {
    std::cout << marker << "\n" << std::flush;
    if (code != 0) {
        LOG_ERROR("drive", "scenario failed with exit code " << code);
    }
    quit_ = true;
}

std::string Shell::focus_id() const {
    const Screen* s = top();
    if (!s) {
        return "";
    }
    switch (s->id) {
        case ScreenId::Title: return s->consent ? "consent." + s->consent->focused_id() : "title";
        case ScreenId::Settings: return settings_menu_ ? settings_menu_->focus_id() : "";
        case ScreenId::MainMenu:
        case ScreenId::Pause: return s->list.focused_id();
        default: return "";
    }
}

// ---- Input ---------------------------------------------------------------------------------------------------
namespace {
// SDL's event types as the kinds core::admits_device_event knows
core::ShellDeviceEvent device_event_kind(Uint32 type) {
    switch (type) {
        case SDL_EVENT_KEY_DOWN:
        case SDL_EVENT_KEY_UP: return core::ShellDeviceEvent::Key;
        case SDL_EVENT_MOUSE_BUTTON_DOWN:
        case SDL_EVENT_MOUSE_BUTTON_UP: return core::ShellDeviceEvent::MouseButton;
        case SDL_EVENT_MOUSE_MOTION: return core::ShellDeviceEvent::MouseMotion;
        case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
        case SDL_EVENT_GAMEPAD_BUTTON_UP: return core::ShellDeviceEvent::PadButton;
        case SDL_EVENT_GAMEPAD_AXIS_MOTION: return core::ShellDeviceEvent::PadAxis;
        case SDL_EVENT_GAMEPAD_ADDED: return core::ShellDeviceEvent::PadAdded;
        case SDL_EVENT_GAMEPAD_REMOVED: return core::ShellDeviceEvent::PadRemoved;
        case SDL_EVENT_QUIT: return core::ShellDeviceEvent::Quit;
        case SDL_EVENT_WINDOW_FOCUS_LOST: return core::ShellDeviceEvent::FocusLost;
        default: return core::ShellDeviceEvent::Other;
    }
}
}  // namespace

void Shell::handle_event(const SDL_Event& event) {
    // #276: a smoke run follows a drive, which presses through key_down / press_binding itself; the real keyboard,
    // mouse and pads (a stray key, a virtual pad on a shared machine) must not reach the screens meanwhile
    if (!core::admits_device_event(device_event_kind(event.type), opts_.automated)) {
        return;
    }
    switch (event.type) {
        case SDL_EVENT_QUIT:
            quit_ = true;
            break;
        case SDL_EVENT_KEY_DOWN:
            key_event(event.key, true);
            break;
        case SDL_EVENT_KEY_UP:
            key_event(event.key, false);
            break;
        case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
            pad_button_event(event.gbutton, true);
            break;
        case SDL_EVENT_GAMEPAD_BUTTON_UP:
            pad_button_event(event.gbutton, false);
            break;
        case SDL_EVENT_GAMEPAD_AXIS_MOTION:
            pad_axis_event(event.gaxis);
            break;
        case SDL_EVENT_GAMEPAD_ADDED:
            if (SDL_Gamepad* pad = SDL_OpenGamepad(event.gdevice.which)) {
                gamepads_.push_back(pad);
            }
            break;
        case SDL_EVENT_GAMEPAD_REMOVED:
            for (auto it = gamepads_.begin(); it != gamepads_.end(); ++it) {
                if (SDL_GetGamepadID(*it) == event.gdevice.which) {
                    SDL_CloseGamepad(*it);
                    gamepads_.erase(it);
                    break;
                }
            }
            break;
        case SDL_EVENT_MOUSE_MOTION:
            last_device_ = "mouse";
            break;
        case SDL_EVENT_WINDOW_FOCUS_LOST:
            if (!opts_.automated && top() && (top()->id == ScreenId::Play || top()->id == ScreenId::Juice)) {
                LOG_INFO("shell", "focus lost: paused");
                push(ScreenId::Pause);
            }
            break;
        default:
            break;
    }
}

void Shell::key_event(const SDL_KeyboardEvent& e, bool down) {
    const std::string binding = core::key_binding(SDL_GetKeyName(e.key));
    if (!down) {
        held_.erase(binding);
        return;
    }
    key_down(binding, e.repeat);
}

void Shell::key_down(const std::string& binding, bool repeat) {
    last_device_ = "keyboard";
    if (capturing_) {
        if (repeat) {
            return;
        }
        if (binding == "key:escape") {
            finish_capture(std::nullopt);
        } else if (capturing_->slot == core::kKeyboardSlot) {
            finish_capture(binding);
        }
        return;
    }
    if constexpr (kDebugBuild) {   // F8: reserved for the bug report in debug builds (#275)
        if (binding == kBugKey) {
            bug_requested_ = bug_requested_ || !repeat;
            return;
        }
    }
    if (!repeat) {
        held_.insert(binding);
    }
    binding_pressed(binding, repeat);
}

void Shell::pad_button_event(const SDL_GamepadButtonEvent& e, bool down) {
    const char* name = SDL_GetGamepadStringForButton(static_cast<SDL_GamepadButton>(e.button));
    const std::string binding = core::pad_binding(name ? name : "unknown");
    if (!down) {
        held_.erase(binding);
        return;
    }
    const char* pad_name = SDL_GetGamepadNameForID(e.which);
    last_device_ = core::device_of_pad(pad_name ? pad_name : "");
    if (capturing_) {
        if (binding == "pad:select") {
            finish_capture(std::nullopt);
        } else if (capturing_->slot == core::kPadSlot) {
            finish_capture(binding);
        }
        return;
    }
    held_.insert(binding);
    binding_pressed(binding, false);
}

// The axes as presses: the left stick as d-pad presses for the menus (hysteresis; not held: the game reads the stick
// itself through stick() and held_actions()), each trigger as pad:l2 / pad:r2 past half travel (held, like a button).
// The analog values themselves are polled in poll_pads().
void Shell::pad_axis_event(const SDL_GamepadAxisEvent& e) {
    const double value = core::analog::axis_from_raw(e.value);
    const double deadzone = std::max(input_number("deadzone", 0.2), 0.05);
    auto device = [this, &e] {
        const char* pad_name = SDL_GetGamepadNameForID(e.which);
        last_device_ = core::device_of_pad(pad_name ? pad_name : "");
    };
    auto edge = [this, &device](const std::string& name, bool active, bool hold) {
        const std::string binding = "pad:" + name;
        const bool was = stick_dirs_[name];
        if (active && !was) {
            stick_dirs_[name] = true;
            device();
            if (hold) {
                held_.insert(binding);
            }
            if (capturing_) {
                if (capturing_->slot == core::kPadSlot) {
                    finish_capture(binding);
                }
            } else {
                binding_pressed(binding, false);
            }
        } else if (!active && was) {
            stick_dirs_[name] = false;
            held_.erase(binding);
        }
    };
    if (e.axis == SDL_GAMEPAD_AXIS_LEFT_TRIGGER || e.axis == SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) {
        const std::string name = e.axis == SDL_GAMEPAD_AXIS_LEFT_TRIGGER ? "l2" : "r2";
        triggers_[name] = core::analog::hysteresis(value, triggers_[name], kTriggerOn, kTriggerOff);
        edge(name, triggers_[name], true);
        return;
    }
    if (e.axis != SDL_GAMEPAD_AXIS_LEFTX && e.axis != SDL_GAMEPAD_AXIS_LEFTY) {
        return;
    }
    const double v = std::abs(value) < deadzone ? 0.0 : value;
    const double on = std::max(kStickOn, deadzone);
    const bool horizontal = e.axis == SDL_GAMEPAD_AXIS_LEFTX;
    const std::string neg = horizontal ? "dpad_left" : "dpad_up";
    const std::string pos = horizontal ? "dpad_right" : "dpad_down";
    edge(neg, core::analog::hysteresis(-v, stick_dirs_[neg], on, kStickOff), false);
    edge(pos, core::analog::hysteresis(v, stick_dirs_[pos], on, kStickOff), false);
}

// The pads' analog state for the game: the stick that leans furthest and the deepest trigger across all pads
void Shell::poll_pads() {
    if (pad_override_) {
        pad_ = *pad_override_;
        return;
    }
    PadAxes p;
    if (opts_.automated) {   // a drive's run reads no real stick or trigger (#276): at rest unless it sets them
        pad_ = p;
        return;
    }
    for (SDL_Gamepad* pad : gamepads_) {
        const double x = core::analog::axis_from_raw(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTX));
        const double y = core::analog::axis_from_raw(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTY));
        if (x * x + y * y > p.lx * p.lx + p.ly * p.ly) {
            p.lx = x;
            p.ly = y;
        }
        p.lt = std::max(p.lt, core::analog::axis_from_raw(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER)));
        p.rt = std::max(p.rt, core::analog::axis_from_raw(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER)));
    }
    pad_ = p;
}

double Shell::input_number(const char* key, double fallback) const {
    const auto in = settings_.find("input");
    if (in == settings_.end() || !in->is_object()) {
        return fallback;
    }
    const auto v = in->find(key);
    return v != in->end() && v->is_number() ? v->get<double>() : fallback;
}

bool Shell::input_flag(const char* key) const {
    const auto in = settings_.find("input");
    if (in == settings_.end() || !in->is_object()) {
        return false;
    }
    const auto v = in->find(key);
    return v != in->end() && v->is_boolean() && v->get<bool>();
}

core::analog::Vec2 Shell::stick() const {
    return core::analog::stick(pad_.lx, pad_.ly, input_number("deadzone", 0.2), input_flag("invert_y"));
}

double Shell::left_trigger() const {
    return core::analog::trigger(pad_.lt);
}

double Shell::right_trigger() const {
    return core::analog::trigger(pad_.rt);
}

// The move_* actions the stick holds: a raw lean past the deadzone (at least kStickHoldMin), invert_y honoured
std::vector<std::string> Shell::stick_actions() const {
    const double on = std::max(input_number("deadzone", 0.2), core::analog::kStickHoldMin);
    const double x = pad_.lx;
    const double y = input_flag("invert_y") ? -pad_.ly : pad_.ly;
    std::vector<std::string> out;
    const double leans[] = {-x, x, -y, y};   // in kMoveActions' order: left, right, up (-y), down (+y)
    for (std::size_t i = 0; i < std::size(kMoveActions); ++i) {
        if (leans[i] > on) {
            out.emplace_back(kMoveActions[i]);
        }
    }
    return out;
}

std::set<std::string> Shell::held_actions() const {
    std::set<std::string> out;
    for (const auto& [action, slots] : bindings()) {
        if (action.compare(0, 3, "ui_") == 0) {
            continue;
        }
        for (const std::string& b : slots) {
            if (!b.empty() && held_.count(b)) {
                out.insert(action);
            }
        }
    }
    for (const std::string& a : stick_actions()) {
        out.insert(a);
    }
    return out;
}

core::analog::Vec2 Shell::move_vector() const {
    // the held move_* actions from keys and buttons only (the stick comes in as its analog value)
    const core::Bindings b = bindings();
    auto held = [this, &b](const char* action) {
        const auto it = b.find(action);
        if (it == b.end()) {
            return 0.0;
        }
        for (const std::string& binding : it->second) {
            if (!binding.empty() && held_.count(binding)) {
                return 1.0;
            }
        }
        return 0.0;
    };
    core::analog::Vec2 dir{held("move_right") - held("move_left"), held("move_down") - held("move_up")};
    const double len = dir.length();
    if (len > 0) {
        dir.x /= len;
        dir.y /= len;
    }
    return core::analog::move_vector(dir, stick());
}

// drives and tests: as if the key or button of binding was pressed on device
void Shell::simulate(const std::string& binding, const std::string& device) {
    last_device_ = device;
    binding_pressed(binding, false);
}

void Shell::binding_pressed(const std::string& binding, bool repeat) {
    Screen* s = top();
    if (!s) {
        return;
    }
    // "press any key or button" on the title: everything but the cancel key opens the menu
    if (s->id == ScreenId::Title && !s->consent && !repeat) {
        bool excepted = false;
        for (const char* ex : kAnyKeyExcept) {
            excepted = excepted || binding == ex;
        }
        if (!excepted) {
            open_main_menu();
            return;
        }
    }
    const std::vector<std::string> actions = core::actions_for(bindings(), binding);
    // a held subtitle line (#167) takes the accept first: on a gamepad, south is accept and jump
    for (const std::string& action : actions) {
        if (action == "ui_accept" && track_.holding()) {
            track_.dismiss();
            return;
        }
    }
    for (const std::string& action : actions) {
        if (!repeat || action.compare(0, 3, "ui_") == 0) {
            if (dispatch(action)) {
                return;
            }
        }
    }
}

bool Shell::dispatch(const std::string& action) {
    if (action == "ui_accept" && track_.holding()) {
        track_.dismiss();
        return true;
    }
    Screen* s = top();
    if (!s) {
        return false;
    }
    ++dispatch_depth_;
    const bool used = screen_action(*s, action);
    --dispatch_depth_;
    if (dispatch_depth_ == 0) {
        flush_stack_ops();
    }
    return used;
}

bool Shell::is_down(const std::string& action) const {
    const core::Bindings b = bindings();
    const auto it = b.find(action);
    if (it != b.end()) {
        for (const std::string& binding : it->second) {
            if (!binding.empty() && held_.count(binding)) {
                return true;
            }
        }
    }
    const std::vector<std::string> stick = stick_actions();   // the stick holds move_* (#274)
    return std::find(stick.begin(), stick.end(), action) != stick.end();
}

void Shell::begin_capture(const std::string& action, std::size_t slot) {
    capturing_ = Capture{action, slot};
}

void Shell::finish_capture(const std::optional<std::string>& binding) {
    if (!capturing_) {
        return;
    }
    const Capture c = *capturing_;
    capturing_.reset();
    if (!binding) {
        return;
    }
    const auto r = core::rebind(bindings(), c.action, c.slot, *binding);
    if (!r) {
        return;
    }
    settings_["input"]["bindings"] = core::bindings_to_json(r->bindings);
    if (settings_menu_) {
        settings_menu_->dirty = true;
    }
    if (!r->conflicts.empty()) {
        say(t("controls.swapped", {{"action", t("action." + r->conflicts.front().first)}}));
    } else {
        say(t("controls.bound", {{"action", t("action." + c.action)}}));
    }
}

bool Shell::screen_action(Screen& s, const std::string& action) {
    switch (s.id) {
        case ScreenId::Title:
            if (s.consent) {
                bool used = true;
                if (action == "ui_cancel") {       // cancel = Later
                    s.consent->focus("later");
                    s.consent->focused()->accept();
                } else {
                    used = s.consent->action(action);
                }
                if (consent_answered_) {
                    consent_answered_ = false;
                    s.consent.reset();
                }
                return used;
            }
            if (action == "ui_accept") {
                open_main_menu();
                return true;
            }
            return false;
        case ScreenId::MainMenu:
            if (action == "ui_cancel") {
                pop();
                return true;
            }
            return s.list.action(action);
        case ScreenId::Settings:
            if (capturing_) {
                return true;
            }
            return settings_menu_ && settings_menu_->action(action);
        case ScreenId::Credits:
        case ScreenId::Help:
        case ScreenId::History:
            if (action == "ui_cancel" || action == "ui_accept") {
                pop();
                return true;
            }
            if (action == "ui_down") {
                s.offset += kStepPx;
                return true;
            }
            if (action == "ui_up") {
                s.offset = std::max(0.0, s.offset - kStepPx);
                return true;
            }
            return false;
        case ScreenId::Loading:
            return true;   // no input while loading
        case ScreenId::Play:
            if (action == "pause") {
                push(ScreenId::Pause);
                return true;
            }
            return play.action && play.action(action);
        case ScreenId::Juice:
            if (action == "pause") {
                push(ScreenId::Pause);
                return true;
            }
            return juice_ && juice_->action(action);
        case ScreenId::Pause:
            if (action == "pause" || action == "ui_cancel") {
                pop();
                return true;
            }
            return s.list.action(action);
    }
    return false;
}

// ---- Frame ---------------------------------------------------------------------------------------------------
void Shell::update(double dt) {
    time_ += dt;
    poll_pads();
    if (notice_t_ > 0) {
        notice_t_ -= dt;
        if (notice_t_ <= 0) {
            notice_.clear();
        }
    }
    if (drive_) {
        drive_->update();
    }
    if (Screen* s = top()) {
        update_screen(*s, dt);
    }
    track_.update(dt, access_flag("subtitle_hold"));
    narrate_update();
    for (auto it = captions_.begin(); it != captions_.end();) {
        it->second.t -= dt;
        it = it->second.t <= 0 ? captions_.erase(it) : std::next(it);
    }
    if (message_t_ > 0) {
        message_t_ -= dt;
        if (message_t_ <= 0) {
            message_.clear();
        }
    }
}

void Shell::update_screen(Screen& s, double dt) {
    s.t += dt;
    ++s.frames;
    switch (s.id) {
        case ScreenId::Loading:
            if (s.steps_done < kLoadingSteps) {
                ++s.steps_done;                     // a game runs its real load steps here, one per frame
                return;
            }
            if ((opts_.automated && s.frames >= kLoadingMinFrames) || s.t >= kLoadingMinS) {
                replace(s.next);
            }
            break;
        case ScreenId::Credits:
            if (!access_flag("reduce_motion")) {
                s.offset += kScrollPxS * dt;
            }
            break;
        case ScreenId::Play:
            if (play.update) {
                play.update(dt);
            }
            break;
        case ScreenId::Juice:
            if (juice_) {
                juice_->update(dt);
            }
            break;
        default:
            break;
    }
}

void Shell::render(SDL_Renderer* renderer) {
    (void)renderer;   // the Draw layer holds it since init()
    const double ui_scale = settings_["display"]["ui_scale"].is_number() ? settings_["display"]["ui_scale"].get<double>() : 1.0;
    draw_->begin_frame(access_number("text_scale", 1.0) * ui_scale, access_flag("readable_font"),
                       access_number("line_spacing", 1.0));
    draw_->clear(style::kBg);
    std::size_t first = stack_.size();
    while (first > 1 && stack_[first - 1].transparent) {
        --first;
    }
    for (std::size_t i = first > 0 ? first - 1 : 0; i < stack_.size(); ++i) {
        draw_screen(stack_[i]);
    }
    draw_subtitles();
    draw_notice();
    if (plant_ && top() && top()->id == ScreenId::MainMenu) {   // --drive pseudo-plant: a label too small for its text
        draw_->text("plant.too_small", t("menu.settings"), 8, 8, 30, 18);
    }
    draw_->end_frame();
    if (bug_requested_) {
        write_bug_report();   // the frame is drawn, not yet presented: its screenshot is this frame
    }
}

void Shell::draw_notice() {
    if (notice_.empty()) {
        return;
    }
    Draw& d = *draw_;
    const double w = std::min(static_cast<double>(style::kBaseW) - 16, d.text_width(notice_) + 24);
    const double h = d.row_h();
    const double x = (style::kBaseW - w) / 2;
    d.panel(x, 6, w, h);
    TextOpts o;
    o.align = Align::Center;
    o.color = style::kAccent;
    d.text("notice", notice_, x + 8, 6, w - 16, h, o);
}

// F8 (#275): bug_<time>/ in the user-data folder with the frame just drawn, the log tail, the settings and the run's
// details, for a tester to attach to an issue. Nothing leaves the machine.
void Shell::write_bug_report() {
    bug_requested_ = false;
    const std::time_t now = std::time(nullptr);
    namespace report = core::report;
    const std::optional<fs::path> dir = report::free_path(data_dir_, "bug", report::file_stamp(now), "");
    if (!dir) {
        LOG_ERROR("bug", "report not saved: too many reports in one second");
        return;
    }
    std::string error;
    const std::string info = report::bug_info(run_info(), report::utc_iso(now));
    const bool ok = core::write_file_atomic(*dir / "info.txt", info, &error) &&
                    core::write_file_atomic(*dir / "log_tail.txt", core::Log::tail(report::kBugLogLines), &error) &&
                    core::write_file_atomic(*dir / "settings.json", settings_text(settings_) + "\n", &error);
    if (!ok) {
        LOG_ERROR("bug", "report not saved: " << error);
        return;
    }
    const std::string path = core::path_to_utf8(*dir);
    if (!renderer_ || !save_frame(renderer_, core::path_to_utf8(*dir / "screenshot.bmp"))) {
        LOG_WARN("bug", "the report has no screenshot: " << SDL_GetError());
    }
    last_bug_report_ = path;
    LOG_INFO("bug", "report saved to " << path);
    std::cout << "BUG_REPORT " << path << "\n" << std::flush;
    notice(t("toast.bug_saved"));
}

void Shell::draw_screen(Screen& s) {
    switch (s.id) {
        case ScreenId::Title: draw_title(s); break;
        case ScreenId::MainMenu: draw_main_menu(s); break;
        case ScreenId::Settings: draw_settings(); break;
        case ScreenId::Credits: draw_credits(s); break;
        case ScreenId::Loading: draw_loading(s); break;
        case ScreenId::Play: draw_play(); break;
        case ScreenId::Pause: draw_pause(s); break;
        case ScreenId::Help: draw_text_page(s, "help.title", help_page_lines(), "help"); break;
        case ScreenId::History: draw_text_page(s, "history.title", history_page_lines(), "history"); break;
        case ScreenId::Juice:
            if (juice_) {
                juice_->draw(*draw_);
            }
            break;
    }
}

double Shell::draw_list(core::MenuList& list, double x, double y, double w, double label_w, double max_h,
                        const std::string& prefix, bool center) {
    Draw& d = *draw_;
    const double gap = 2;
    const double marker = d.char_w() + 6;           // room for the ">" focus marker
    // two columns, unless a label is too wide for its column at this text size: then label over value (stacked)
    bool stacked = false;
    if (label_w > 0) {
        for (const core::Row& row : list.rows) {
            if (row.kind != core::RowKind::Button && d.text_width(row.label()) > label_w - marker - 4) {
                stacked = true;
            }
        }
    }
    const double rh = stacked ? d.line_h() * 2 + style::kRowPad * 2 : d.row_h();
    std::size_t visible = list.rows.size();
    if (max_h > 0) {
        visible = static_cast<std::size_t>(std::max(1.0, std::floor((max_h + gap) / (rh + gap))));
    }
    const auto [top, count] = list.window(visible);
    double ry = y;
    for (std::size_t i = top; i < top + count; ++i) {
        const core::Row& row = list.rows[i];
        const bool focused = i == list.index;
        if (focused) {
            d.focus_box(x, ry, w, rh);
        } else {
            d.fill(x, ry, w, rh, style::kRow);
        }
        TextOpts o;
        o.color = row.is_enabled() ? style::kText : style::kDim;
        const std::string lid = prefix + "." + row.id;
        if (label_w > 0 && row.kind != core::RowKind::Button) {
            if (stacked) {
                d.text(lid, row.label(), x + marker, ry + style::kRowPad, w - marker - 4, d.line_h(), o);
                draw_value(row, x + marker, ry + style::kRowPad + d.line_h(), w - marker - 8, d.line_h(), focused, lid);
            } else {
                d.text(lid, row.label(), x + marker, ry, label_w - marker, rh, o);
                draw_value(row, x + label_w, ry, w - label_w - 8, rh, focused, lid);
            }
        } else {
            o.align = center ? Align::Center : Align::Left;
            d.text(lid, row.label(), x + marker, ry, w - marker * 2, rh, o);
        }
        ry += rh + gap;
    }
    // scroll hints: more rows above or below
    if (top > 0) {
        d.fill(x + w - 12, y - 5, 8, 3, style::kDim);
    }
    if (top + count < list.rows.size()) {
        d.fill(x + w - 12, ry + 1, 8, 3, style::kDim);
    }
    return ry;
}

void Shell::draw_value(const core::Row& row, double x, double y, double w, double h, bool focused,
                       const std::string& lid) {
    Draw& d = *draw_;
    TextOpts o;
    switch (row.kind) {
        case core::RowKind::Toggle:
        case core::RowKind::Choice: {
            if (focused) {
                TextOpts arrow;
                arrow.color = style::kAccent;
                arrow.raw = true;   // a symbol, not UI copy
                d.text(lid + ".left", "<", x, y, kArrowW, h, arrow);
                arrow.align = Align::Right;
                d.text(lid + ".right", ">", x + w - kArrowW, y, kArrowW, h, arrow);
            }
            o.align = Align::Center;
            d.text(lid + ".value", row.value(), x + kArrowW, y, w - kArrowW * 2, h, o);
            break;
        }
        case core::RowKind::Slider: {
            // the number's room: kSliderTextChars, or more when a language writes it longer (the pseudo drive's
            // "[100%~]"; the widest percentage keeps the bars of one tab the same length), at most half the row
            const std::string text = row.value ? row.value() : "";
            const double widest = std::max(d.text_width(text), d.text_width(t("value.percent", {{"n", "100"}})));
            const double tw = std::min(w / 2, std::max(kSliderTextChars * d.char_w(), widest));
            const double bw = w - tw;
            d.bar(x, y + (h - 6) / 2, bw - 8, 6, row.fraction ? row.fraction() : 0.0);
            o.align = Align::Right;
            d.text(lid + ".value", text, x + bw, y, tw, h, o);
            break;
        }
        case core::RowKind::Binding: {
            const json& list = settings_["input"]["bindings"];
            const std::string action = row.id.substr(5);   // "bind_<action>"
            const double cw = (w - kCellGap) / 2;
            for (std::size_t slot = 0; slot < 2; ++slot) {
                const double cx = x + static_cast<double>(slot) * (cw + kCellGap);
                std::string binding;
                if (list.is_object() && list.contains(action) && list[action].is_array() && slot < list[action].size() &&
                    list[action][slot].is_string()) {
                    binding = list[action][slot].get<std::string>();
                }
                const std::string text = binding.empty() ? t("controls.unbound")
                                                         : binding_label(core::glyph_name(slot == 0 ? "keyboard" : pad_set(), binding));
                if (focused && row.cell == static_cast<int>(slot)) {
                    d.rect(cx, y + 2, cw, h - 4, style::kFocus);
                }
                o.align = Align::Center;
                o.raw = !binding.empty();   // a key or button name; "None" is UI copy
                d.text(lid + ".slot" + std::to_string(slot), text, cx + 4, y, cw - 8, h, o);
            }
            break;
        }
        case core::RowKind::Button:
            break;
    }
}

void Shell::draw_title(Screen& s) {
    Draw& d = *draw_;
    const double W = style::kBaseW;
    const double H = style::kBaseH;
    const std::string name = t("title.name", {{"name", opts_.game_name}});
    double mult = style::kTitleMult;
    while (mult > 1.0 && d.text_width(name, mult) > W - 32) {   // a long name shrinks instead of being cut
        mult -= 0.5;
    }
    TextOpts title;
    title.align = Align::Center;
    title.mult = mult;
    title.color = style::kAccent;
    d.text("title.name", name, 0, H * 0.22, W, d.line_h(mult), title);
    const bool steady = access_flag("reduce_motion");
    if (!s.consent && (steady || std::fmod(s.t, kBlinkS * 2) < kBlinkS)) {
        TextOpts o;
        o.align = Align::Center;
        d.text("title.press", t("title.press_any"), 0, H * 0.62, W, d.line_h(), o);
    }
    TextOpts small;
    small.align = Align::Right;
    small.color = style::kDim;
    d.text("title.version", t("title.version", {{"version", opts_.version}}), 0, H - d.line_h() - 8, W - 12, d.line_h(), small);
    if (s.consent) {
        d.fill(0, 0, W, H, style::kBlack, style::kOverlayAlpha);
        // every height from the text it holds, so the dialog grows with the text size instead of overflowing
        const double cw = d.text_scale() > 1.25 ? W - 40 : 420;
        const double pad = 10;
        const std::string body = t("consent.body");
        const std::size_t fit = static_cast<std::size_t>(std::max(1, d.chars_fit(cw - 32)));
        const double body_h = static_cast<double>(core::wrap_chars(body, fit).size()) * d.line_h();
        const double list_h = static_cast<double>(s.consent->rows.size()) * (d.row_h() + 2);
        const double ch = std::max(190.0, pad + d.line_h() + 4 + body_h + 8 + list_h + pad);
        const double x = (W - cw) / 2;
        const double y = std::max(4.0, (H - ch) / 2);
        d.panel(x, y, cw, ch);
        TextOpts heading;
        heading.color = style::kAccent;
        d.text("consent.title", t("consent.title"), x + 16, y + pad, cw - 32, d.line_h(), heading);
        TextOpts wrap;
        wrap.wrap = true;
        d.text("consent.body", body, x + 16, y + pad + d.line_h() + 4, cw - 32, body_h, wrap);
        draw_list(*s.consent, x + cw * 0.26, y + pad + d.line_h() + 4 + body_h + 8, cw * 0.48, 0, 0, "consent", true);
    }
}

void Shell::draw_main_menu(Screen& s) {
    Draw& d = *draw_;
    const double W = style::kBaseW;
    const std::string name = t("title.name", {{"name", opts_.game_name}});
    double mult = style::kTitleMult;
    while (mult > 1.0 && d.text_width(name, mult) > W - 32) {
        mult -= 0.5;
    }
    TextOpts title;
    title.align = Align::Center;
    title.mult = mult;
    title.color = style::kAccent;
    d.text("menu.title", name, 0, 40, W, d.line_h(mult), title);
    core::MenuList& list = s.list;
    double w = kMenuW;
    for (const core::Row& row : list.rows) {
        w = std::max(w, d.text_width(row.label()) + 2 * (d.char_w() + 6) + 8);
    }
    w = std::min(w, W - 16);
    draw_list(list, (W - w) / 2, 40 + d.line_h(mult) + 30, w, 0, style::kBaseH - 40 - d.line_h(mult) - 30 - 40, "menu", true);
    TextOpts hint;
    hint.color = style::kDim;
    draw_hint("menu.hint", "ui_accept", "hint.select", 16, style::kBaseH - d.line_h() - 10, W - 32, hint);
}

// A prompt and what it does: the key's name (raw: not UI copy), two spaces, then the hint text through t()
void Shell::draw_hint(const std::string& id, const std::string& action, const std::string& hint_key, double x, double y,
                      double w, TextOpts o) {
    Draw& d = *draw_;
    const std::string key = prompt(action).second;
    const double kw = std::min(w, d.text_width(key));
    TextOpts k = o;
    k.raw = true;
    d.text(id + ".key", key, x, y, kw + 1, d.line_h(), k);
    const double gap = 2 * d.char_w();
    d.text(id, t(hint_key), x + kw + gap, y, std::max(1.0, w - kw - gap), d.line_h(), o);
}

void Shell::draw_settings() {
    Draw& d = *draw_;
    if (!settings_menu_) {
        return;
    }
    core::SettingsMenu& menu = *settings_menu_;
    const double W = style::kBaseW;
    const double H = style::kBaseH;
    TextOpts heading;
    heading.align = Align::Center;
    heading.mult = style::kHeadingMult;
    heading.color = style::kAccent;
    const double title_y = 6;
    d.text("settings.title", t("settings.title"), 0, title_y, W, d.line_h(style::kHeadingMult), heading);
    // the tab bar: each tab as wide as its text; a row that does not fit wraps onto the next
    const double th = d.line_h() + 10;
    double tx = 16;
    double ty = title_y + d.line_h(style::kHeadingMult) + 4;
    for (const char* tab : core::SettingsMenu::kTabs) {
        const std::string label = t(std::string("settings.tab.") + tab);
        const double tw = d.text_width(label) + 18;
        if (tx + tw > W - 16 && tx > 16) {
            tx = 16;
            ty += th + 4;
        }
        const bool selected = menu.tab == tab;
        if (selected && menu.on_tabs) {
            d.focus_box(tx, ty, tw, th);
        } else {
            d.fill(tx, ty, tw, th, selected ? style::kRowFocus : style::kRow);
        }
        if (selected) {   // the open tab is underlined, not just tinted
            d.fill(tx + 4, ty + th - 3, tw - 8, 2, style::kAccent);
        }
        TextOpts o;
        o.align = Align::Center;
        o.color = selected ? style::kText : style::kDim;
        d.text(std::string("settings.tab.") + tab, label, tx + (selected && menu.on_tabs ? d.char_w() : 0), ty,
               tw - (selected && menu.on_tabs ? d.char_w() : 0), th, o);
        tx += tw + 4;
    }
    const double list_y = ty + th + 10;
    const std::string hint = message_.empty() ? t("settings.hint") : message_;
    const double hint_lines = static_cast<double>(core::wrap_chars(hint, static_cast<std::size_t>(std::max(1, d.chars_fit(W - 32)))).size());
    const double hint_h = hint_lines * d.line_h();
    const double list_bottom = H - hint_h - 14;
    draw_list(menu.list(), kContentX, list_y, kContentW, kLabelW, list_bottom - list_y, "settings." + menu.tab, false);
    TextOpts ho;
    ho.align = Align::Center;
    ho.wrap = true;
    ho.color = message_.empty() ? style::kDim : style::kAccent;
    d.text("settings.hint", hint, 16, H - hint_h - 8, W - 32, hint_h, ho);
    if (capturing_) {
        d.fill(0, 0, W, H, style::kBlack, style::kOverlayAlpha);
        const double pw = std::min(W - 16, std::max(380.0, d.text_width(t("controls.press_key", {{"action", "Move right"}})) + 32));
        const double ph = d.line_h() * 2 + 44;
        const double px = (W - pw) / 2;
        const double py = (H - ph) / 2;
        d.panel(px, py, pw, ph);
        const char* key = capturing_->slot == core::kKeyboardSlot ? "controls.press_key" : "controls.press_button";
        TextOpts o;
        o.align = Align::Center;
        d.text("settings.capture", t(key, {{"action", t("action." + capturing_->action)}}), px + 8, py + 14, pw - 16, d.line_h(), o);
        o.color = style::kDim;
        d.text("settings.capture.hint", t("controls.capture_cancel"), px + 8, py + 14 + d.line_h() + 8, pw - 16, d.line_h(), o);
    }
}

void Shell::draw_credits(const Screen& s) {
    Draw& d = *draw_;
    TextOpts heading;
    heading.align = Align::Center;
    heading.mult = style::kHeadingMult;
    heading.color = style::kAccent;
    d.text("credits.title", t("credits.title"), 0, 12, style::kBaseW, d.line_h(style::kHeadingMult), heading);
    TextOpts hint;
    hint.align = Align::Center;
    hint.color = style::kDim;
    hint.wrap = true;
    const double hint_h = d.line_h() * 2;
    d.text("credits.hint", t("credits.hint"), 16, style::kBaseH - hint_h - 6, style::kBaseW - 32, hint_h, hint);
    const double lh = d.line_h() + 2;
    if (!s.credits) {   // no CREDITS.md yet: a placeholder, no scrolling
        TextOpts o;
        o.align = Align::Center;
        o.wrap = true;
        d.text("credits.placeholder", t("credits.placeholder"), kAreaX, kAreaY + 10, kAreaW, kAreaH - 70, o);
        o.wrap = false;
        d.text("credits.engine", t("credits.engine"), kAreaX, kAreaY + kAreaH - 40, kAreaW, lh, o);
        return;
    }
    std::vector<std::string> rows;
    const std::size_t fit = static_cast<std::size_t>(std::max(1, d.chars_fit(kAreaW)));
    for (const std::string& line : *s.credits) {
        std::vector<std::string> wrapped = core::wrap_chars(line, fit);
        if (wrapped.empty()) {
            wrapped.emplace_back("");
        }
        rows.insert(rows.end(), wrapped.begin(), wrapped.end());
    }
    rows.emplace_back("");
    rows.push_back(t("credits.engine"));
    const double total = static_cast<double>(rows.size()) * lh;
    double offset = s.offset;
    if (total > kAreaH) {
        offset = std::fmod(offset, total + kAreaH);   // loop: start again from below
    } else {
        offset = 0;
    }
    const double start = total > kAreaH ? kAreaH - offset : 0;
    d.clip(kAreaX, kAreaY, kAreaW, kAreaH);
    for (std::size_t i = 0; i < rows.size(); ++i) {
        const double y = kAreaY + start + static_cast<double>(i) * lh;
        if (rows[i].empty() || y + lh <= kAreaY || y >= kAreaY + kAreaH) {
            continue;
        }
        if (y >= kAreaY && y + lh <= kAreaY + kAreaH) {
            TextOpts o;
            o.align = Align::Center;
            o.raw = i + 1 != rows.size();   // CREDITS.md is content, not UI copy; the engine line is
            d.text("credits.line" + std::to_string(i), rows[i], kAreaX, y, kAreaW, lh, o);
        } else {
            // half scrolled out: drawn, not a layout problem (an empty id keeps it out of the record)
            TextOpts o;
            o.align = Align::Center;
            d.text("", rows[i], kAreaX, y, kAreaW, lh, o);
        }
    }
    d.unclip();
}

void Shell::draw_loading(const Screen& s) {
    Draw& d = *draw_;
    const double bw = 360;
    const double x = (style::kBaseW - bw) / 2;
    const double y = style::kBaseH / 2.0;
    const double progress = static_cast<double>(s.steps_done) / kLoadingSteps;
    TextOpts o;
    o.align = Align::Center;
    d.text("loading.title", t("loading.title"), 0, y - d.line_h() - 16, style::kBaseW, d.line_h(), o);
    d.bar(x, y, bw, 12, progress, style::kAccent);
    o.color = style::kDim;
    d.text("loading.percent", t("value.percent", {{"n", std::to_string(static_cast<int>(std::floor(progress * 100 + 0.5)))}}),
           0, y + 18, style::kBaseW, d.line_h(), o);
}

void Shell::draw_play() {
    Draw& d = *draw_;
    if (play.draw) {
        play.draw(d);
    }
    // the HUD hint, outlined: it sits over the game
    TextOpts hint;
    hint.outline = true;
    draw_hint("play.hint", "pause", "hint.pause", 12, 8, style::kBaseW - 24, hint);
}

void Shell::draw_pause(Screen& s) {
    Draw& d = *draw_;
    const double W = style::kBaseW;
    const double H = style::kBaseH;
    d.fill(0, 0, W, H, style::kBlack, style::kOverlayAlpha);
    core::MenuList& list = s.list;
    // the panel's height follows its rows and the text size, its width the longest button
    const double list_y = 10 + d.line_h(style::kHeadingMult) + 10;
    const double h = std::min(H - 8, std::max(kPauseH, list_y + static_cast<double>(list.rows.size()) * (d.row_h() + 2) + 12));
    // and its width the longest button plus the focus marker's room on both sides (draw_list), so "Dialogue
    // history" fits at 200 % text (the access sweep)
    double widest = 0;
    for (const core::Row& row : list.rows) {
        widest = std::max(widest, d.text_width(row.label()) + 2 * (d.char_w() + 6) + 8);
    }
    const double w = std::min(W - 16, std::max(kPauseW, widest + kListPad * 2 + kRowInset));
    const double x = (W - w) / 2;
    const double y = std::max(4.0, (H - h) / 2);
    d.panel(x, y, w, h);
    TextOpts heading;
    heading.align = Align::Center;
    heading.mult = style::kHeadingMult;
    heading.color = style::kAccent;
    d.text("pause.title", t("pause.title"), x, y + 10, w, d.line_h(style::kHeadingMult), heading);
    draw_list(list, x + kListPad, y + list_y, w - kListPad * 2, 0, h - list_y - 8, "pause", true);
}

std::vector<std::string> Shell::help_page_lines() const {
    std::vector<std::pair<std::string, std::string>> controls;
    for (const char* action : kControlActions) {
        controls.emplace_back(action, prompt(action).second);
    }
    return core::help_lines([this](const std::string& key, const core::TrArgs& args) { return t(key, args); },
                            objective_, history_, controls);
}

std::vector<std::string> Shell::history_page_lines() const {
    std::vector<std::string> lines;
    for (const core::HistoryEntry& e : history_.entries()) {
        lines.push_back(t("help.last_line", {{"name", e.name}, {"text", e.text}}));
    }
    if (lines.empty()) {
        lines.push_back(t("history.empty"));
    }
    return lines;
}

void Shell::draw_text_page(Screen& s, const std::string& title_key, const std::vector<std::string>& lines,
                           const std::string& prefix) {
    Draw& d = *draw_;
    TextOpts heading;
    heading.align = Align::Center;
    heading.mult = style::kHeadingMult;
    heading.color = style::kAccent;
    d.text(prefix + ".title", t(title_key), 0, 12, style::kBaseW, d.line_h(style::kHeadingMult), heading);
    TextOpts hint;
    hint.align = Align::Center;
    hint.color = style::kDim;
    hint.wrap = true;
    const double hint_h = d.line_h() * 2;
    d.text(prefix + ".hint", t("page.hint"), 16, style::kBaseH - hint_h - 6, style::kBaseW - 32, hint_h, hint);
    const double lh = d.line_h() + 2;
    std::vector<std::string> rows;
    const std::size_t fit = static_cast<std::size_t>(std::max(1, d.chars_fit(kAreaW)));
    for (const std::string& line : lines) {
        const auto wrapped = core::wrap_chars(line, fit);
        rows.insert(rows.end(), wrapped.begin(), wrapped.end());
    }
    const double area_h = style::kBaseH - hint_h - 12 - kAreaY;
    const std::size_t visible = static_cast<std::size_t>(std::max(1.0, std::floor(area_h / lh)));
    const std::size_t max_first = rows.size() > visible ? rows.size() - visible : 0;
    const std::size_t first = std::min(max_first, static_cast<std::size_t>(std::max(0.0, s.offset / kStepPx)));
    s.offset = static_cast<double>(first) * kStepPx;   // clamped (history opens at the end)
    for (std::size_t i = first; i < rows.size() && i < first + visible; ++i) {
        d.text(prefix + ".line" + std::to_string(i), rows[i], kAreaX, kAreaY + static_cast<double>(i - first) * lh, kAreaW, lh);
    }
    if (first > 0) {
        d.fill(kAreaX + kAreaW - 12, kAreaY - 6, 8, 3, style::kDim);
    }
    if (first + visible < rows.size()) {
        d.fill(kAreaX + kAreaW - 12, kAreaY + area_h + 2, 8, 3, style::kDim);
    }
}

void Shell::draw_subtitles() {
    Draw& d = *draw_;
    const json& access = settings_["access"];
    double bottom = style::kBaseH - kSubtitleBottom;
    const core::SubtitleLine* cur = track_.current();
    if (cur && core::subtitle_allowed(*cur, settings_)) {
        const std::string size = access["subtitle_size"].is_string() ? access["subtitle_size"].get<std::string>() : "medium";
        const double mult = size == "small" ? style::kSubtitleMult[0] : size == "large" ? style::kSubtitleMult[2]
                          : size == "xl" ? style::kSubtitleMult[3] : style::kSubtitleMult[1];
        const double inner = kSubtitleW - kSubtitlePad * 2;
        const std::size_t fit = static_cast<std::size_t>(std::max(1, d.chars_fit(inner, mult)));
        const std::string said = line_text(*cur);
        const auto lines = core::wrap_chars(said, fit);
        const double lh = d.line_h(mult);
        const bool names = access_flag("speaker_names") && !cur->name.empty();
        const double h = static_cast<double>(lines.size()) * lh + (names ? lh : 0) + kSubtitlePad * 2;
        const double x = (style::kBaseW - kSubtitleW) / 2;
        const double y = bottom - h;
        const double bg = access["subtitle_background"].is_number() ? access["subtitle_background"].get<double>() : 0.6;
        d.fill(x, y, kSubtitleW, h, style::kBlack, static_cast<Uint8>(std::floor(bg * 255 + 0.5)));
        // outlined, so the line reads at any background opacity the player picks
        TextOpts o;
        o.mult = mult;
        o.outline = true;
        double ty = y + kSubtitlePad;
        if (names) {
            TextOpts speaker = o;
            speaker.color = style::kAccent;
            d.text("subtitle.speaker", t("subtitle.speaker", {{"name", cur->name}}), x + kSubtitlePad, ty, inner, lh, speaker);
            ty += lh;
        }
        o.wrap = true;
        d.text("subtitle.text", said, x + kSubtitlePad, ty, inner, static_cast<double>(lines.size()) * lh, o);
        bottom = y - 4;
    }
    for (const auto& [id, c] : captions_) {
        const double w = d.text_width(c.text) + kSubtitlePad * 2;
        const double h = d.line_h() + kSubtitlePad;
        const double x = style::kBaseW - w - 12;
        const double y = bottom - h;
        const double bg = access["subtitle_background"].is_number() ? access["subtitle_background"].get<double>() : 0.6;
        d.fill(x, y, w, h, style::kBlack, static_cast<Uint8>(std::floor(std::max(bg, 0.4) * 255 + 0.5)));
        TextOpts o;
        o.outline = true;
        d.text("caption." + id, c.text, x + kSubtitlePad, y, w - kSubtitlePad * 2, h, o);
        bottom = y - 2;
    }
}

// ---- Narration (#165) ----------------------------------------------------------------------------------------
std::string Shell::describe(const core::Row& row) const {
    return core::narration_line(row.label(), t(core::narration_role_key(row.kind)), row.value ? row.value() : "");
}

void Shell::narrate_update() {
    const Screen* s = top();
    if (s != narrated_top_) {
        narrated_top_ = s;
        if (s) {
            const char* key = kScreenTitleKeys[static_cast<int>(s->id)];
            const std::string title = *key ? t(key) : screen_name(s->id);
            speak(core::narration_line(title, t("narrate.screen")));
            return;
        }
    }
    if (!s) {
        return;
    }
    const core::Row* row = nullptr;
    if (s->id == ScreenId::Settings && settings_menu_ && !settings_menu_->on_tabs) {
        row = settings_menu_->list().focused();
    } else if (s->id == ScreenId::Title && s->consent) {
        row = s->consent->focused();
    } else if (s->id == ScreenId::MainMenu || s->id == ScreenId::Pause) {
        row = s->list.focused();
    }
    if (!row) {
        return;
    }
    const std::string line = describe(*row);
    if (!line.empty() && line != last_narration_) {
        speak(line);
    }
}

void Shell::speak(const std::string& line) {
    last_narration_ = line;
    LOG_DEBUG("narrate", line);
    if (opts_.automated || !access_flag("narration")) {
        return;
    }
    {
        std::lock_guard<std::mutex> lock(speech_mutex_);
        speech_queue_.push_back(speech_command(line));
    }
    if (!speech_thread_.joinable()) {
        speech_thread_ = std::thread([this] { speech_worker(); });
    }
    speech_cv_.notify_one();
}

// the speech thread: one line at a time through the system's speech command, the game never waits
void Shell::speech_worker() {
    for (;;) {
        std::string cmd;
        {
            std::unique_lock<std::mutex> lock(speech_mutex_);
            speech_cv_.wait(lock, [this] { return speech_stop_ || !speech_queue_.empty(); });
            if (speech_stop_) {
                return;
            }
            cmd = speech_queue_.front();
            speech_queue_.pop_front();
        }
        if (std::system(cmd.c_str()) != 0) {
            LOG_WARN("narrate", "the system's speech command failed (verify spd-say / say / PowerShell)");
        }
    }
}

}  // namespace shell

// {{FOOTER}}
