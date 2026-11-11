# SOP-20: Accessibility

## Goal
More people can play, and nobody gets hurt: players who cannot hear, see colour, read small text, hold buttons, react
fast or handle motion and flashes can still finish the game. Most of it is cheap when it is planned from the start and
expensive when it is bolted on at the end.

Sources: the Game Accessibility Guidelines (E69) and the Xbox Accessibility Guidelines (E70 to E73), with the flash rule
from WCAG (E74). Both guideline sets are written as best practice, not as legal compliance checklists.

## 1. The baseline every kit game ships (A)
The shell (`SOP-19`) has the settings; this SOP is what they must do.

| Need | Rule | Shell setting | Source |
|---|---|---|---|
| Subtitles | On by default (or chosen before any sound plays), every important line, speaker named when it changes, at most two lines of about 40 characters, a solid background with adjustable opacity, size up to 200 % | `access.subtitles`, `subtitle_size`, `subtitle_background`, `speaker_names` | F35 |
| Captions | Important sounds that are not shown on screen get a caption, with a direction arrow when the source is off-screen; barks and ambient captions can be turned on and off apart from dialogue | `captions_sfx`, `subtitle_barks` | F35 |
| Text | Smallest body text 18 px at 1080p on PC, 9 px at 1280x800 on Steam Deck (12 recommended); scalable to 200 % | `text_scale`, `display.ui_scale` | F36 |
| Colour | No information by colour alone (add a shape, icon or label); text at least 4.5:1 against its background (3:1 when large); a colour-blind option where colour carries meaning, and the pairs that matter (player vs enemy, hazard vs floor) declared in `data/access/colours.json` and kept apart for protan, deutan and tritan players (`python tools/access/colour_check.py pairs`) | `colorblind` | E69, E157, E158 |
| Controls | Every action remappable; the whole UI reachable with the gameplay input; no required button holds (toggle option); separate volume per bus and a mono switch | `input.bindings`, `hold_to_toggle`, `audio.*`, `audio.mono` | F37, E69 |
| Motion | Shake, bob and full-screen effects can be turned off (an intensity slider, as in the guideline's examples); reduce motion turns them off; nothing auto-scrolls without a way to pause it | `shake_scale`, `reduce_motion` | F33 |
| Flashes | At most three full-screen flashes in any one second, or below the thresholds; remove triggers rather than warn. The limiter is always on; the setting only makes flashes gentler | `flash_limit` (on by default: tones flashes down) | F34 |
| Difficulty | A wide choice of difficulty, changeable during play; assist options where the game allows (slower game speed, more health, skip a section) | `difficulty`, `game_speed` | E69 |
| Saving | Settings always saved; autosave plus manual save | (shell) | E69 |
| Keeping track | A reminder of the current goal during play; every line said can be read again; text waits for the player instead of leaving on a timer; an easily readable font as an option | "What now?" and "Dialogue history" on the pause menu (the game calls `set_objective`), `subtitle_hold`, `readable_font` (Atkinson Hyperlegible), `line_spacing` | E69 |
| Narration | Every menu control, value and screen says what it is ("Music volume, slider, 70 percent"); no control is unlabelled; a screen reader can follow the menus | `narration` (spoken through the system's speech; the web page always updates an ARIA live region) | E69 |
| Hands and timing | Controls as simple as possible: no required button-mashing, no required holds, timing that is not precise; a layout for one hand (the kit's take on simpler controls: no guideline names it) | `auto_repeat` (a held button repeats), `hold_to_toggle`, `timing_scale` (input buffer and coyote time, longer), one-handed layouts in Settings > Controls (`data/input/presets.json`) | E69 |

## 2. Steps
1. **At the GDD stage**, note which of the needs above the game touches (a rhythm game leans on audio, a puzzle game on
   colour) and how each pillar can still be met with the option on. Record it in `docs/GDD.md`.
2. **Use the shell's settings from the first menu**, not after the vertical slice. Every new mechanic asks: does it
   rely on hearing, colour, timing, holding, reading speed or motion? If so, add the alternative with it.
3. **Write captions as you add sounds**: an important sound gets an entry in the captions table when it is created
   (the captions table in the audio tools' dialogue.json, `docs/resources/audio.md`).
4. **Check flashes and motion** on every effect: route flashes through the flash limiter (`SOP-18`), test the effect with
   reduce motion on. Record a burst (`dev.py smoke --record`) and count flashes per second for anything bright; that is
   the first check, not proof. Bright, red or striped effects that stay in the game get a flash analysis tool run on a
   recording before release (E73, E74), or are softened until they need none.
5. **Check the colour pairs** whenever a palette changes: `python tools/access/colour_check.py pairs` simulates each pair as a protanope, deuteranope and tritanope sees it, in the palette the colour-blind setting switches to, and fails a pair that comes too close (CIEDE2000, E159). The pass mark is the file's `min_delta_e`: no published rule sets one for game art, so the kit's 20 is a tip; raise it if colour-blind playtesters still mix a pair up. `colour_check.py image <screenshot>` writes the picture as each player sees it, for a look.
6. **Run the sweep** on the engines with the shell's screens (Godot, LÖVE, web, web-3d, Unity, Unreal, Bevy, C++/SDL3): `python tools/access/sweep.py` drives every screen
   at 1920x1080 and at 1280x800 (gamepad only), at 100 % and 200 % text, and fails text under 18 px at 1080p or 9 px
   at 1280x800 (F36), text under 4.5:1 against what is behind it (3:1 for large text, E158; text over the game is
   checked against its panel or outline over both a black and a white game), text clipped, off screen or running
   into other text, a control the arrow keys or the gamepad cannot reach, focus that looks like hover, an action
   with no keyboard or no gamepad binding, a subtitle that is not the dialogue line, and keyboard glyphs while the
   gamepad is in use (E75), and a control whose narration would be "unlabelled" (#165). It reads what the engine
   reports (`dev.py smoke --drive access`), so how a screen
   looks still needs a look (`smoke --drive show:<screen> --screenshot`). Each run's settings go to a fresh
   `captures/access/<run>/`, never under `build/` (on Windows and macOS that is Unity's player folder `Build/`); every
   `dev.py smoke` refuses a `--data-dir` inside its player or build output. The game's output stays there too
   (`smoke.log`), with the last frame drawn (`last.png`, `last.bmp` on C++/SDL3) on the engines that capture during
   a drive (Bevy, C++/SDL3, LÖVE, web, web-3d); a failed run prints where they are. A drive reads no real keyboard, mouse or
   gamepad, so a stray key or a virtual pad on a shared machine cannot change the tour (#276).
7. **Test with the settings at their extremes:** text 200 %, subtitles largest with full background, colour-blind modes,
   gamepad only, keyboard only, mono, reduce motion. Run the pseudo-locale smoke at text 200 % too: it catches clipping.
   For mono, `python tools/audio/wavesmith/wavesmith.py loudness mono <stereo files>` finds sounds that cancel out when summed (K01).
8. **Playtest with the players it is for** when you can, and ask one question (SOP-03): could you finish it?
9. **Describe it on the store page**: list the options; players look for them.

## 3. Notes
- Many colour-blind players can tell red and green apart by brightness: a shape or label is still the fix that works for
  everyone (standard practice).
- Swap the palette of the important colours rather than filter the whole screen. The kit's full-screen colour-blind filter (daltonization, the `colorblind` shader) pulled the Godot demo's player and box closer together for protan and deutan players (CIEDE2000 22.3 to 12.5 and 24.3 to 7.0, K01), so the shells swap palettes and the filter runs only when `colours.json` sets `"filter": true`.
- A photosensitivity warning screen does not replace removing the trigger (E73 says removal is preferred).

## Done when
- Every row in step 1 is met or the GDD says why it does not apply.
- A full playthrough works with gamepad only and with keyboard only, with subtitles at the largest size, text at 200 %
  and reduce motion on.
- No effect breaks the flash rule; the release check (`/release-check`) lists the accessibility options.

## Common mistakes
- Subtitles off by default, or only for cutscenes and not for in-game lines.
- Red and green as the only difference between good and bad.
- Holding a button for a long action with no toggle.
- Shake and flashes with no off switch. For some players that is the difference between playing and being hurt.
- Text that looks fine on a 27-inch monitor and is unreadable on a Steam Deck.
