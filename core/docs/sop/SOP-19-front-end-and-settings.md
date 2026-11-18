# SOP-19: Front end, settings, saves, input and localization ("the shell")

## Goal
Everything around the game that players touch before and between play works the first time and every time: menus
that a gamepad can drive, settings that stick, saves that survive a crash and an update, controls players can change,
prompts that show the buttons they hold, text that fits in every language, and a crash that leaves a report behind.

Run it with `/game-shell`.

## 1. The shell's parts
Godot, LÖVE, web, web-3d, Unity, Unreal, Bevy and C++/SDL3 overlays ship a working shell, each with crash files, the
bug report key, the juice demo, the pseudo-locale drive and analog input for the game (web-3d runs web's shell over
Three.js); RPG Maker MZ keeps MZ's own screens, settings and saves, ships the shell's rules as the GameShell plugin
(the same golden vectors) and puts the accessibility settings that fit onto MZ's Options screen (GameAccess) (details per engine: `docs/ENGINE_FLOW.md`). The behavior is one spec, `tools/golden_vectors.py`, with expected
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
- Saved on Back or Apply, never on every slider tick. Audio, accessibility and the other tabs apply as the player
  moves a control, so a change is heard and seen while sliding. Display changes wait for an Apply button (the
  reference's `DisplayStaging`, held by the `display_staging` cases): the controls show the staged value, Apply sends
  only the changed fields (mode before resolution), and a change that can black out the screen (mode, resolution)
  asks "Keep these display settings? Reverting in N s" for 15 seconds of real time, never game time, with focus on
  Keep. Revert, the countdown, Back or cancel put back exactly what that Apply replaced. Such a change is saved only
  once kept: while the confirm is open settings.json (and an engine's own copy, such as Unreal's GameUserSettings.ini)
  keeps the old values, so a game killed on a black screen starts as before; Keep saves, a revert saves the old values.
  Back with unapplied Display changes warns once, and the warning stays up while the next Back would discard them;
  that second Back discards them. The Display tab says so in a hint line, and the resolution row
  says it sets the window size. `smoke --drive display` runs the whole path headless.
- Every setting is saved and restored (F37). Machine-specific settings (resolution, vsync) stay out of cloud sync
  (E79).
- Content switches (`content` section, rows on the Accessibility tab): `content.blood` (on by default; the game's
  blood effects, `blood_enabled(settings)`, SOP-18 section 3) and `content.clean_language` (off by default: text as
  written; section 5 step 8). Both load like any other field (a file from before them gets the defaults). A game
  with no blood or no strong language hides the row with `SHOW_BLOOD_SETTING` or `SHOW_LANGUAGE_SETTING` = false, so
  no switch does nothing.

## 3. Saves (standard practice, proven by K01)
1. Every save is an envelope `{"format": "save", "version": N, "data": {...}}`. The version starts at 1 on day one
   (ARCHITECTURE.md) and goes up whenever the data's shape changes.
2. Each version change gets a migration function (version N to N+1) and a test that loads a real file from version N.
   Loading runs every migration in order.
3. A save from a newer version is never loaded and never overwritten: say "this save is from a newer version". That
   holds for the backup too: while `<file>` or `<file>.bak` holds a newer save, every write to the slot is refused.
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
   0 in `one`) (E86). The kit's plural helper (`plural(locale, n)`, the reference's `PLURAL_FAMILIES`) has CLDR 46's
   whole-number rules for 77 languages and European Portuguese, Russian, Polish, Czech, Arabic and Welsh among them
   (K01: swept over 0 to 2000 and the millions against CLDR's own rules file; `CLDR_PLURALS_XML=<plurals.xml>
   python tools/test_golden_vectors.py` repeats the sweep); a language it does not list gets English's rule, so add its rule
   to `tools/golden_vectors.py` and every port before shipping it. Each locale in the fallback chain uses its own
   rule, and a table without the form asked for shows its `.other` (a missing French `many`, used only for whole
   millions, is fine).
3. Placeholders are named (`{name}`), never concatenated strings.
4. Run the pseudo-locale before any translation: accented look-alikes, padded by 40 % of the visible characters rounded up (placeholders
   such as `{name}` and `%d` neither change nor count, so short strings grow more), wrapped in brackets (F38). The
   pseudo smoke run (`dev.py smoke --drive pseudo --locale pseudo`) visits every screen and fails on a clipped or
   untranslated label. Use the reserved name only on the command line, never as a real locale code (E87).
5. Fonts must cover every character of every shipped language (E70); check before adding a language (Dotwork's
   `fonts-check` lists every character the game's strings use that a font lacks; `tools/i18n/l10n.py check` reads
   the game's TrueType and OpenType fonts too). The kit's shell font, Atkinson Hyperlegible, has no Cyrillic, Greek
   letters or CJK (K01): a Russian or Ukrainian table needs another font, or Dotwork's
   `tools/art/dotwork/glyphs/dialogue_cyrillic.txt`.
6. Machine or local-model translations are drafts: a draft keeps exactly the source's placeholders or is rejected,
   and a person reviews it before it ships, with a native reader for languages far from English (K01: a local
   model invented placeholders in its drafts; `docs/resources/audio.md`, "Translations and bark lines").
   `python tools/i18n/l10n.py` runs the round trip: `export <LANG>` writes `l10n/<LANG>.xlf` (XLIFF 1.2, or
   `--format csv`) with each line's context note and length budget (from context.json in the same folder: your
   notes and limits), and the plural forms the language needs that English lacks; `draft <LANG>` asks a model on this machine (LM Studio, llama.cpp or
   Ollama through their OpenAI-compatible server, or any `--command`) and rejects a draft that changes a
   placeholder, echoes the string id or answers in markup; `review <LANG>` accepts, fixes or rejects each draft;
   `import <LANG>` writes only reviewed lines into `data/i18n/<LANG>.json`, in en.json's layout, and refuses a line
   whose placeholders differ, that overruns its budget, whose English changed since export, or a file that lost
   lines; `check` runs the placeholder, plural, length and font checks over every table and the pseudo-locale (K01).
7. Before you call a language done, `python tools/check_i18n.py --locale <LANG>` lists every English key the table
   lacks, still has in English, or has with other placeholders (proper names and units pass; add your own with
   `--same`). A partial table is fine while you work: missing keys fall back to English.
8. Clean language (#207; the reference's `tr` with `clean`, `mask_words`): a line with strong language gets a
   sibling `<key>@clean` in the same table (`guard.insult@clean`; plurals `hits.one@clean`), and `@` is reserved for
   it. With `content.clean_language` on, each locale of the chain is asked for `@clean`, then the plain line, before
   the next locale, so the player's language always wins. Then the filled text, player names and other placeholder
   values included, is masked with the game's word list (`data/i18n/mature/<locale>.json`, `{"words": [...]}`, the
   files of every locale in the chain; the kit ships an empty English list): each whole listed word, in any case,
   becomes a same-length grawlix (`#@$%`). Limits: the mask matches whole words only, so a run of Chinese or Japanese
   characters with no spaces is one word, and a German compound must be listed as itself; text is not normalized.
   `check_i18n.py` lists every line that holds a listed word and has no `@clean` (a warning). Not filtered yet:
   dialogue files (subtitles, Wavesmith `dialogue`) do not go through `tr()`. A voiced line will need its own clean
   line and recording, chosen when the line starts, never swapped halfway.

## 6. Display and platforms
- Pixel art: the kit's 640x360 base scales by whole numbers (2x at 720p, 3x at 1080p, 4x at 1440p); letterbox the rest
  and keep UI inside a safe area. Ultrawide: extend the view, never stretch it.
- Text: the smallest text body must be at least 18 px tall at 1080p on PC (6 px at the 640x360 base) and at least 9 px
  at 1280x800 on Steam Deck, 12 px recommended (F36). Scale UI and text to 200 % (`ui_scale`, `text_scale`).
- Game HUDs too: a HUD the game draws itself (its own layer, canvas or scene) does not inherit the menus' scaling, so
  every HUD label takes its size from the engine's HUD font helper (base size times `text_scale` times `ui_scale`)
  and sets it again when those settings change. `docs/ENGINE_FLOW.md` (or `docs/ENGINE.md`) names the helper; the
  starter's play screen uses it.
- Focus loss pauses the game (and mutes it if the player chose that); alt-tab must not lose input or crash.
- Steam Deck review: controller works by default with no settings change, matching glyphs, 1280x800, the
  on-screen keyboard for text entry, no launcher, 30 fps at 800p (E75). `python tools/access/sweep.py --runs deck`
  checks what a program can on the shell's screens: every screen reached and left with gamepad events only at
  1280x800, no keyboard glyphs while the gamepad is in use, text at least 9 px (a warning under 12). A real Deck is
  still the check for Proton, the on-screen keyboard when text is typed, suspend and resume, and 30 fps
  **(verify against Valve's current Deck Verified criteria)**.

## 7. Logs, crashes and bug reports (standard practice)
- A log file per run (logs/game.log in the user-data folder), first line the game version and the date; keep the last five.
- An unhandled error writes `crashes/crash_<time>.txt` (version, seed if any, the error, the log tail) before the
  engine's own handler runs; in automated runs it exits non-zero so `dev.py smoke` fails.
- In debug builds a key (F8) bundles the log tail, settings and a screenshot into a folder the player can attach to
  the Bug issue form (`SOP-03`), after checking it for user names, local paths and anything private (issues are public).

## 8. Telemetry (consent first)
Off until the player chooses Yes on a one-time question; No and Later write nothing. The kit's version appends events
to `telemetry.csv` on the player's machine and sends nothing. Every engine writes the same columns,
`time,session,event,detail` (UTC time in whole seconds, a random 8-digit hex id per launch), checked against
`data/golden/telemetry.json`, so one analysis script reads any port's file. Before adding any upload, write the
privacy policy (`SOP-21` step 6): what is collected, why, for how long, and how to turn it off.
`dev.py smoke --drive menus` with consent unset must leave no telemetry file.

## Done when
- A gamepad alone gets through title, settings, play, pause and back; focus is always visible.
- Settings survive a restart; a hand-broken settings file gives defaults and a log line, not a crash.
- A save from every older version loads (migration tests); a corrupt save falls back to the backup.
- The pseudo-locale smoke passes; no label is clipped.
- Every shipped language passes `tools/check_i18n.py`.
- A planted crash writes a crash file; the shell's tests pass against `data/golden/shell.json`.

## Common mistakes
- Saving by writing straight over the old file: a crash mid-write loses the player's progress.
- A save format with no version number, so the first update breaks every existing save.
- Mouse-only menus, or a focus highlight in colour alone.
- Keyboard glyphs on screen while the player holds a gamepad.
- Strings glued together from pieces ("You have " + n + " coins"): untranslatable. Use placeholders and plurals.
- Telemetry that starts before the player said yes.
