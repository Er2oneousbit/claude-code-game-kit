# Troubleshooting Log

> Known issues and verified fixes. Future-you and testers should not need to ask how to fix these.
> Add an entry whenever a bug cost more than ~30 minutes or is likely to come back.

## Template (copy)
```
### <Short symptom>
- First seen: YYYY-MM-DD
- Environment: OS, engine version, build type
- Symptom: exact error text or behavior
- Root cause: 
- Fix: 
- How to verify: 
- Related: commit / ADR / issue
```

## Entries
### Charging beat fighting from cover (pillar 1 refuted)
- First seen: 2026-10-21
- Environment: tests/test_scenario.cpp, Windows 11, MSVC 14.44
- Symptom: reckless bot won 9/12 seeds, skilled 1/12; the skilled bot was in view 54% of the time, as much as the reckless one
- Root cause: raiders trained their guns on the player while flanking, so the one who rounded a corner fired first; hiding gave no first-shot advantage
- Fix: in FLANK, COVER and RETREAT the turret points where the raider drives; it swings to the player only in FIRE (also a visible tell)
- How to verify: `python tools/dev.py test` (pillar check over 40 seeds)

### Stand-offs: a raider and the player both in view, nobody shooting
- First seen: 2026-10-21
- Symptom: fights ran the full 5 minutes; the raider showed FLANK at its spot
- Root cause: sight is center to center, a clear shot needs room for the shell; a spot 0.3 m off its mark saw the player past a crate edge but had no shot
- Fix: a raider that arrives without a shot picks another spot; the bot counts a raider as a threat only when it can hit (`Sim::can_hit`)
- How to verify: no stalemates in the scenario test (a stand-off counts as a loss)

### Ground drawn with a dark grid
- First seen: 2026-10-21
- Symptom: thin dark lines across the ground every few tiles
- Root cause: fractional tile rectangles rounded down in the software renderer, leaving 1 px gaps
- Fix: integer tile edges taken from the next tile's position (`Game::draw_world`)
- How to verify: `python tools/dev.py smoke --screenshot build/shot.bmp`

### Tower Defense Kit models rendered black
- First seen: 2026-10-21
- Symptom: the ground tile and rocks came out black from `tools/make_sprites.py` (Cycles), fine in Eevee
- Root cause: the meshes store every face twice, back to back; Cycles' shadow rays hit the twin
- Fix: the kit's `render_sprites.py` removes the inner twin after import; `validate_asset.py` warns about such meshes
- How to verify: `python tools/make_sprites.py rocks` prints "removed ... back-to-back duplicate faces"
