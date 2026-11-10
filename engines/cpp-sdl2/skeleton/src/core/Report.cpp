// ---------------------------------------------------------------------------
// Report.cpp
// Purpose : Implementation of crash files and bug-report texts (see Report.hpp).
// Usage   : compiled into the `core` library; call through Report.hpp.
// Notes   : gmtime_s / gmtime_r instead of std::gmtime: thread-safe, and MSVC warns about std::gmtime (C4996).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/Report.hpp"

#include <cstdio>
#include <exception>
#include <system_error>
#include <utility>

#include "core/AtomicFile.hpp"
#include "core/Log.hpp"

namespace core {

namespace fs = std::filesystem;

namespace {

CrashContext& context() {
    static CrashContext c;
    return c;
}

bool utc_parts(std::time_t t, std::tm* out) {
#ifdef _WIN32
    return gmtime_s(out, &t) == 0;
#else
    return gmtime_r(&t, out) != nullptr;
#endif
}

std::string format_utc(std::time_t t, const char* fmt) {
    std::tm tm{};
    if (!utc_parts(t, &tm)) {
        return "unknown";
    }
    char buf[32];
    const std::size_t n = std::strftime(buf, sizeof buf, fmt, &tm);
    return n ? std::string(buf, n) : "unknown";
}

std::string or_none(const std::string& s) {
    return s.empty() ? "none" : s;
}

std::string header_lines(const RunInfo& info, const std::string& time_iso) {
    return "game: " + or_none(info.game) + "\n" + "version: " + or_none(info.version) + "\n" +
           "build: " + or_none(info.build) + "\n" + "os: " + or_none(info.os) + "\n" + "time: " + time_iso + "\n" +
           "screen: " + or_none(info.screen) + "\n" + "locale: " + or_none(info.locale) + "\n" +
           "seed: " + or_none(info.seed) + "\n";
}

}  // namespace

std::string utc_iso(std::time_t t) {
    return format_utc(t, "%Y-%m-%dT%H:%M:%SZ");
}

std::string file_stamp(std::time_t t) {
    return format_utc(t, "%Y%m%d_%H%M%S");
}

std::string crash_report(const RunInfo& info, const std::string& error, const std::string& time_iso,
                         const std::string& log_tail, const std::string& settings_json) {
    std::string out = or_none(info.game) + " crash report\n" + header_lines(info, time_iso);
    out += "\nerror: " + error + "\n";
    out += "\nlog tail:\n" + (log_tail.empty() ? std::string("(no log lines)\n") : log_tail);
    if (out.back() != '\n') {
        out += '\n';
    }
    out += "\nsettings:\n" + (settings_json.empty() ? std::string("(not loaded yet)") : settings_json) + "\n";
    return out;
}

std::string bug_info(const RunInfo& info, const std::string& time_iso) {
    return or_none(info.game) + " bug report\n" + header_lines(info, time_iso);
}

std::optional<fs::path> free_path(const fs::path& dir, const std::string& stem, const std::string& stamp,
                                  const std::string& ext) {
    std::error_code ec;
    for (int n = 1; n <= kMaxSameSecond; ++n) {
        const std::string name = stem + "_" + stamp + (n > 1 ? "_" + std::to_string(n) : "") + ext;
        const fs::path p = dir / path_from_utf8(name);
        if (!fs::exists(p, ec)) {
            return p;
        }
    }
    return std::nullopt;
}

void set_crash_context(CrashContext c) {
    context() = std::move(c);
}

void clear_crash_callbacks() {
    context().info = nullptr;
    context().settings = nullptr;
}

std::optional<fs::path> write_crash(const std::string& error, bool from_signal, std::string* why) {
    try {
        const CrashContext& c = context();
        std::error_code ec;
        const fs::path base = c.data_dir.empty() ? fs::temp_directory_path(ec) : c.data_dir;
        RunInfo info = c.base;
        std::string settings;
        if (!from_signal) {
            if (c.info) {
                info = c.info();
            }
            if (c.settings) {
                settings = c.settings();
            }
        }
        const std::time_t now = std::time(nullptr);
        const std::string text = crash_report(info, error, utc_iso(now), Log::tail(kCrashLogLines, !from_signal), settings);
        const std::optional<fs::path> file = free_path(base / kCrashDir, "crash", file_stamp(now), ".txt");
        if (!file) {
            if (why) {
                *why = "too many crash files in one second";
            }
            return std::nullopt;
        }
        std::string error_text;
        if (!write_file_atomic(*file, text, &error_text)) {
            if (why) {
                *why = error_text;
            }
            return std::nullopt;
        }
        return file;
    } catch (const std::exception& e) {
        if (why) {
            *why = e.what();
        }
    } catch (...) {
        if (why) {
            *why = "unknown error while writing the crash file";
        }
    }
    return std::nullopt;
}

}  // namespace core

// {{FOOTER}}
