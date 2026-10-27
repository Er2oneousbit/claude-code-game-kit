# {{GAME_NAME}}

{{GAME_NAME}} is a game made with {{ENGINE_LABEL}}. One-line pitch lives in `docs/GDD.md`.

## Quick start
```
python tools/dev.py -h        # see every command and what it does
python tools/dev.py check     # fast sanity pass
python tools/dev.py test      # run tests
python tools/dev.py run       # launch the game
```
Engine-specific setup (install, versions, env vars): **`docs/ENGINE.md`**.

## For contributors and testers
1. Read `docs/ENGINE.md` for setup.
2. Run `python tools/dev.py doctor` (or `python tools/doctor.py`) to verify your environment.
3. Known problems and fixes: `docs/TROUBLESHOOTING.md`.
4. How we work: `docs/sop/`.

## Working with Claude Code
This repo is set up for Claude Code. Open it in the repo root and run `claude`.
- `CLAUDE.md` is loaded automatically. Skills in `.claude/skills/`, subagents in `.claude/agents/`.
- Start with `/start-session`, end with `/end-session`.
- Full guide: `docs/sop/SOP-07-claude-code-hygiene.md`.

## Layout
See `docs/ARCHITECTURE.md` and `docs/ENGINE.md`.

## Credits and licenses
Third-party assets and licenses: `docs/ASSET_LOG.md`.

<sub>Set up with the Claude Code Game Kit.</sub>
