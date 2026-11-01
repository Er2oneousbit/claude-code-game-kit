// ---------------------------------------------------------------------------
// AtomicFile.cpp
// Purpose : Implementation of the crash-safe writer and the file reader (see AtomicFile.hpp).
// Usage   : compiled into the `core` library; call through AtomicFile.hpp.
// Notes   : Uses C stdio for the write because flushing to the disk (fsync / _commit) needs a file
//           descriptor, which iostreams do not expose. On Windows the path goes in as UTF-16
//           (_wfopen_s), so non-ASCII folder names work. On Linux/macOS the folder entry is not fsynced
//           after the rename; the file content is, which covers crashes and most power cuts.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/AtomicFile.hpp"

#include <cstdio>
#include <fstream>
#include <iterator>
#include <system_error>

#ifdef _WIN32
#include <io.h>        // _commit, _fileno
#else
#include <unistd.h>    // fsync, fileno
#endif

namespace core {

namespace fs = std::filesystem;

namespace {

void set_error(std::string* error, const std::string& text) {
    if (error) {
        *error = text;
    }
}

// Opens path for binary writing. nullptr on failure.
std::FILE* open_for_write(const fs::path& path) {
#ifdef _WIN32
    std::FILE* f = nullptr;
    return _wfopen_s(&f, path.c_str(), L"wb") == 0 ? f : nullptr;
#else
    return std::fopen(path.c_str(), "wb");
#endif
}

// Pushes the OS cache for f to the disk. Returns false if the OS reports a failure.
bool sync_to_disk(std::FILE* f) {
#ifdef _WIN32
    return _commit(_fileno(f)) == 0;
#else
    return fsync(fileno(f)) == 0;
#endif
}

}  // namespace

fs::path path_from_utf8(const std::string& text) {
#if defined(__cpp_char8_t)
    return fs::path(std::u8string(text.begin(), text.end()));
#else
    return fs::u8path(text);
#endif
}

std::string path_to_utf8(const fs::path& path) {
#if defined(__cpp_char8_t)
    const std::u8string s = path.u8string();
    return std::string(s.begin(), s.end());
#else
    return path.u8string();
#endif
}

fs::path temp_path_for(const fs::path& target) {
    fs::path p = target;
    p += kTempSuffix;
    return p;
}

fs::path backup_path_for(const fs::path& target) {
    fs::path p = target;
    p += kBackupSuffix;
    return p;
}

std::optional<std::string> read_file(const fs::path& path, std::string* error) {
    set_error(error, "");
    std::error_code ec;
    if (!fs::exists(path, ec)) {
        return std::nullopt;  // never written: not an error
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        set_error(error, "cannot open " + path_to_utf8(path));
        return std::nullopt;
    }
    std::string bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (in.bad()) {
        set_error(error, "read failed: " + path_to_utf8(path));
        return std::nullopt;
    }
    return bytes;
}

bool write_temp(const fs::path& target, const std::string& bytes, std::string* error) {
    const fs::path tmp = temp_path_for(target);
    std::error_code ec;
    if (target.has_parent_path()) {
        fs::create_directories(target.parent_path(), ec);  // already there is fine; a real failure shows at open
    }
    std::FILE* f = open_for_write(tmp);
    if (!f) {
        set_error(error, "cannot create " + path_to_utf8(tmp));
        return false;
    }
    const bool written = std::fwrite(bytes.data(), 1, bytes.size(), f) == bytes.size();
    const bool flushed = written && std::fflush(f) == 0 && sync_to_disk(f);
    const bool closed = std::fclose(f) == 0;
    if (!(written && flushed && closed)) {
        fs::remove(tmp, ec);
        set_error(error, "write failed (disk full or removed?): " + path_to_utf8(tmp));
        return false;
    }
    return true;
}

bool commit_temp(const fs::path& target, std::string* error) {
    std::error_code ec;
    fs::rename(temp_path_for(target), target, ec);  // replaces an existing target (MoveFileExW REPLACE_EXISTING on MSVC)
    if (ec) {
        set_error(error, "cannot replace " + path_to_utf8(target) + ": " + ec.message());
        return false;
    }
    return true;
}

bool write_file_atomic(const fs::path& target, const std::string& bytes, std::string* error) {
    return write_temp(target, bytes, error) && commit_temp(target, error);
}

}  // namespace core

// {{FOOTER}}
