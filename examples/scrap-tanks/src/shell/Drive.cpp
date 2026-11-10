// ---------------------------------------------------------------------------
// Drive.cpp
// Purpose : Implementation of the scripted smoke scenarios (see Drive.hpp).
// Usage   : built by Shell::init in automated runs; Shell::update calls Drive::update once a frame.
// Notes   : The drive is a friend of Shell: it reads the stack, the settings and the draw layer's access report
//           directly, and presses actions through Shell::inject (or, gamepad-only, through the action's pad
//           button). Proof lines go to stdout as one line each so dev.py and tools/access/sweep.py can read them.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "shell/Drive.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <optional>
#include <set>
#include <utility>

#include "core/AtomicFile.hpp"
#include "core/Bindings.hpp"
#include "core/Log.hpp"
#include "core/Menu.hpp"
#include "core/ShellLogic.hpp"
#include "shell/Shell.hpp"

namespace shell {

using nlohmann::json;

namespace {

const char* kAccessActions[] = {"ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel", "pause"};
const char* kPromptActions[] = {"move_left", "move_right", "jump", "attack", "interact", "pause"};
const char* kShowScreens = "title, menu, settings, pause, subtitle, play";

bool starts_with(const std::string& s, const std::string& prefix) {
    return s.compare(0, prefix.size(), prefix) == 0;
}

std::string top_name(const Shell& shell) {
    const Screen* s = shell.top();
    return s ? screen_name(s->id) : "";
}

}  // namespace

Drive::Drive(Shell& shell, std::string name) : shell_(shell), name_(std::move(name)) {
    if (name_ == "default") {
        build_default();
    } else if (name_ == "menus") {
        build_menus();
    } else if (starts_with(name_, "show:")) {
        if (!build_show(name_.substr(5))) {
            fail("unknown --drive " + name_ + " (show:<" + kShowScreens + ">)");
        }
    } else if (name_ == "access" || starts_with(name_, "access:")) {
        build_access(name_ == "access" ? "" : name_.substr(7));
    } else {
        fail("unknown --drive " + name_ + " (menus, access[:res=WxH,scale=N,pad,read], show:<screen>)");
    }
    building_ = false;
    if (name_ != "default") {
        LOG_INFO("drive", "scenario " << name_);
    }
}

void Drive::add(Step step) {
    if (building_) {
        steps_.push_back(std::move(step));
    } else {
        inserted_.push_back(std::move(step));
    }
}

void Drive::update() {
    if (finished_) {
        return;
    }
    if (++frame_ > kDriveLimit) {
        fail("drive " + name_ + " did not finish in " + std::to_string(kDriveLimit) + " frames");
        return;
    }
    if (steps_.empty()) {
        return;
    }
    Step& step = steps_.front();
    const bool finished_step = step.run(step);
    if (finished_) {   // the step failed or ended the run: the queue goes now, after its lambda has returned
        steps_.clear();
        inserted_.clear();
        return;
    }
    if (finished_step) {
        steps_.pop_front();
        for (auto it = inserted_.rbegin(); it != inserted_.rend(); ++it) {
            steps_.push_front(std::move(*it));
        }
        inserted_.clear();
    }
}

void Drive::fail(const std::string& why) {
    LOG_ERROR("drive", why);
    done(1);
}

void Drive::done(int code) {
    exit_code_ = code;
    finished_ = true;   // update() empties the queue once the running step has returned
    shell_.finish("DRIVE_DONE " + name_, code);
}

// ---- Building blocks ---------------------------------------------------------------------------------------
void Drive::then(const std::string& what, std::function<void()> fn) {
    add({what, [fn](Step&) { fn(); return true; }});
}

void Drive::frames(int n) {
    add({"frames", [n](Step& s) { return ++s.counter >= n; }});
}

void Drive::press(const std::string& action) {
    add({"press " + action, [this, action](Step& s) {
             if (s.counter == 0) {
                 if (pad_) {   // the access drive's gamepad-only run: the action's pad button
                     const std::string b = core::binding_with_prefix(shell_.bindings(), action, "pad:");
                     if (b.empty()) {
                         fail(action + " has no gamepad button: a gamepad-only player cannot press it");
                         return true;
                     }
                     shell_.simulate(b, "pad_xbox");
                 } else {
                     shell_.inject(action);
                 }
             }
             return ++s.counter > kPressGap;
         }});
}

void Drive::wait_for(const std::string& what, std::function<bool()> pred, int limit) {
    add({"wait " + what, [this, what, pred, limit](Step& s) {
             if (pred()) {
                 return true;
             }
             if (++s.counter > limit) {
                 fail("timed out waiting for " + what);
             }
             return false;
         }});
}

void Drive::wait_screen(const std::string& name) {
    wait_for("screen " + name, [this, name] { return top_name(shell_) == name; });
}

// presses `step` until the focused item is id (one press every other frame)
void Drive::focus(const std::string& id, const std::string& step) {
    add({"focus " + id, [this, id, step](Step& s) {
             if (shell_.focus_id() == id) {
                 return true;
             }
             if (s.counter % 2 == 0) {
                 if (pad_) {
                     const std::string b = core::binding_with_prefix(shell_.bindings(), step, "pad:");
                     if (b.empty()) {
                         fail(step + " has no gamepad button");
                         return true;
                     }
                     shell_.simulate(b, "pad_xbox");
                 } else {
                     shell_.inject(step);
                 }
             }
             if (++s.counter > kFocusLimit * 2) {
                 fail("could not focus " + id + " (focused: " + shell_.focus_id() + ")");
             }
             return false;
         }});
}

void Drive::open(const std::string& item, const std::string& screen) {
    focus(item);
    press("ui_accept");
    wait_screen(screen);
}

// title (answers the consent question with Later) -> main menu
void Drive::to_menu() {
    wait_screen("title");
    then("answer consent", [this] {
        if (shell_.top() && shell_.top()->consent) {
            press("ui_cancel");
        }
    });
    press("ui_accept");
    wait_screen("main_menu");
}

// settings: from the rows back up to the tab bar, then to a tab
void Drive::to_tab(const std::string& tab) {
    then("to the tab bar", [this] {
        for (int i = 0; i < kFocusLimit && shell_.settings_menu_ && !shell_.settings_menu_->on_tabs; ++i) {
            shell_.inject(shell_.settings_menu_->list().index == 0 ? "ui_up" : "ui_down");
        }
    });
    focus("tabs." + tab, "ui_right");
}

// Presses left or right on the focused slider until read() equals target, from any start value
void Drive::slide_to(const std::string& what, std::function<double()> read, double target) {
    add({"slide " + what, [this, what, read, target](Step& s) {
             const std::string action = core::slide_action(read(), target);
             if (action.empty()) {
                 return true;
             }
             if (++s.counter > kMaxSliderSteps) {
                 fail(what + " did not reach " + std::to_string(target) + " (is " + std::to_string(read()) + ")");
                 return true;
             }
             shell_.inject(action);
             return false;
         }});
}

// which controls ui_down reaches on the screen's list (every enabled row must come round), and what each says
json Drive::reach() {
    const Screen* top = shell_.top();
    json out = {{"start", shell_.focus_id()}, {"controls", 0}, {"reached", 0}, {"unreached", json::array()},
                {"focus_like_hover", json::array()}, {"narration", json::object()}};
    const core::MenuList* list = nullptr;
    std::string prefix;
    if (top && (top->id == ScreenId::MainMenu || top->id == ScreenId::Pause)) {
        list = &top->list;
    } else if (top && top->id == ScreenId::Settings && shell_.settings_menu_) {
        list = &shell_.settings_menu_->list();
        prefix = shell_.settings_menu_->tab + ".";
    }
    if (!list) {
        return out;
    }
    std::vector<std::string> want;
    for (const core::Row& row : list->rows) {
        if (row.is_enabled()) {
            want.push_back(prefix + row.id);
        }
        out["narration"][prefix + row.id] = shell_.describe(row);
    }
    std::set<std::string> seen;
    for (std::size_t i = 0; i <= list->rows.size(); ++i) {
        seen.insert(shell_.focus_id());
        shell_.inject("ui_down");
    }
    out["controls"] = want.size();
    int reached = 0;
    for (const std::string& id : want) {
        if (seen.count(id)) {
            ++reached;
        } else {
            out["unreached"].push_back(id);
        }
    }
    out["reached"] = reached;
    return out;
}

void Drive::access_screen(const std::string& name) {
    add({"access " + name, [this, name](Step& s) {
             if (s.counter++ == 0) {
                 const Screen* top = shell_.top();
                 shell_.draw_->request_access(name, top && top->id == ScreenId::Play);
                 return false;
             }
             std::optional<json> report = shell_.draw_->take_access_report();
             if (!report) {
                 if (s.counter > kWaitLimit) {
                     fail("no drawn frame for the access report of " + name);
                 }
                 return false;
             }
             (*report)["focus"] = reach();
             std::cout << "ACCESS_SCREEN " << report->dump() << "\n" << std::flush;
             return true;
         }});
}

// ---- Scenarios -------------------------------------------------------------------------------------------------
// no --drive: walk into the game and stay there (main.cpp ends the run after --smoke N frames)
void Drive::build_default() {
    to_menu();
    open("play", "play");
}

void Drive::build_menus() {
    to_menu();
    open("settings", "settings");
    to_tab("audio");
    press("ui_down");
    focus("audio.master");
    slide_to("audio.master", [this] { return shell_.settings_["audio"]["master"].get<double>(); }, kTargetMaster);
    to_tab("access");
    press("ui_down");
    focus("access.reduce_motion");
    then("reduce motion on", [this] {
        if (!shell_.access_flag("reduce_motion")) {
            press("ui_accept");
        }
    });
    press("ui_cancel");                                   // back: saves settings.json
    wait_screen("main_menu");
    then("check the file", [this] {
        const std::string path = core::path_to_utf8(shell_.settings_file());
        const std::optional<std::string> text = core::read_file(shell_.settings_file());
        const json saved = text ? json::parse(*text, nullptr, false) : json();
        const bool ok = saved.is_object() && saved["audio"]["master"].is_number() &&
                        core::slide_action(saved["audio"]["master"].get<double>(), kTargetMaster).empty() &&
                        saved["access"]["reduce_motion"] == true;
        if (!ok) {
            fail("settings.json does not hold master " + std::to_string(kTargetMaster) + " and reduce_motion true: " + path);
            return;
        }
        std::cout << "SETTINGS_WRITTEN " << path << "\n" << std::flush;
    });
    focus("quit");
    press("ui_accept");                                   // Shell::quit ends the run with DRIVE_DONE
    frames(10);
    then("quit did not end the run", [this] { fail("quit did not end the run"); });
}

// show:<screen>: open it, let it settle, end (main.cpp saves --screenshot)
bool Drive::build_show(const std::string& screen) {
    if (screen == "title") {
        wait_screen("title");
        then("answer consent", [this] {
            if (shell_.top() && shell_.top()->consent) {
                press("ui_cancel");
            }
        });
        frames(10);
        wait_for("the blinking prompt", [this] {
            const Screen* top = shell_.top();
            const double t = top ? std::fmod(top->t, 1.2) : 0.0;
            return t > 0.1 && t < 0.5;
        });
    } else if (screen == "menu") {
        to_menu();
        frames(5);
    } else if (screen == "settings") {
        to_menu();
        open("settings", "settings");
        to_tab("audio");
        press("ui_down");
        focus("audio.master");
        press("ui_left");
        frames(5);
    } else if (screen == "pause") {
        to_menu();
        open("play", "play");
        frames(30);
        press("pause");
        wait_screen("pause");
        frames(5);
    } else if (screen == "subtitle") {
        then("speaker names on", [this] { shell_.settings_["access"]["speaker_names"] = true; });
        to_menu();
        open("play", "play");
        wait_for("the subtitle line", [this] { return shell_.track_.current() && shell_.track_.elapsed() > 1.6; });
    } else if (screen == "play") {
        to_menu();
        open("play", "play");
        frames(60);
    } else {
        return false;
    }
    then("done", [this] { done(0); });
    return true;
}

// The accessibility sweep (#91, #85): access[:res=WxH][,scale=N][,pad][,read]
void Drive::build_access(const std::string& options) {
    double scale = 1.0;
    int res_w = 0;
    int res_h = 0;
    bool read = false;
    std::string part;
    std::vector<std::string> parts;
    for (const char c : options + ",") {
        if (c == ',') {
            if (!part.empty()) parts.push_back(part);
            part.clear();
        } else {
            part.push_back(c);
        }
    }
    for (const std::string& p : parts) {
        if (p == "pad") {
            pad_ = true;
        } else if (p == "read") {
            read = true;                              // the readable font and double line spacing (#167)
        } else if (starts_with(p, "scale=")) {
            scale = std::strtod(p.c_str() + 6, nullptr);
        } else if (starts_with(p, "res=")) {
            const auto x = p.find('x');
            if (x == std::string::npos) {
                fail("access option res needs WxH: " + p);
                return;
            }
            res_w = std::atoi(p.substr(4, x - 4).c_str());
            res_h = std::atoi(p.c_str() + x + 1);
        } else {
            fail("unknown access option " + p + " (res=WxH, scale=N, pad, read)");
            return;
        }
    }
    then("ACCESS_INPUT", [this, scale] {
        const core::Bindings b = shell_.bindings();
        json actions = json::object();
        for (const char* a : kAccessActions) {
            actions[a] = {{"keyboard", !core::binding_with_prefix(b, a, "key:").empty()},
                          {"gamepad", !core::binding_with_prefix(b, a, "pad:").empty()}};
        }
        std::cout << "ACCESS_INPUT " << json{{"pad", pad_}, {"text_scale", scale}, {"actions", actions}}.dump() << "\n"
                  << std::flush;
    });
    wait_screen("title");
    then("window and text size", [this, scale, read, res_w, res_h] {
        if (res_w > 0 && res_h > 0 && shell_.window_) {
            SDL_SetWindowSize(shell_.window_, res_w, res_h);   // the letterbox scale follows the window
        }
        if (scale != 1.0 || read) {
            shell_.settings_["access"]["text_scale"] = scale;
            if (read) {
                shell_.settings_["access"]["readable_font"] = true;
                shell_.settings_["access"]["line_spacing"] = 2.0;
            }
            shell_.apply_settings();
        }
    });
    frames(2);
    access_screen("title");
    then("answer consent", [this] {
        if (shell_.top() && shell_.top()->consent) {
            press("ui_cancel");
        }
    });
    press("ui_accept");
    wait_screen("main_menu");
    access_screen("main_menu");
    open("settings", "settings");
    for (const char* tab : core::SettingsMenu::kTabs) {
        to_tab(tab);
        access_screen(std::string("settings/") + tab);
        if (std::string(tab) == "controls") {               // the one-handed layout (#166), live, then reset
            focus("controls.preset_one_hand_left");
            press("ui_accept");
            then("ACCESS_PRESET", [this] {
                const bool applied = shell_.settings_["input"]["bindings"]["attack"][0] == "key:f";
                focus("controls.reset");
                press("ui_accept");
                then("ACCESS_PRESET line", [this, applied] {
                    const bool reset = shell_.settings_["input"]["bindings"]["attack"][0] == "key:j";
                    std::cout << "ACCESS_PRESET " << json{{"applied", applied}, {"reset", reset}}.dump() << "\n" << std::flush;
                });
            });
        }
    }
    press("ui_cancel");
    wait_screen("main_menu");
    open("credits", "credits");
    access_screen("credits");
    press("ui_cancel");
    wait_screen("main_menu");
    open("play", "play");
    frames(40);
    access_screen("play");
    then("ACCESS_SUBTITLE and ACCESS_PROMPTS", [this] {
        const core::SubtitleLine* cur = shell_.track_.current();
        std::cout << "ACCESS_SUBTITLE "
                  << json{{"visible", cur != nullptr && shell_.access_flag("subtitles")},
                          {"text", cur ? cur->text : ""}, {"speaker", cur ? cur->name : ""}, {"id", cur ? cur->id : ""}}.dump()
                  << "\n";
        json rows = json::object();
        const core::Bindings b = shell_.bindings();
        for (const char* a : kPromptActions) {
            const std::string kb = core::prompt_binding(b, a, "keyboard");
            rows[a] = {{"keyboard", shell_.binding_label(core::glyph_name("keyboard", kb))}, {"shown", shell_.prompt(a).second}};
        }
        std::cout << "ACCESS_PROMPTS "
                  << json{{"device", shell_.last_device_}, {"glyphs", shell_.glyph_set()}, {"actions", rows}}.dump() << "\n"
                  << std::flush;
        // subtitle_hold (#167), live: a finished line stays until accept, then goes
        shell_.settings_["access"]["subtitle_hold"] = true;
        shell_.track_.dismiss();
        if (!shell_.say_line("guide.welcome")) {
            fail("the hold check could not play guide.welcome");
        }
    });
    wait_for("the held line", [this] { return shell_.track_.holding(); }, kDriveLimit);
    then("ACCESS_HOLD", [this] {
        const bool held = shell_.track_.holding();
        shell_.inject("ui_accept");
        std::cout << "ACCESS_HOLD " << json{{"held", held}, {"dismissed", shell_.track_.current() == nullptr}}.dump() << "\n"
                  << std::flush;
        shell_.settings_["access"]["subtitle_hold"] = false;
    });
    press("pause");
    wait_screen("pause");
    access_screen("pause");
    for (const char* page : {"help", "history"}) {          // #167: both reachable and readable
        open(page, page);
        access_screen(page);
        press("ui_cancel");
        wait_screen("pause");
    }
    open("quit", "title");
    then("done", [this] { done(0); });
}

}  // namespace shell
