# Adding a new engine (GameMaker, Love2D, Defold, Raylib, Roblox...)

Candidates and what each overlay would need: the "Not in the kit yet" table in `CHOOSING_AN_ENGINE.md`.

Copy this folder to `engines/<your-id>/` and fill it in. For files to start from, copy the closest shipped overlay instead
(`engines/godot` for a CLI-driven engine, `engines/cpp-sdl2` or `engines/bevy` for a code-only one) and adapt its `tools/dev.py`, which already
implements every rule below (including `hoist_global_options`, so options work before or after the command). The scaffolder picks it up automatically (`new_game.py --list-engines`).

## Required files
| File | Purpose |
|---|---|
| `engine.json` | Metadata, see fields below |
| `ENGINE.md` | Short, imported into the game's CLAUDE.md. Version, setup, layout, conventions, **Gotchas**, generated/binary files |
| `FLOW.md` | Long-form flow: daily loop, command mapping, tests, assets/audio, profiling, packaging, common errors |
| `gitignore.append` | Engine-specific ignores, appended to the universal `.gitignore` |
| `settings.patch.json` | Extra Claude Code permissions merged into `.claude/settings.json` (`allow`/`ask`/`deny` lists) |
| `skeleton/tools/dev.py` | **The command contract.** Implement `check test smoke build run clean doctor` (add extras if useful) |
| `skeleton/...` | Starter project files copied to the game root. Include one tiny testable unit and a boot marker |

## engine.json fields
```json
{
  "id": "myengine",
  "label": "Human readable name",
  "summary": "one line for --list-engines",
  "skeleton_dir": "skeleton",
  "gitignore_append": "gitignore.append",
  "settings_patch": "settings.patch.json",
  "engine_md": "ENGINE.md",
  "flow_md": "FLOW.md",
  "assets_dir": "assets",
  "adopt_hints": { "project.file": "what to merge from project.file.gold when adopting" }
}
```
`setup_step` is optional: one line printed as step 3 of the scaffolder's next steps instead of the generic "do the engine setup" line.
`adopt_hints` is optional: when `--adopt` writes a `.gold` copy of one of these files, the scaffolder prints the hint under the `[merge]` line.

## The command contract (every dev.py must honor)
| Command | Meaning | Exit codes |
|---|---|---|
| `check` | Fastest sanity pass (parse or compile) | 0 ok, 1 failed, 2 env problem |
| `test` | Unit tests | same |
| `smoke` | Boot headless for N frames, fail on errors | same |
| `build` | Full build or export. If the shippable artifact needs another command (Unreal `package`), document it in FLOW.md "Packaging" | same |
| `run` | Launch the game | same |
| `clean` | Remove build artifacts | same |
| `doctor` | Verify local environment, call `tools/doctor.py` | same |
Global `--debug`, `-h` help with env vars documented. Header comment names Claude and the model. Footer line included.

Rules every `dev.py` follows (the shipped ones do; check yours against them):
- **Exit 2, not 1, for anything that is not the code's fault:** missing or non-executable engine binary (and a folder or `.app`
  given instead of the binary), engine already open on the project, toolchain missing, path too long, and **nothing ran**
  (no tests matched, test framework missing). 1 means the code or content is broken.
- **Never a false pass:** parse output for proof that work happened (test counts, boot marker), because engines often exit 0 on errors.
- **Never hang:** a timeout on anything that runs the game or tests, `stdin=DEVNULL` on captured runs, bounded `--frames`.
- **`clean` checks** that the folder is really gone and reports locked files; it never deletes through a link or junction.
- **Prompts** only with a TTY and `--yes` to skip; a closed stdin exits 2.
- **Output:** UTF-8 stdout/stderr with replacement, line-buffered, flushed before child processes; `--debug` prints tracebacks
  but never changes the exit code.

## Placeholders available in all text files
`{{GAME_NAME}}` `{{GAME_SLUG}}` `{{ENGINE}}` `{{ENGINE_LABEL}}` `{{DATE}}` `{{AUTHOR}}`

## Checklist before calling it done
- [ ] `new_game.py --engine <id> --name "Test" --dest /tmp/x` succeeds
- [ ] `python tools/doctor.py` passes in the output
- [ ] Every command in `dev.py -h` works or exits 2 with a clear message
- [ ] ENGINE.md gotchas list is real, not filler. Mark unverified commands **(verify)**
