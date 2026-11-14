// ---------------------------------------------------------------------------
// test_capture_format.cpp
// Purpose : Unit tests for core::capture_format_of (#314): the format a --screenshot name asks for.
// Usage   : python tools/dev.py test
// Notes   : Before #314 every capture was BMP bytes, so a .png name held a BMP; the name now picks the format.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include <doctest/doctest.h>

#include "core/CaptureFormat.hpp"

using core::CaptureFormat;
using core::capture_format_of;

TEST_CASE("capture format: .png is PNG and .bmp is BMP, in any letter case") {
    CHECK(capture_format_of("captures/a.png") == CaptureFormat::png);
    CHECK(capture_format_of("C:\\shots\\A.PNG") == CaptureFormat::png);
    CHECK(capture_format_of("captures/b.bmp") == CaptureFormat::bmp);
    CHECK(capture_format_of("b.Bmp") == CaptureFormat::bmp);
    CHECK(capture_format_of("my.shots/frame_000004.png") == CaptureFormat::png);
}

TEST_CASE("capture format: any other extension, or none, is refused") {
    CHECK(capture_format_of("captures/a.jpg") == CaptureFormat::unknown);
    CHECK(capture_format_of("captures/a.png.txt") == CaptureFormat::unknown);
    CHECK(capture_format_of("captures/shot") == CaptureFormat::unknown);
    CHECK(capture_format_of("captures/shot.") == CaptureFormat::unknown);
    CHECK(capture_format_of("my.png/shot") == CaptureFormat::unknown);   // the dot is in a folder name
    CHECK(capture_format_of("") == CaptureFormat::unknown);
}
