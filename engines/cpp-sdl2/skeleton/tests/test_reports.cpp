// ---------------------------------------------------------------------------
// test_reports.cpp
// Purpose : Tests the #275 logic without SDL: the crash file's text and where it lands (core/Report.hpp), the log
//           tail it carries (core/Log.hpp), the ASCII pseudo locale (core/I18n.hpp: pseudo_ascii, tr_pseudo) and the
//           pseudo-locale layout check (core/ShellLogic.hpp: label_problem).
// Usage   : python tools/dev.py test     (ctest lists one test per TEST_CASE)
// Notes   : The crash-file test works in its own temp folder (its name holds "Í"), removed at the end, and resets
//           the crash context afterwards. The smoke run proves the rest: smoke --drive crash, bug, pseudo.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include <chrono>
#include <filesystem>
#include <string>
#include <system_error>

#include "core/AtomicFile.hpp"
#include "core/I18n.hpp"
#include "core/Log.hpp"
#include "core/Report.hpp"
#include "core/ShellLogic.hpp"

namespace fs = std::filesystem;

namespace {

struct TempDir {
    fs::path path;
    TempDir() {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() / core::path_from_utf8("gamekit-report-\xC3\x8D-" + std::to_string(stamp));
        fs::create_directories(path);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
};

bool contains(const std::string& text, const std::string& part) {
    return text.find(part) != std::string::npos;
}

}  // namespace

TEST_CASE("UTC stamps name the files and date the reports") {
    CHECK(core::utc_iso(0) == "1970-01-01T00:00:00Z");
    CHECK(core::file_stamp(86400 + 3661) == "19700102_010101");
}

TEST_CASE("a crash report names the run, the error, the log tail and the settings") {
    core::RunInfo info;
    info.game = "Test";
    info.version = "0.1.0";
    info.build = "debug";
    info.screen = "play";
    info.locale = "en";
    const std::string text = core::crash_report(info, "exception: boom", "2026-11-10T10:00:00Z", "[INFO][core] BOOT_OK\n",
                                                "{\"language\": \"en\"}");
    CHECK(text.rfind("Test crash report\n", 0) == 0);
    CHECK(contains(text, "version: 0.1.0\n"));
    CHECK(contains(text, "screen: play\n"));
    CHECK(contains(text, "seed: none\n"));            // a run without a seed says so
    CHECK(contains(text, "error: exception: boom\n"));
    CHECK(contains(text, "log tail:\n[INFO][core] BOOT_OK\n"));
    CHECK(contains(text, "settings:\n{\"language\": \"en\"}\n"));
    // before the settings exist, and with no log yet
    const std::string early = core::crash_report(core::RunInfo{}, "boom", "t", "", "");
    CHECK(contains(early, "(no log lines)"));
    CHECK(contains(early, "(not loaded yet)"));
    CHECK(contains(core::bug_info(info, "t"), "Test bug report\n"));
}

TEST_CASE("free_path counts up within a second and gives up after the limit") {
    TempDir dir;
    const auto first = core::free_path(dir.path, "crash", "20261110_100000", ".txt");
    REQUIRE(first.has_value());
    CHECK(first->filename() == "crash_20261110_100000.txt");
    REQUIRE(core::write_file_atomic(*first, "x"));
    const auto second = core::free_path(dir.path, "crash", "20261110_100000", ".txt");
    REQUIRE(second.has_value());
    CHECK(second->filename() == "crash_20261110_100000_2.txt");
    for (int n = 2; n <= core::kMaxSameSecond; ++n) {
        REQUIRE(core::write_file_atomic(dir.path / ("crash_20261110_100000_" + std::to_string(n) + ".txt"), "x"));
    }
    CHECK_FALSE(core::free_path(dir.path, "crash", "20261110_100000", ".txt").has_value());
}

TEST_CASE("write_crash puts the file in crashes/ of the data folder with the shell's details") {
    TempDir dir;
    LOG_INFO("test", "a line the crash file must carry");
    core::CrashContext context;
    context.data_dir = dir.path;
    context.base.game = "Test";
    context.info = [] {
        core::RunInfo i;
        i.game = "Test";
        i.screen = "juice_demo";
        return i;
    };
    context.settings = [] { return std::string("{\"audio\": {}}"); };
    core::set_crash_context(context);
    std::string why;
    const auto file = core::write_crash("exception: planted", false, &why);
    REQUIRE_MESSAGE(file.has_value(), why);
    CHECK(file->parent_path() == dir.path / core::kCrashDir);
    const std::string text = core::read_file(*file).value_or("");
    CHECK(contains(text, "screen: juice_demo\n"));
    CHECK(contains(text, "a line the crash file must carry"));
    CHECK(contains(text, "{\"audio\": {}}"));
    // from a signal handler: no callbacks (only the base details), still a file
    const auto from_signal = core::write_crash("fatal signal SIGSEGV", true, &why);
    REQUIRE_MESSAGE(from_signal.has_value(), why);
    CHECK_FALSE(contains(core::read_file(*from_signal).value_or(""), "juice_demo"));
    core::clear_crash_callbacks();
    core::set_crash_context({});
}

TEST_CASE("the log keeps its last lines for crash files and bug reports") {
    for (int i = 0; i < 3; ++i) {
        LOG_INFO("tail", "line " << i);
    }
    const std::string tail = core::Log::tail(2);
    CHECK_FALSE(contains(tail, "line 0"));
    CHECK(contains(tail, "[INFO][tail] line 1\n[INFO][tail] line 2\n"));
    CHECK(core::Log::tail(2, false) == tail);         // nobody holds the lock: the crash path reads it too
}

TEST_CASE("the ASCII pseudo locale brackets and lengthens without accents") {
    CHECK(core::pseudo_ascii("Play") == "[Play~~]");
    CHECK(core::pseudo_ascii("Volume {n}%") == "[Volume {n}%~~~~]");   // placeholders kept, not counted
    for (const char c : core::pseudo_ascii("Credits and settings")) {
        CHECK(static_cast<unsigned char>(c) < 128);   // the 8x8 debug font draws ASCII only
    }
    core::StringTables tables;
    tables["en"]["menu.play"] = "Play";
    tables["en"]["greet"] = "Hi {name}";
    CHECK(core::tr_pseudo(tables, "menu.play") == "[Play~~]");
    CHECK(core::tr_pseudo(tables, "greet", {{"name", "Ana"}}) == "[Hi Ana~~]");   // the value is not pseudo-ised
    CHECK(core::tr_pseudo(tables, "missing.key") == "missing.key");             // bare: the check flags it
}

TEST_CASE("the layout check flags cut-off, off-screen and untranslated labels") {
    core::DrawnLabel ok;
    ok.text = "[Play~~]";
    ok.x = 10;
    ok.y = 10;
    ok.w = 64;
    ok.h = 8;
    CHECK(core::label_problem(ok, 640, 360, true).empty());
    core::DrawnLabel cut = ok;
    cut.fits = false;
    cut.why = "wider than its box";
    CHECK(core::label_problem(cut, 640, 360, true) == "wider than its box");
    core::DrawnLabel off = ok;
    off.x = 600;
    CHECK(core::label_problem(off, 640, 360, true) == "past the screen edge");
    core::DrawnLabel bare = ok;
    bare.text = "Play";
    CHECK(core::label_problem(bare, 640, 360, true) == "not through t() (untranslated)");
    CHECK(core::label_problem(bare, 640, 360, false).empty());   // English: no brackets expected
    bare.raw = true;                                             // a key name or CREDITS.md
    CHECK(core::label_problem(bare, 640, 360, true).empty());
}

// {{FOOTER}}
