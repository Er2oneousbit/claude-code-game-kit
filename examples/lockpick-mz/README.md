# Lockpick MZ

A lockpicking minigame for RPG Maker MZ, as a pair of plugins: a pick sweeps across a bar, and you press OK while it is in
the green sweet spot to set each pin. Miss three times, or run out of time, and the lock jams. Events run it with one
Plugin Command and read the result from a switch. Made with the [Claude Code Game Kit](../../README.md) as its **RPG
Maker MZ example**: the rules are an engine-free plugin tested in Node, with a scenario pair (a careful player opens 40
of 40 locks, a key-masher 1); the MZ glue is a second plugin. Step by step: [HOW_IT_WAS_MADE.md](HOW_IT_WAS_MADE.md).

> **Untested proof of concept: never run in RPG Maker MZ.** Built without MZ installed: the rules, the bots and the glue were tested in Node and in
> a headless browser against stand-ins for MZ's classes, never against the real engine. Expect small fixes on the
> first real run, and read [HOW_IT_WAS_MADE.md](HOW_IT_WAS_MADE.md) "What is not verified".

## Play it
Needs RPG Maker MZ (yours: the kit does not ship it), Node.js 22.12+ and Python 3.8+.
1. In RPG Maker MZ: File > New Project, anywhere. It is only a source of MZ's own files.
2. In this folder:
   ```
   python tools/dev.py setup --from <that new project's folder>   # copies MZ's files into game/, registers the plugins
   python tools/dev.py run                                        # opens the game in your browser
   ```
3. On the title screen choose **Pick a lock**. Press OK (Enter, Z, Space or a tap) when the pick is in the green.

In your own game: copy `game/js/plugins/GameCore.js` and `GameMain.js` into your project's `js/plugins/`, turn both on in
the Plugin Manager (GameCore first), then in an event: Plugin Command > GameMain > **Open Lock** (pins, sweet spot %,
seed, result switch), followed by a Conditional Branch on that switch. Plugin parameter **Title demo** removes the title
command.

Browser flags: `?autoplay` (a careful bot picks the demo lock), `?autoplay=masher` (a bot that hammers the key).

## What to look at
| File | What it shows |
|---|---|
| `game/js/plugins/GameCore.js` | The rules and both bots, with no RPG Maker objects: the same file runs in Node and in MZ |
| `game/js/plugins/GameMain.js` | The MZ glue in MZ's own style: a prototype scene, aliased title hooks, a plugin command whose arguments arrive as strings |
| `tests/lockpick.test.js` | Rules tests and the scenario pair over 40 seeds, including sloppy copies of the careful player |
| `tests/gameMain.test.js`, `tests/support/mzFake.js` | The glue run against small stand-ins for MZ's classes |
| `tools/dev.py` | The kit's commands for MZ: `setup --from`, a `check` that compares plugin annotations with the code |

## Checks
```
python tools/dev.py check     # plugin syntax, annotations against registerCommand, database JSON, js/plugins.js
python tools/dev.py test      # 16 Node tests: rules, the bot pair, the glue against MZ stand-ins
python tools/dev.py smoke --query autoplay --until LOCK_OPEN --fail-on LOCK_JAMMED   # needs setup --from first
```

## Credits and licenses
- Code: the kit's MIT license. No third-party assets of its own.
- RPG Maker MZ (Gotcha Gotcha Games / KADOKAWA) supplies the engine, the window skin and the system sounds the scene
  uses (`SoundManager.playOk`, `playBuzzer`); they come from your MZ install by `setup --from` and are not in this repo.
