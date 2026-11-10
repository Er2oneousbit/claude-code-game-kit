// ---------------------------------------------------------------------------
// Log.hpp
// Purpose : Minimal channel-based logger. Header-only, SDL-free. Greppable output format. Keeps the last lines in
//           memory for crash files and bug reports (Log::tail).
// Usage   : LOG_INFO("core", "started " << name);
//           LOG_ERROR("save", "failed to open " << path);
//           Log::set_debug(true) turns LOG_DEBUG output on (main.cpp --debug).
//           Log::tail(50) -> the last 50 lines written, oldest first (core/Report.hpp puts them in a crash file)
// Notes   : "[ERROR]" lines are what `dev.py smoke` scans for. Keep that tag.
//           A mutex guards the output and the tail: the narration thread logs too. The tail holds kTailLines lines,
//           debug lines included only when they were printed.
//           Swap this for spdlog later if needed; call sites will not change.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the in-memory tail for crash files and the F8 bug
//           report (#275), a mutex around writes
// ---------------------------------------------------------------------------
#pragma once

#include <cstddef>
#include <deque>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>

namespace core {

class Log {
public:
    enum class Level { Debug, Info, Warn, Error };

    // ---- Tunables ----
    static constexpr std::size_t kTailLines = 200;   // lines kept for crash files and bug reports

    static void set_debug(bool on) { debug_enabled() = on; }
    static bool is_debug() { return debug_enabled(); }

    // Writes one formatted line. Errors and warnings go to stderr, the rest to stdout.
    static void write(Level level, const std::string& channel, const std::string& msg) {
        if (level == Level::Debug && !debug_enabled()) {
            return;
        }
        const std::string line = std::string("[") + tag(level) + "][" + channel + "] " + msg;
        std::lock_guard<std::mutex> lock(mutex());
        std::ostream& out = (level >= Level::Warn) ? std::cerr : std::cout;
        out << line << '\n';
        std::deque<std::string>& t = lines();
        t.push_back(line);
        while (t.size() > kTailLines) {
            t.pop_front();
        }
    }

    // The last n lines written (at most kTailLines), oldest first, one per line. wait = false (a crash handler: the
    // crash may have happened inside write()) gives up instead of waiting for the lock.
    static std::string tail(std::size_t n = kTailLines, bool wait = true) {
        std::unique_lock<std::mutex> lock(mutex(), std::defer_lock);
        if (wait) {
            lock.lock();
        } else if (!lock.try_lock()) {
            return "(the log was busy when the game stopped)\n";
        }
        const std::deque<std::string>& t = lines();
        std::string out;
        for (std::size_t i = t.size() > n ? t.size() - n : 0; i < t.size(); ++i) {
            out += t[i];
            out += '\n';
        }
        return out;
    }

private:
    // Function-local statics avoid a separate .cpp for one flag.
    static bool& debug_enabled() {
        static bool flag = false;
        return flag;
    }

    static std::mutex& mutex() {
        static std::mutex m;
        return m;
    }

    static std::deque<std::string>& lines() {
        static std::deque<std::string> t;
        return t;
    }

    static const char* tag(Level level) {
        switch (level) {
            case Level::Debug: return "DEBUG";
            case Level::Info:  return "INFO";
            case Level::Warn:  return "WARN";
            case Level::Error: return "ERROR";
        }
        return "?";
    }
};

}  // namespace core

#define CORE_LOG_(level, channel, expr)                    \
    do {                                                   \
        std::ostringstream core_log_stream_;               \
        core_log_stream_ << expr;                          \
        ::core::Log::write(level, channel, core_log_stream_.str()); \
    } while (0)

#define LOG_DEBUG(channel, expr) CORE_LOG_(::core::Log::Level::Debug, channel, expr)
#define LOG_INFO(channel, expr)  CORE_LOG_(::core::Log::Level::Info, channel, expr)
#define LOG_WARN(channel, expr)  CORE_LOG_(::core::Log::Level::Warn, channel, expr)
#define LOG_ERROR(channel, expr) CORE_LOG_(::core::Log::Level::Error, channel, expr)

// {{FOOTER}}
