# Profiles: your name, your footer, your house style

A profile is a small JSON file that `new_game.py --profile <file>` applies to a new game. Without one the kit uses
`default.json`: no author name, no footer line, and the neutral working style in the game's `CLAUDE.md`.

| Field | Goes into | Example |
|---|---|---|
| `author` | `CLAUDE.md` ("Owner: ...", "how <author> wants Claude to behave"); file headers credit Claude and the model only | `"Ada"` (empty: your `git config user.name`, else "the owner") |
| `footer` | last line of every starter source file, as a comment; `docs/STYLE.md` asks Claude to keep adding it | `"Made by Ada Studio"` (empty: no footer) |
| `style` | extra bullets under "Working style" in the game's `CLAUDE.md` | `["**Tone:** formal, no jokes."]` |

`example.json` is a filled-in example to copy.

```
python scripts/new_game.py --name "My Game" --engine godot --dest D:/games/my_game --profile profiles/mine.json
```
The profile is recorded in the game's `.game-kit.json`, so a later `--upgrade` renders the same way. `--author` overrides
the profile's author. The kit's own tools (`tools/*.py`, `dev.py`) carry no footer and no author either way.
