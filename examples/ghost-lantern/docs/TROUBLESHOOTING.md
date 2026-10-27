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
### Ghosts caught the player inside the lantern light
- First seen: 2026-10-21
- Environment: Windows 11, Chromium (Playwright), Phaser 4.2.1
- Symptom: `CAUGHT` while the lantern was bright and the ghost was in its light
- Root cause: ghosts decided every 0.25 s and moved about a tile between decisions at chase speed
- Fix: `GHOST.thinkEvery` 0.12, and a shield rule (`GHOST.shieldLight`): a ghost in strong light cannot touch you
- How to verify: `python tools/dev.py smoke --query autoplay --until ESCAPED --fail-on CAUGHT`
- Related: ADR 0001

### The lantern did not matter (dark bot escaped)
- First seen: 2026-10-21
- Symptom: `?autoplay=dark` (never brightens) escaped
- Root cause: ghosts slower than the player, and dim light repelled them at point-blank range
- Fix: chase speed above player speed; `dimPower` 0.35 so dim light is for seeing, bright light shields
- How to verify: `python tools/dev.py smoke --query autoplay=dark --until CAUGHT`

### Ghosts stacked into one sprite
- First seen: 2026-10-21 (first debug screenshot)
- Root cause: all fleeing ghosts picked the same farthest cell
- Fix: separation steering (`src/core/separation.ts`) and a crowd penalty on flee targets
- How to verify: `tests/separation.test.ts`; `smoke --query "autoplay&debug" --until GOT_KEY --screenshot build/shot.png`

