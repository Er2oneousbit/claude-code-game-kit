# Engine: Unreal Engine 5 (C++ and Blueprints)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.

## Version and setup
- **Unreal version:** 5.x (SET EXACT VERSION HERE, e.g. 5.5.x). Source or Launcher build, record which.
- **Env var:** `UE_ROOT` = engine install folder (the one containing `Engine/`). `dev.py doctor` verifies.
- **Project file:** the `*.uproject` in the repo root. Adopt-first: create the project in the editor (no spaces in the name), close
  the editor, then run `new_game.py --adopt` into that folder and `python tools/dev.py doctor`. Full steps: `docs/ENGINE_FLOW.md` "Setup".
- **Toolchain:** MSVC, the Windows SDK and the .NET Framework 4.8 SDK. The free "Build Tools for Visual Studio 2022" with the "Desktop development with C++" workload plus the ".NET Framework 4.8 SDK" component is enough; the Visual Studio IDE is optional (VS Code works: `python tools/dev.py genproj --vscode`). Allowed and banned MSVC versions are in `<UE_ROOT>/Engine/Config/Windows/Windows_SDK.json` (UE 5.8: 14.44 or 14.50 families). Blueprint-only projects run tests without a toolchain.
- **Live Coding:** any open Unreal editor on the same engine install blocks command-line builds of every project. Close it before `dev.py check`.
- **Languages:** C++ for systems, base classes, and anything Claude must edit. Blueprints for content-facing glue and data. Editor Python (`python tools/dev.py exec <script.py>`, headless) for asset imports and maps, so binary content comes from a script Claude can edit (`docs/ENGINE_FLOW.md` "Content from scripts").
- **Source control:** Git with **Git LFS** (see `.gitattributes`). Set up LFS before the first commit of `Content/`.
- **Optional:** Unreal MCP plugin so Claude can inspect and modify the editor. Record which plugin and version in an ADR and describe how to start it here. 

## Layout
```
<Game>.uproject
Source/<Game>/           C++ module (Public/ and Private/)
Source/<Game>Tests/      automation tests (optional separate module, or Private/Tests/)
Content/                 binary assets (.uasset, .umap): NEVER hand-edit, LFS tracked
Config/                  .ini settings (text, editable with care)
Plugins/                 project plugins (including MCP if used)
Tools/ or tools/         dev.py and helpers
```

## The big rule: what Claude can and cannot edit
| Edit freely | Edit with care | Never edit by hand |
|---|---|---|
| `Source/**` C++ | `Config/*.ini` (check keys against docs) | `Content/**/*.uasset`, `*.umap` (binary) |
| `tools/`, `docs/` | `*.uproject`, `*.Target.cs`, `*.Build.cs` | `Intermediate/`, `Binaries/`, `Saved/`, `DerivedDataCache/` |
| Data files that get imported (CSV/JSON for DataTables) | Plugin descriptors | `.sln`/`.vcxproj` (generated) |

**Consequence:** put behavior in C++ (or data-driven assets fed by CSV/JSON) so Claude can change it by editing text.
Blueprint graph changes happen in the editor (by you, or via an MCP plugin if you set one up). Claude writes the C++ base class
and a clear spec for the Blueprint child.

## Conventions
- UE coding standard prefixes: `A` actors, `U` UObjects/components, `F` structs, `E` enums, `I` interfaces, `T` templates.
- Asset prefixes: `BP_` blueprint, `WBP_` widget, `M_` material, `MI_` material instance, `T_` texture, `SM_` static mesh,
  `SK_` skeletal mesh, `A_`/`AM_` animation, `DT_` data table, `DA_` data asset, `SFX_`/`MUS_` sound cues or MetaSounds.
- `UPROPERTY` and `UFUNCTION` specifiers on everything exposed. Use `EditAnywhere`, `BlueprintReadOnly` etc. deliberately.
- Tunables: `UDataAsset` or `UDeveloperSettings` or DataTables, not literals in `.cpp`.
- Logging: `DEFINE_LOG_CATEGORY` per system, `UE_LOG(LogMyGame, Warning, TEXT("..."))`. No `GEngine->AddOnScreenDebugMessage` in committed logic except behind a debug cvar.
- Debug toggles: console variables (`TAutoConsoleVariable`) or `exec` console commands.
- Tests: Automation Spec or simple automation tests for engine-light logic (see ENGINE_FLOW).

## Gotchas (Claude: read before editing)
1. **Header changes require a full editor restart or a Live Coding-incompatible rebuild.** Prefer building with `dev.py check` and restarting the editor after header/reflection changes. Live Coding handles function body edits only.
2. **Never edit generated files** (`*.generated.h`, `.sln`, `Intermediate/`). Regenerate project files with `dev.py genproj`.
3. **`#include "X.generated.h"` must be the last include** in a header with `UCLASS`/`USTRUCT`.
4. **Add new modules or plugins to `Build.cs`/`.uplugin`** explicitly, or you get linker errors.
5. **Raw `UObject*` members need `UPROPERTY()`** or the GC may collect them. Use `TObjectPtr<>` for UE5 members.
6. **Binary assets cannot merge.** Use file locking or "one person per asset" etiquette. Solo dev: still commit often.
7. **Hard-coded asset paths** break on rename. Use soft references or data-driven lookups.
8. **Tick everything is expensive.** Disable tick by default, enable when needed, prefer timers and events.
9. **Version matters:** many APIs moved between UE 5.x releases. Check the engine version in this file and the matching docs before using an unfamiliar API.
10. **Editor-only code** needs `#if WITH_EDITOR` or an Editor module, or packaging will fail.
11. **Secrets live in Config/ too.** `Config/DefaultCrypto.ini` holds pak encryption and signing keys (Claude is denied it), and Android signing puts `KeyStorePassword`/`KeyPassword` in `Config/DefaultEngine.ini`. Never read those values out or paste them anywhere; keep the repo private if they are committed.
12. **Never load assets by path in a constructor.** Every UCLASS builds its default object when the module loads, so a
    `LoadObject` there runs in every editor command, before a fresh clone has made or pulled its content; the error it logs fails
    commandlets (`dev.py exec`). Load in `BeginPlay` (or use `ConstructorHelpers` only for assets that always exist, such as engine ones).

## Generated or binary (do not hand-edit)
`Content/**/*.uasset`, `*.umap`, `Intermediate/`, `Binaries/`, `Saved/`, `DerivedDataCache/`, `.vs/`, `*.sln`, `*.generated.h`.
