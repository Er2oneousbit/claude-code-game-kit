# ---------------------------------------------------------------------------
# copy_game_data.cmake
# Purpose : Copies the game's runtime data next to the exe: data/ (string tables, dialogue, input presets, colours
#           and whatever the game adds) without the kit's test folders, and CREDITS.md when there is one. A shipped
#           build is that folder, so the shell finds its files from any working directory (Shell::game_dir()).
# Usage   : cmake -DSRC=<project root> -DDST=<the exe's folder> -P cmake/copy_game_data.cmake
#           (CMakeLists.txt runs it on every build, through the game_data target)
# Notes   : DST/data is cleared first, so a file deleted from data/ does not linger in the build. The folders in
#           SKIP are for the tests and tools only (golden vectors, shader check inputs) and never ship.
#
# Pseudocode:
#   remove DST/data -> for each entry directly under SRC/data: skip SKIP names, copy the rest into DST/data
#     -> CREDITS.md into DST when it exists
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.21)

# ---- Tunables ----
set(SKIP golden shaders)   # data/ subfolders that stay out of the build

if(NOT SRC OR NOT DST)
  message(FATAL_ERROR "copy_game_data.cmake needs -DSRC=<project root> -DDST=<exe folder>")
endif()

file(REMOVE_RECURSE "${DST}/data")
file(MAKE_DIRECTORY "${DST}/data")
file(GLOB entries LIST_DIRECTORIES true "${SRC}/data/*")
foreach(entry IN LISTS entries)
  get_filename_component(name "${entry}" NAME)
  if(NOT name IN_LIST SKIP)
    file(COPY "${entry}" DESTINATION "${DST}/data")
  endif()
endforeach()

if(EXISTS "${SRC}/CREDITS.md")
  file(COPY "${SRC}/CREDITS.md" DESTINATION "${DST}")
endif()
