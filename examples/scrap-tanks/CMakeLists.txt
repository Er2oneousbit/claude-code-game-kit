# ---------------------------------------------------------------------------
# CMakeLists.txt
# Purpose : Build definition for Scrap Tanks (C++17 + SDL3).
# Usage   : cmake --preset debug && cmake --build --preset debug
#           (or just: python tools/dev.py check)
# Notes   : Explicit source lists (no file(GLOB)) so adds/removes show up in diffs.
#           Layering: `core` (no SDL) <- `game_lib` (SDL) <- exe. Tests link `core` only.
#           Dependencies come from vcpkg.json via the toolchain file in CMakePresets.json.
#           The kit's golden-vector tests read data/golden/*.json through the GOLDEN_DIR definition.
#           Every build copies data/ (without golden/ and shaders/) next to the exe (game_data); the sprites, font
#           and sounds are found in assets/ from the working directory or the exe's folder (src/game/Assets.cpp).
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): the kit's juice and shell logic in core
#           (nlohmann-json), its golden-vector and file tests
# Updated : 2026-11-06 with Claude (Opus 5.5, claude-opus-5-5): SDL3 and SDL3_image/ttf/mixer (was SDL2), the kit's
#           shader recipes compiled with shadercross, src/gfx (KitShaders), the kit_shader_check tool
# Updated : 2026-11-10 with Claude (Fable 5.1, claude-fable-5-1): the kit's shell screens (#168): Menu and ShellLogic in
#           core, src/shell in game_lib, tests/test_menu.cpp
# Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): kit 0.14.4: Report (crash files), JuiceDemo, the analog,
#           motor-access and report tests, the game_data target (data/ next to the exe)
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.21)
project(scrap_tanks VERSION 0.2.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUILD_TESTS "Build unit tests" ON)
option(ENABLE_SANITIZERS "Enable ASan/UBSan (GCC/Clang only)" OFF)

# Single output folder for executables. Multi-config generators add a Debug/Release subfolder.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# ---- Warnings (applied via an interface target so every target gets them) ----
add_library(project_warnings INTERFACE)
if(MSVC)
  # /utf-8: sources (and the footer emoji) are UTF-8; without it MSVC on CJK code pages warns C4819 and garbles names
  target_compile_options(project_warnings INTERFACE /W4 /permissive- /utf-8)
else()
  target_compile_options(project_warnings INTERFACE -Wall -Wextra -Wpedantic)
  if(ENABLE_SANITIZERS)
    target_compile_options(project_warnings INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(project_warnings INTERFACE -fsanitize=address,undefined)
  endif()
endif()

# ---- core: SDL-free simulation, AI and bots, unit tested (the whole fight runs in tests) ----
# The kit's juice headers and shell logic (settings, saves, bindings, i18n, the menus) live here too; the shell's
# screens (src/shell) use them, the golden-vector and menu tests keep them honest.
find_package(nlohmann_json CONFIG REQUIRED)

add_library(core STATIC
  src/core/Nav.cpp
  src/core/Sim.cpp
  src/core/Tactics.cpp
  src/core/EnemyBrain.cpp
  src/core/Bot.cpp
  src/core/AtomicFile.cpp
  src/core/Bindings.cpp
  src/core/I18n.cpp
  src/core/Menu.cpp
  src/core/Report.cpp
  src/core/SaveStore.cpp
  src/core/Settings.cpp
  src/core/ShellLogic.cpp
)
target_include_directories(core PUBLIC ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(core PUBLIC project_warnings nlohmann_json::nlohmann_json)
# One source of truth for the version (SOP-06): project(... VERSION) above, readable in code as GAME_VERSION
target_compile_definitions(core PUBLIC GAME_VERSION="${PROJECT_VERSION}")

# ---- game_lib: gameplay code that talks to SDL ----
find_package(SDL3 CONFIG REQUIRED)
# SDL companion libraries for PNG sprites, the HUD font and WAV sounds (docs/adr/0001-sdl-companion-libraries.md)
find_package(SDL3_image CONFIG REQUIRED)
find_package(SDL3_ttf CONFIG REQUIRED)
find_package(SDL3_mixer CONFIG REQUIRED)

set(GAME_SOURCES
  src/game/Game.cpp
  src/game/Assets.cpp
  src/gfx/KitShaders.cpp
  src/shell/Draw.cpp
  src/shell/Drive.cpp
  src/shell/JuiceDemo.cpp
  src/shell/Shell.cpp
)
add_library(game_lib STATIC ${GAME_SOURCES})
target_link_libraries(game_lib PUBLIC core SDL3::SDL3 SDL3_image::SDL3_image SDL3_ttf::SDL3_ttf
  SDL3_mixer::SDL3_mixer)
target_include_directories(game_lib PUBLIC ${CMAKE_SOURCE_DIR}/shaders/kit)   # kit_shaders.hpp

# ---- the kit's shader recipes: HLSL -> SPIR-V, DXIL, MSL with shadercross (vcpkg host tool) ----
include(${CMAKE_SOURCE_DIR}/shaders/kit/kit_shaders.cmake)   # KIT_SHADER_NAMES (generated)
find_program(SHADERCROSS shadercross
  HINTS "${VCPKG_INSTALLED_DIR}/${VCPKG_HOST_TRIPLET}/tools/sdl3-shadercross" REQUIRED)
set(KIT_SHADER_OUT ${CMAKE_BINARY_DIR}/shaders/kit)
set(KIT_SHADER_FILES)
foreach(name IN LISTS KIT_SHADER_NAMES)
  set(src ${CMAKE_SOURCE_DIR}/shaders/kit/${name}.frag.hlsl)
  foreach(pair "SPIRV;spv" "DXIL;dxil" "MSL;msl")
    list(GET pair 0 format)
    list(GET pair 1 ext)
    set(out ${KIT_SHADER_OUT}/${name}.frag.${ext})
    add_custom_command(OUTPUT ${out}
      COMMAND ${CMAKE_COMMAND} -E make_directory ${KIT_SHADER_OUT}
      COMMAND ${SHADERCROSS} ${src} -s HLSL -d ${format} -t fragment -e main -o ${out}
      DEPENDS ${src}
      COMMENT "shader ${name} -> ${format}"
      VERBATIM)
    list(APPEND KIT_SHADER_FILES ${out})
  endforeach()
endforeach()
add_custom_target(kit_shaders ALL DEPENDS ${KIT_SHADER_FILES})

# Copies the compiled recipes next to an executable target (shaders/kit/), so a shipped build finds them
function(copy_kit_shaders target)
  add_dependencies(${target} kit_shaders)
  add_custom_command(TARGET ${target} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${KIT_SHADER_OUT} $<TARGET_FILE_DIR:${target}>/shaders/kit
    VERBATIM)
endfunction()


# ---- executable ----
add_executable(scrap_tanks src/main.cpp)
# Release on Windows: a GUI-subsystem exe, so the shipped game does not open a console window.
# Debug keeps the console for logs and for dev.py smoke, which reads stdout.
set_target_properties(scrap_tanks PROPERTIES WIN32_EXECUTABLE $<CONFIG:Release>)
target_link_libraries(scrap_tanks PRIVATE game_lib)
copy_kit_shaders(scrap_tanks)

# ---- the game's data next to the exe: data/ (minus the kit's test folders) and CREDITS.md ----
# The shell reads them from the working directory when it has data/, else from the exe's folder, so a shipped
# build started from anywhere finds its strings, presets, colours and dialogue. A custom target runs on every
# build (a POST_BUILD step would only run when the exe relinks), so an edit to data/ alone is copied too.
add_custom_target(game_data ALL
  COMMAND ${CMAKE_COMMAND} -DSRC=${CMAKE_SOURCE_DIR} -DDST=$<TARGET_FILE_DIR:scrap_tanks>
          -P ${CMAKE_SOURCE_DIR}/cmake/copy_game_data.cmake
  COMMENT "game data -> next to the exe"
  VERBATIM)

# ---- kit_shader_check: draws every recipe for `dev.py smoke --shaders` (a kit tool, not shipped) ----
add_executable(kit_shader_check src/tools/kit_shader_check.cpp)
target_link_libraries(kit_shader_check PRIVATE game_lib)
target_compile_definitions(kit_shader_check PRIVATE KIT_INPUT_DIR="${CMAKE_SOURCE_DIR}/data/shaders/inputs")
copy_kit_shaders(kit_shader_check)

# ---- tests ----
if(BUILD_TESTS)
  enable_testing()
  find_package(doctest CONFIG REQUIRED)
  add_executable(unit_tests
    tests/test_main.cpp
    tests/test_analog.cpp
    tests/test_fixed_timestep.cpp
    tests/test_math_geom.cpp
    tests/test_nav.cpp
    tests/test_bt.cpp
    tests/test_arena.cpp
    tests/test_sim.cpp
    tests/test_brain.cpp
    tests/test_view.cpp
    tests/test_scenario.cpp
    tests/test_regressions.cpp
    tests/test_golden_vectors.cpp
    tests/test_golden_audio.cpp
    tests/test_menu.cpp
    tests/test_motor_access.cpp
    tests/test_reports.cpp
    tests/test_shell_files.cpp
  )
  target_link_libraries(unit_tests PRIVATE core doctest::doctest)
  # The kit's golden vectors (reference: tools/golden_vectors.py). Override with -DGOLDEN_DIR=<folder>.
  set(GOLDEN_DIR "${CMAKE_SOURCE_DIR}/data/golden" CACHE PATH "Folder holding the golden vector files")
  target_compile_definitions(unit_tests PRIVATE GOLDEN_DIR="${GOLDEN_DIR}")
  add_test(NAME unit_tests COMMAND unit_tests)
endif()
