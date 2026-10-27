# Examples

Small games made with the kit, kept in the repo as proof and as something to copy from.

| Example | Engine | What it shows |
|---|---|---|
| [ghost-lantern](ghost-lantern/) | Web (Phaser 4) | **Built only with what is in the kit.** Top-down escape: utility-AI ghosts that fear your lantern, A* and separation steering, a scenario pair that proves the lantern matters (escapes with it on 6/6 seeds, caught without it on 6/6), and six kit gaps found and fixed along the way |
| [courier-dash](courier-dash/) | Web 3D (Three.js) | **Built only with what is in the kit, in 3D.** Carry parcels past a patrol robot: Kenney CC0 models fetched with `fetch_asset.py` and prepared with the Blender tools, an FSM robot with a sight cone drawn as far as it really sees, grid A*, and the whole run in engine-free TypeScript so the scenario pair (careful bot wins, reckless bot is caught, 4 robot starts each) runs in Vitest and replays identically in the browser. Nine kit gaps found and fixed |
| [scrap-tanks](scrap-tanks/) | C++ / SDL2 | **Built only with what is in the kit, in C++.** A one-screen tank brawl: Kenney 3D models rendered into 32-direction sprite sheets with `render_sprites.py`, raiders on a small behavior tree whose active branch shows over each tank, and a scenario pair that proved the main pillar false three times before it held (cover wins 25 of 40 seeds, charging 11 of 40). Six kit gaps found and fixed |
| [graveyard-shift](graveyard-shift/) | Unity 6 | **Built only with what is in the kit, in Unity, without the editor UI.** Night stealth with a lantern you choose to light: three ghosts on a tested C# state machine with Unity's NavMesh, a scene built by an editor script through `dev.py exec`, a versioned save with a migration, and a bot trio (careful, always lit, always dark) over 8 seeds that refuted the lantern pillar until a redesign. Eight kit gaps found and fixed. Then iterated by ear: generated sound and voices (ElevenLabs, Fish Audio), Suno music looped in code, a dawn ending, ten playtest-driven changes in its iteration timeline |
| [rune-delve](rune-delve/) | Unreal Engine 5 | **Built only with what is in the kit, in Unreal, without the editor UI.** A top-down room clearer where a ward timed to an orc's wind-up beats spamming spells: every ability is Gameplay Ability System C++, orcs see and hear through AI Perception and chase on a runtime NavMesh, all content comes from one headless Python script (`dev.py exec`), and a bot pair over 8 seeds proves the pillar (3 full clears against 0). Eight kit gaps found and fixed |
| [gatekeeper-web](gatekeeper-web/) | Web (Phaser 4) | **Local AI in the browser:** talk past a guard run by a small language model (WebLLM on WebGPU, no server, no key). The model only labels and words; the rules decide. Scripted fallback, recorded-output tests, real-model scenario runs |
| [gatekeeper-godot](gatekeeper-godot/) | Godot 4 | **Local AI in a native game:** the same game with the NobodyWho plugin and a GGUF model on the player's GPU, a live accuracy eval (93%), a setup script that verifies the model download, and an optional live voice (Fish Audio, the player's own key) |
| [coyote-hop](coyote-hop/) | Godot 4 | A one-level platformer: tunables module, level as data, a reachability test that guards the level design, an autoplay bot, CC0 art brought in with `tools/fetch_asset.py`, a hero swapped after a playtest, and all sound made in code with the kit's synth tools |
| [lockpick-mz](lockpick-mz/) | RPG Maker MZ | **Untested proof of concept: never run in RPG Maker MZ.** A lockpicking minigame as two plugins: the rules in an engine-free plugin tested in Node (a careful bot opens 40 of 40 locks, a masher 1), the glue tested against stand-ins for MZ's classes. Rule 5 below (smoke passes on the named engine version) does not hold for it yet |

## License
The example games are copyright er2oneousbit, all rights reserved, and free to read, run, study and reference: see
[LICENSE.md](LICENSE.md). Kit-provided files inside them stay MIT; assets keep their own licenses.

## Rules for every example
1. **`HOW_IT_WAS_MADE.md` is required.** The exact commands, the order of work, what the kit's checks caught, and an honest
   list of anything that came from outside the kit. Someone should be able to repeat it. Once the game changes after it
   first works, it also keeps an **iteration timeline**: what prompted each change (playtest words or a failed check),
   what changed, and what proved it.
2. **Scaffolded by `scripts/new_game.py`**, then built. Never hand-assembled.
3. **License:** the example's README links `../LICENSE.md` (all rights reserved, free to reference).
4. **Every asset is in its `docs/ASSET_LOG.md`** with license evidence in `docs/licenses/`. CC0 or other licenses that allow
   public redistribution only.
5. **Green before it lands:** `doctor`, `check`, `test` and `smoke` pass on the engine version named in its `docs/ENGINE.md`.
6. **No Git LFS in examples:** their `.gitattributes` stores assets in plain git so "Download ZIP" works (assets stay small).
   Your own games should use LFS (SOP-05).
7. **No build output, caches or dependencies committed** (`.godot/`, `addons/gut/`, `node_modules/`, `dist/`, `.asset_cache/`,
   Unity's `Library/`, `Temp/`, `Logs/`, `UserSettings/`, `Build/`;
   Unreal's `Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`, `Packaged/`, and `Content/` when a script makes it).
   The example's README says how to get them back.

The kit's own link check skips this folder (each example is its own project): run `python tools/check_links.py` inside the example instead.
