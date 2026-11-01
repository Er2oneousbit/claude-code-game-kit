# SOP-19: Front end, settings, saves, input and localization ("the shell")

## Goal
Everything around the game that players touch before and between play works the first time and every time: menus
that a gamepad can drive, settings that stick, saves that survive a crash and an update, controls players can change,
prompts that show the buttons they hold, text that fits in every language, and a crash that leaves a report behind.

Run it with `/game-shell`.

## 1. The shell's parts
Godot, LÖVE and web overlays ship a working shell; Unity, Unreal, Bevy and C++/SDL2 ship its engine-free logic with
tests (details per engine: `docs/ENGINE_FLOW.md`). The behavior is one spec, `tools/golden_vectors.py`, with expected
values in `data/golden/shell.json` that every port's tests check (K01).

| Part | What it gives |
|---|---|
| Screens | boot, title (press any key), main menu (Play, Settings, Credits, Quit), settings, credits, pause (on the pause action and on focus loss), loading with a progress bar |
| Settings | display (mode, vsync, frame cap, resolution, UI scale), audio per bus (Master, Music, SFX, UI, Voice, mono), language, accessibility (`SOP-20`), input (bindings, dead zone, invert Y, prompt style), telemetry consent |
| Saves | versioned slots with a migration chain, one backup, atomic writes, autosave hook |
| Input | actions, not keys; keyboard and gamepad defaults; rebinding with swap and conflict display; prompts that follow the last device |
| Localization | string tables per locale, a fallback chain, plurals, placeholders, a pseudo-locale smoke run |
| Logs and crashes | a log file per run (version on line one, five kept), a crash file with the version and the log tail, a bug-report key |
| Telemetry | off until the player says yes; local file only by default |

## 2. Settings
- One file, `settings.json`, in the platform's user-data folder. Load rules (the reference's `settings_load`):
  missing fields take defaults, a wrong type or an out-of-range value is fixed and logged, unknown keys are kept (so a
  newer build's file survives an older build), a file that does not parse gives defaults and a log line.
- Saved on Back or Apply, never on every slider tick. Apply display changes at once and offer a revert for anything
  that can black out the screen (resolution, fullscreen).
- Every setting is saved and restored (F37). Machine-specific settings (resolution, vsync) stay out of cloud sync
  (E79).

## 3. Saves (standard practice, proven by K01)
1. Every save is an envelope `{"format": "save", "version": N, "data": {...}}`. The version starts at 1 on day one
   (ARCHITECTURE.md) and goes up whenever the data's shape changes.
2. Each version change gets a migration function (version N to N+1) and a test that loads a real file from version N.
   Loading runs every migration in order.
3. A save from a newer version is never loaded and never overwritten: say "this save is from a newer version".
4. Write atomically: write `<file>.tmp`, flush, then replace the file with it (rename). Keep the previous good save as
   `<file>.bak`; if the main file does not parse, load the backup and say so.
5. Autosave at safe points (level start, checkpoint), never in the middle of a transition.

## 4. Input and prompts (A)
- Bind actions (`jump`, `ui_accept`), never raw keys in game code. Defaults for keyboard (slot 0) and gamepad
  (slot 1). Rebinding swaps within a group: two gameplay actions cannot share a key, but a menu action and a gameplay
  action can (`ui_accept` and `jump` on the same button is normal).
- The whole UI is reachable with the gameplay input: full gamepad navigation, a visible focus that is not colour
  alone, accept and cancel everywhere, cancel goes back one screen (F37).
- Prompts show the device in use: keyboard keys after a key press, the gamepad's buttons after a button press
  (`glyph_set`); on Steam Deck, keyboard glyphs while a controller is active fail the review (E75). The kit's prompt
  names (`glyph_name`): `key_space`, `mouse_left`, `xbox_a`, `ps_cross`, `pad_south`; art in `assets/ui/glyphs/`.
  Use generic shapes for button art, never platform logos. In Godot, Dotwork's `uikit` lane (drawn in code, no GPU)
  makes that whole set plus a Theme for every menu control in every state, focus a ring of its own colour (K01).
- Platform holders' certification may require their own button art from their SDKs; the generic set is for PC.

## 5. Localization (A)
1. Every visible string goes through `tr(key)` from `data/i18n/<locale>.json`; the fallback chain is the locale, its
   base language, then English, then the key itself (a missing string shows, so it gets noticed).
2. Plurals per CLDR category with one message per category, never "item(s)"; `one` does not mean only 1 (French puts
   0 in `one`) (E86). The kit's plural helper covers English-like, French and CJK rules; add a language's rule from
   the CLDR chart before shipping it.
3. Placeholders are named (`{name}`), never concatenated strings.
4. Run the pseudo-locale before any translation: accented look-alikes, padded by 40 % of the visible characters rounded up (placeholders
   such as `{name}` and `%d` neither change nor count, so short strings grow more), wrapped in brackets (F38). The
   pseudo smoke run (`dev.py smoke --drive pseudo --locale pseudo`) visits every screen and fails on a clipped or
   untranslated label. Use the reserved name only on the command line, never as a real locale code (E87).
5. Fonts must cover every character of every shipped language (E70); check before adding a language.

## 6. Display and platforms
- Pixel art: the kit's 640x360 base scales by whole numbers (2x at 720p, 3x at 1080p, 4x at 1440p); letterbox the rest
  and keep UI inside a safe area. Ultrawide: extend the view, never stretch it.
- Text: the smallest text body must be at least 18 px tall at 1080p on PC (6 px at the 640x360 base) and at least 9 px
  at 1280x800 on Steam Deck, 12 px recommended (F36). Scale UI and text to 200 % (`ui_scale`, `text_scale`).
- Focus loss pauses the game (and mutes it if the player chose that); alt-tab must not lose input or crash.
- Steam Deck review: controller works by default with no settings change, matching glyphs, 1280x800, the
  on-screen keyboard for text entry, no launcher, 30 fps at 800p (E75).

## 7. Logs, crashes and bug reports (standard practice)
- A log file per run (logs/game.log in the user-data folder), first line the game version and the date; keep the last five.
- An unhandled error writes `crashes/crash_<time>.txt` (version, seed if any, the error, the log tail) before the
  engine's own handler runs; in automated runs it exits non-zero so `dev.py smoke` fails.
- In debug builds a key (F8) bundles the log tail, settings and a screenshot into a folder the player can attach to
  the Bug issue form (`SOP-03`).

## 8. Telemetry (consent first)
Off until the player chooses Yes on a one-time question; No and Later write nothing. The kit's version appends events
to `telemetry.csv` on the player's machine and sends nothing. Before adding any upload, write the privacy policy
(`SOP-21` step 6): what is collected, why, for how long, and how to turn it off. `dev.py smoke --drive menus` with
consent unset must leave no telemetry file.

## Done when
- A gamepad alone gets through title, settings, play, pause and back; focus is always visible.
- Settings survive a restart; a hand-broken settings file gives defaults and a log line, not a crash.
- A save from every older version loads (migration tests); a corrupt save falls back to the backup.
- The pseudo-locale smoke passes; no label is clipped.
- A planted crash writes a crash file; the shell's tests pass against `data/golden/shell.json`.

## Common mistakes
- Saving by writing straight over the old file: a crash mid-write loses the player's progress.
- A save format with no version number, so the first update breaks every existing save.
- Mouse-only menus, or a focus highlight in colour alone.
- Keyboard glyphs on screen while the player holds a gamepad.
- Strings glued together from pieces ("You have " + n + " coins"): untranslatable. Use placeholders and plurals.
- Telemetry that starts before the player said yes.
