// ---------------------------------------------------------------------------
// Drive.hpp
// Purpose : Scripted smoke scenarios (`python tools/dev.py smoke --drive <name>`): they press the same actions a
//           player would, frame by frame, and print proof lines dev.py echoes (SETTINGS_WRITTEN, DRIVE_DONE,
//           ACCESS_*). Without --drive, a smoke run walks title -> menu -> play and lets the game run.
// Usage   : menus            title -> settings: master volume to 0.5, reduce motion on -> back (saves) -> quit;
//                            prints SETTINGS_WRITTEN <path> once the file holds the new values
//           crash            throws in a frame: main.cpp writes the crash file, prints CRASH_WRITTEN, exits 1
//           pseudo           (with --locale pseudo) visits every screen and checks every visible label: cut off,
//                            past the screen edge, or not through t(): PSEUDO_FAIL lines and exit 1, or PSEUDO_PASS
//           pseudo-plant     the same plus one label too small for its text: must fail and name plant.too_small
//           bug              presses F8 on the menu and checks bug_<time>/: DRIVE_BUG <path> (debug builds)
//           display          (#308) the Display tab's Apply: stages a window size, Back warns, Apply sets and saves
//                            it and opens the confirm, which reverts by itself after 15 REAL seconds; then two
//                            Backs discard a staged change. DRIVE_DISPLAY lines (staged, warned, applied, reverted,
//                            discarded)
//           show:<screen>    title | menu | settings | pause | subtitle | play | juice | credits | apply (a Display
//                            change waiting) | confirm (Keep these display settings?): opens it, then ends
//                            (--screenshot)
//           access[:opts]    the accessibility sweep's tour (tools/access/sweep.py): res=WxH, scale=N, pad, read
//           A scenario ends with DRIVE_DONE <name>; a failure logs [ERROR] first, which fails dev.py smoke.
// Notes   : A scenario is a queue of small steps run one per frame (press, wait for a screen, move focus to a row,
//           slide a slider); a step that needs to decide at run time (is the consent question up?) adds steps in
//           front of the queue. Each wait has a frame limit, so a broken menu fails instead of hanging. Add a
//           scenario: a builder in Drive.cpp's table, then a line in docs/ENGINE_FLOW.md.
//           The pseudo check reads the access report of a drawn frame (Draw.hpp) through core::label_problem; the
//           juice demo and the bug report exist in debug builds only (smoke builds the debug preset).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): crash, pseudo, pseudo-plant, bug, show:juice (#275)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): display, show:apply, show:confirm (#308)
// ---------------------------------------------------------------------------
#pragma once

#include <chrono>
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
    static constexpr double kRealSlackS = 2.0;   // display: the confirm reverts within this of its 15 real seconds
    static constexpr int kRealWaitMs = 10;       // display: sleep per frame while the confirm counts down

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
    int checked_ = 0;                    // pseudo: screens checked, labels seen, problems found
    int labels_ = 0;
    int problems_ = 0;
    nlohmann::json before_;              // display: the window size before the drive staged one
    std::chrono::steady_clock::time_point applied_at_;   // display: when Apply opened the confirm
    int applied_frame_ = 0;

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
    void check(const std::string& name);  // the pseudo layout check of the next drawn frame
    void to_juice();
    void fail(const std::string& why);
    void done(int code = 0);
    nlohmann::json reach();
    // scenarios
    void build_default();
    void build_menus();
    void build_crash();
    void build_pseudo(bool plant);
    void build_bug();
    void build_display();
    void stage_resolution();             // settings: the Display tab's window size one step right (#308)
    bool build_show(const std::string& screen);
    void build_access(const std::string& options);
};

}  // namespace shell

// {{FOOTER}}
