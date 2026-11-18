# Platform services: achievements, stats, presence, overlay, cloud saves

The kit's engine-neutral layer between a game and a store's SDK (Steam first). The game calls the layer; the layer
keeps the rules and talks to a **backend**. Every game runs the **null backend** by default, so `check`, `test` and
`smoke` never need Steam. A store adapter (Steam's, one per engine) replaces it in a store build. Steam facts are
from Valve's pages (E78 achievements and stats, E79 Steam Cloud, E76 uploads; F39); limits not on those pages are
marked **(verify)**.

The rules live in one reference, `tools/golden_vectors.py` (`achievements_load`, `Platform`, `cloud_partition`,
`overlay_action`, `platform_state_load`), and `data/golden/platform.json` holds its cases. An engine's port loads that
file in its unit tests and must reproduce every case exactly, as the juice and shell ports do (`SOP-18`, `SOP-19`).
Change the reference first, run `python tools/golden_vectors.py --write`, then fix the ports.

Status: phase 1 (#84) is this spec, the reference and its cases. The engine ports and the Steam adapters are phase 2,
not written yet.

## 1. The pieces
```
game code ──calls──> Platform (the rules, engine-free)  ──calls──> backend
                     local state: data/achievements.json,          null: records every call (default)
                     platform_state.json, the presence map         steam: the engine's Steamworks wrapper
```
- **Definitions:** data/achievements.json, written by the game (the kit ships none; create it when the game gets its
  first achievement). Load it with `achievements_load`.
- **Local state:** `<user-data>/platform_state.json`, next to `settings.json`: what is unlocked, every stat's value,
  and the queue not yet stored. Written atomically like a save (`SOP-19` section 3). It is a cache: the
  store's copy is the truth, so a file that does not load starts from the initial state.
- **Backend calls**, always as a list `[name, args...]`, in the order sent:
  `["set_achievement", id]`, `["set_stat", id, value]`, `["store_stats"]`,
  `["indicate_progress", id, value, threshold]`, `["reset_all_stats", true]`, `["set_presence", key, value]`,
  `["clear_presence"]`, `["cloud_write", path]`.

## 2. The definitions: data/achievements.json
```json
{"stats": [{"id": "enemies_defeated", "type": "int", "min": 0, "max": 1000000, "increment_only": true},
           {"id": "best_time_s", "type": "float", "min": 0, "max": 3600}],
 "achievements": [{"id": "first_win", "name": "ach_first_win", "description": "ach_first_win_desc"},
                  {"id": "defeat_100", "name": "ach_defeat_100", "stat": "enemies_defeated", "threshold": 100,
                   "progress_every": 25}]}
```
- Ids (stats, achievements, presence keys): a letter, then letters, digits and `_` (ASCII), at most 64. Stats and
  achievements have separate namespaces. On Steam, use the same names as the App Admin page's API names (E78).
- A stat: `type` `int` (default) or `float`; `min` (default 0) and `max` (default none), whole for an int stat;
  `increment_only` (default false). Its initial value is 0 clamped into `[min, max]`.
- An achievement: `name` (required) and `description` (default "") are localization keys: the shell's `tr` shows the
  key when a table lacks it, so plain words work too. A bound achievement names a `stat` and a `threshold` above the
  stat's initial value and at most its max; `progress_every`, if set, is above 0 and below the threshold (both whole
  for an int stat). A threshold without a stat is a mistake.
- Loading follows `settings_load`: no file is no achievements and no problems; not JSON or not an object is nothing
  and 1 problem; otherwise each bad entry is dropped and counted, and the rest load. A whole float (`5.0`) is a whole
  number: judge by the value, never the type (JavaScript and Lua cannot tell them apart); `true` is never a number.
- Steam allows 100 achievements at first; names and icons must be all-ages; before release they do not show in the
  Community, so the game shows what was earned itself (E78).

## 3. The rules (what every port reproduces)
Every operation returns `(out, calls)`: a status word and the backend calls it made, in order.

**Achievements.** `unlock(id)`: `unknown` (not defined: no call), `already` (no call, ever: an achievement unlocks
once), or `unlocked`: unlocked locally at once and, when online, flushed at once so the store shows its popup (E78:
SetAchievement, then StoreStats).

**Stats.** `set_stat(id, v)` and `add_stat(id, d)`:
- `unknown`; `refused` when the value is not a finite number, not whole for an int stat, or lower than now on an
  `increment_only` stat (the value stays); `same` when nothing changes (nothing becomes pending);
- `ok`, or `clamped` when the value was moved into `[min, max]`. The change is pending until a flush.
- Then every achievement bound to that stat whose threshold the new value reaches unlocks, **in definition order**.
  Online, a bound achievement whose `progress_every` step the value just crossed (and whose threshold it did not
  reach) sends `indicate_progress` at once (E78's IndicateAchievementProgress). Offline, no progress popups: they would
  be stale later.
- Stats wait for `flush()`; call it at checkpoints (level end, pause, quit). An unlock flushes everything pending.

**Flush.** `flush()`: `offline` (all kept), `nothing`, `sent` or `failed`. It sends `set_stat` for each pending stat
(definition order, the latest value only), `set_achievement` for each pending unlock (unlock order), one
`store_stats`, then `cloud_write` for each pending cloud file (first-save order). The pending lists clear only when
`store_stats` succeeds. A failed store keeps everything and the layer goes offline until `connect()`.

**The backend coming and going.** `connect(remote)`, with `remote = {"unlocked": [...], "stats": {id: value}}` as the
store reports it once its stats arrive:
1. remote unlocks join the local list without a call, and leave the pending list;
2. a remote stat (clamped) replaces the local one unless a local change is pending; on an `increment_only` stat the
   larger value wins, and the pending change drops when the remote is at least as far;
3. bound achievements are checked again (no progress popups here);
4. `flush()`, then, if the store accepted it, the presence map as it is now (keys sorted).

`out` is `online`, or `failed` when that flush failed (presence then waits for the next `connect`).
`disconnect()` goes offline. While offline every operation still updates the local state at once.

**Rich presence.** `set_presence(key, value)`: `refused` for a bad key, a value that is not a string or is longer than
255 UTF-8 bytes, or a key past the 30th (Steam's limits, **verify**); `same` for an unchanged value (nothing is
resent); else `ok`, sent at once when online. `""` removes the key. Offline only the map changes; `connect()` sends the
map, never the history. `clear_presence()`: `same` when empty, else `ok` (and `clear_presence` when online). Presence
is per session and not saved.

**The overlay's pause hook.** `overlay_action(active, screen)`: the store overlay opening over gameplay (`play`)
returns `pause`, and the game opens its pause menu, as on focus loss (`SOP-19` section 6). Anything else returns
`none`; closing the overlay never resumes: the player resumes from the pause menu, which is still open.

**Cloud saves.** `cloud_partition(path)` says which user-data files sync: `local` for `settings.json` (the display
settings belong to the machine, E79), `<user-data>/platform_state.json`, `telemetry.csv`,
`<user-data>/log_tail.txt`, any `*.tmp` or `*.log` (by file name, in any folder), and anything under a first
folder named `logs`, `crashes` or `captures`; `cloud` for the rest (the save slots and their `.bak`). Compared without
case, `\` read as `/`. `saved(path)` is the hook the save code calls after its atomic write succeeded: it returns the
partition and, in `api` cloud mode, sends `cloud_write` for a cloud file now (online) or queues it once (offline). In
`auto` mode it sends nothing.
- **Steam Auto-Cloud** (`auto`, no code): set the root to the user-data folder on Steamworks and include the cloud
  files by pattern, leaving out what `cloud_partition` calls local; test with `testappcloudpaths` on every OS (E79).
  Prefer it.
- **The Cloud API** (`api`, ISteamRemoteStorage): the adapter writes the file through the API on `cloud_write`. Only
  for a game that needs it (E79: per-user byte and file quotas; smaller files split by how often they change).

**Reset.** `reset_all()` is for testing: `offline` (refused: a reset is never queued), else everything back to the
initial values, the pending lists emptied, and `reset_all_stats` sent (E78's ResetAllStats(true)). Never in a shipped
menu.

**The state file.** `platform_state_load(defs, text)`: no file is the initial state with no problems. Not JSON, not an
object, another `format` or a `version` other than 1: the initial state and 1 problem. Otherwise each entry that does
not fit the definitions is dropped and counted (an unknown or repeated unlock, an unknown stat or a non-number, a
pending id that is unknown, repeated or not unlocked, a pending cloud path that is local); a stat out of range is
clamped, not counted.

## 4. The backend interface (phase 2 writes these)
| Call | Null backend | Steam adapter |
|---|---|---|
| `available()` | true | the SDK initialised (Steam running, the app owned) |
| `remote()` | what it recorded | the user's achievements and stats once they arrive |
| `set_achievement`, `set_stat`, `store_stats` | records; `store_stats` true (a test hook fails the next N) | ISteamUserStats (E78); `store_stats` false or its callback failing is a failed store |
| `indicate_progress`, `reset_all_stats` | records | ISteamUserStats |
| `set_presence`, `clear_presence` | records | ISteamFriends rich presence **(verify)** |
| `cloud_write(path)` | records | ISteamRemoteStorage, `api` mode only |
| each frame | nothing | run the SDK's callbacks; overlay open or closed calls `overlay_action` **(verify)** |

The null backend keeps every call in order, so tests and a debug overlay can show "what would have been sent"; with
`--debug` a port may also write them, one JSON array per line, to `<user-data>/platform_calls.jsonl`.

Candidate adapters, all **(verify)** for version and licence before use: GodotSteam (Godot), Steamworks.NET or
Facepunch.Steamworks (Unity), the Online Subsystem Steam plugin (Unreal), the steamworks crate or bevy_steamworks
(Bevy), luasteam (LÖVE), the Steamworks SDK directly (C++/SDL2), steamworks.js or Greenworks for NW.js and Electron
builds (web, RPG Maker MZ). A plain browser build has no Steam and keeps the null backend.

## 5. Steam housekeeping
- **Test with app 480** (Valve's Spacewar) before you have your own app id: put `480` in
  `<build>/steam_appid.txt`, next to the dev build's executable, so the game starts outside Steam (**verify** per
  wrapper). Its achievements are Spacewar's
  own, so test the wiring there and your own definitions on your app.
- **Never ship `<build>/steam_appid.txt`.** `python tools/dev.py ship --target steam` refuses a depot folder holding one
  (`SOP-21` step 3).
- **The Steamworks SDK is never committed**, to the game's repo or the kit: its access agreement does not allow
  redistributing it **(verify)**. Each machine downloads it from partner.steamgames.com (a Steamworks login), and the
  adapter finds it there; the game's docs say where.
- Achievements and stats are defined on the App Admin page (E78); data/achievements.json mirrors them, it does not
  create them.
