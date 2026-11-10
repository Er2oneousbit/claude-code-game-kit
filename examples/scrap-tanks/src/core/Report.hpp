// ---------------------------------------------------------------------------
// Report.hpp
// Purpose : Crash files and bug reports (#275): the text of a crash file (version, time, screen, the error, the log
//           tail, the settings), the info file of the F8 bug report, free file names per second, and the crash
//           context that main.cpp's handlers write through when the game stops on an exception or a fatal signal.
// Usage   : core::report::set_crash_context({data_dir, base, [&]{ return info_now(); }, [&]{ return settings(); }});
//           if (auto file = core::report::write_crash("std::runtime_error: boom")) std::cout << "CRASH_WRITTEN " ...;
//           core::report::crash_report(info, error, core::report::utc_iso(now), core::Log::tail(60), settings_text)
// Notes   : No SDL: the shell fills the context at boot (the user-data folder, the game's name and version, and
//           callbacks for the screen, locale and settings) and clears the callbacks when it goes. Before that, or
//           with no data folder, crash files go to the system's temp folder. A crash file must never hide the crash:
//           write_crash catches everything and reports a failure through `why`. From a signal handler
//           (from_signal = true) it skips the callbacks and does not wait for the log's lock; that path is best
//           effort (allocating there is not async-signal-safe, but the process is going down anyway).
//           File names use UTC: crashes/crash_20261110_101500.txt, then crash_20261110_101500_2.txt in the same
//           second; bug reports are folders, bug_20261110_101500/.
//           Everything here lives in core::report, not core: games keep their own code in core:: too, and names
//           like RunInfo (a roguelike's run) or free_path are ones a game may well have.
//
// Pseudocode:
//   write_crash(error): dir = context.data_dir or temp -> info = context.info() (not from a signal)
//     -> text = crash_report(info, error, now, Log tail, context.settings()) -> path = free_path(dir/crashes, "crash")
//     -> write_file_atomic(path, text) -> path
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): moved into core::report, so a game's own core::RunInfo
//           or core::free_path still compiles
// ---------------------------------------------------------------------------
#pragma once

#include <cstddef>
#include <ctime>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>

namespace core::report {

// ---- Tunables ----
constexpr const char* kCrashDir = "crashes";      // inside the user-data folder
constexpr std::size_t kCrashLogLines = 60;        // log lines in a crash file
constexpr std::size_t kBugLogLines = 200;         // log lines in a bug report
constexpr int kMaxSameSecond = 50;                // crash_<stamp>_2 ... _50 when several land in one second

// What a report says about the run.
struct RunInfo {
    std::string game;
    std::string version;
    std::string build;       // "debug" or "release"
    std::string os;
    std::string screen;      // the top screen ("" = none yet)
    std::string locale;
    std::string seed;        // "" = the run has none
};

std::string utc_iso(std::time_t t);      // "2026-11-10T10:15:00Z"
std::string file_stamp(std::time_t t);   // "20261110_101500" (UTC)

// The text of a crash file.
std::string crash_report(const RunInfo& info, const std::string& error, const std::string& time_iso,
                         const std::string& log_tail, const std::string& settings_json);

// The info.txt of a bug report.
std::string bug_info(const RunInfo& info, const std::string& time_iso);

// dir/<stem>_<stamp><ext> if it is free, else _2, _3 ... up to kMaxSameSecond; nullopt when all are taken.
std::optional<std::filesystem::path> free_path(const std::filesystem::path& dir, const std::string& stem,
                                               const std::string& stamp, const std::string& ext);

// ---- The crash context (main.cpp's handlers write through it) ----
struct CrashContext {
    std::filesystem::path data_dir;                 // empty: the system's temp folder
    RunInfo base;                                   // the game, version, build, os
    std::function<RunInfo()> info;                  // the run right now (screen, locale); empty: base
    std::function<std::string()> settings;          // settings.json's text; empty: none
};

void set_crash_context(CrashContext context);
void clear_crash_callbacks();                       // the shell is going: keep the folder and base, drop the rest

// Writes the crash file; its path, or nullopt with *why set.
std::optional<std::filesystem::path> write_crash(const std::string& error, bool from_signal = false,
                                                 std::string* why = nullptr);

}  // namespace core::report
