# SOP-05: Git

## Goal
Safe history, easy rollback, no binary bloat, no leaked secrets.

## Rules
- `main` is always buildable. Work on `feat/<name>`, `fix/<name>`, `chore/<name>` branches.
- Small commits, one idea each. Message: `type(scope): summary` plus a body explaining why.
- Claude does not commit, push, or tag unless asked. When asked, show `git status` and `git diff --stat` first.
- Never commit: build output, engine cache folders (see `.gitignore`), `.env`, keys, platform signing files.
- **Several agents in one working tree** (tip, E54): each stages its own files by name (never `git add -A` or `git add .`),
  and none stashes, hard-resets or deletes worktrees in the shared tree: one game lost other agents' commits to a stale index
  and its shared `node_modules` to a worktree removal. Simpler: give each parallel agent its own git worktree.
- Large binaries (art source, audio masters, 3D, Unreal assets): use Git LFS. Every scaffolded project ships a `.gitattributes`
  that routes images, audio, video, fonts and 3D files through LFS; run `git lfs install` once per machine before the first commit.
- Tags for builds: `vMAJOR.MINOR.PATCH`, plus `playtest-YYYYMMDD` for tester builds. What each number means and when to bump it: SOP-06 "Versioning".

Putting the repo on GitHub (license, secret scan, lock-down settings): `SOP-13`.

## Before committing
1. `python tools/dev.py check` and `test` pass.
2. No `PROTOTYPE:` hacks sneaking into `main`.
3. `ROADMAP.md` and `HANDOFF.md` reflect reality (if end of session).

## Recovery cheat sheet
| Situation | Command |
|---|---|
| Undo last commit, keep changes | `git reset --soft HEAD~1` |
| Discard local changes to one file | `git restore <file>` |
| See what changed | `git diff`, `git diff --staged` |
| Find which commit broke it | `git bisect start`, mark good/bad, repeat |
| Rescue a lost commit | `git reflog` |

## Done when
- `main` builds, history explains itself, no secrets or cache folders tracked, LFS covers large binaries.

## Common mistakes
- Committing the engine cache folder (huge, useless).
- Committing without LFS then trying to fix history later. Set up LFS first.
- Force-pushing shared branches.
