// ---------------------------------------------------------------------------
// Drive.hpp
// Purpose : Scripted smoke scenarios (`python tools/dev.py smoke --drive <name>`): they press the same actions a
//           player would, frame by frame, and print proof lines dev.py echoes (SETTINGS_WRITTEN, DRIVE_DONE,
//           ACCESS_*). Without --drive, a smoke run walks title -> menu -> play and lets the game run.
// Usage   : menus            title -> settings: master volume to 0.5, reduce motion on -> back (saves) -> quit;
//                            prints SETTINGS_WRITTEN <path> once the file holds the new values
//           show:<screen>    title | menu | settings | pause | subtitle | play: opens it, then ends (--screenshot)
//           access[:opts]    the accessibility sweep's tour (tools/access/sweep.py): res=WxH, scale=N, pad, read
//           A scenario ends with DRIVE_DONE <name>; a failure logs [ERROR] first, which fails dev.py smoke.
// Notes   : A scenario is a queue of small steps run one per frame (press, wait for a screen, move focus to a row,
//           slide a slider); a step that needs to decide at run time (is the consent question up?) adds steps in
//           front of the queue. Each wait has a frame limit, so a broken menu fails instead of hanging. Add a
//           scenario: a builder in Drive.cpp's table, then a line in docs/ENGINE_FLOW.md.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include <deque>
#include <functional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace shell {

class Shell;
enum class ScreenId;

class Drive {
public:
    Drive(Shell& shell, std::string name);
    void update();                       // one frame of the scenario (before the screens update)
    const std::string& name() const { return name_; }
    int exit_code() const { return exit_code_; }

    // ---- Tunables ----
    static constexpr int kPressGap = 2;          // frames after each injected press
    static constexpr int kWaitLimit = 900;       // frames a wait may take before the scenario fails
    static constexpr int kFocusLimit = 40;       // presses to reach a menu item
    static constexpr int kDriveLimit = 6000;     // frames for a whole scenario
    static constexpr double kTargetMaster = 0.5; // menus drives the master volume here
    static constexpr int kMaxSliderSteps = 40;

private:
    struct Step {
        std::string what;
        std::function<bool(Step&)> run;   // true when done
        int counter = 0;
    };

    Shell& shell_;
    std::string name_;
    std::deque<Step> steps_;
    std::vector<Step> inserted_;         // steps a running step adds in front of the queue
    bool building_ = true;
    bool finished_ = false;
    int exit_code_ = 0;
    int frame_ = 0;
    bool pad_ = false;                   // the access drive's gamepad-only run

    void add(Step step);
    // building blocks
    void then(const std::string& what, std::function<void()> fn);
    void frames(int n);
    void press(const std::string& action);
    void wait_screen(const std::string& name);
    void wait_for(const std::string& what, std::function<bool()> pred, int limit = kWaitLimit);
    void focus(const std::string& id, const std::string& step = "ui_down");
    void open(const std::string& item, const std::string& screen);
    void to_menu();
    void to_tab(const std::string& tab);
    void slide_to(const std::string& what, std::function<double()> read, double target);
    void access_screen(const std::string& name);
    void fail(const std::string& why);
    void done(int code = 0);
    nlohmann::json reach();
    // scenarios
    void build_default();
    void build_menus();
    bool build_show(const std::string& screen);
    void build_access(const std::string& options);
};

}  // namespace shell
