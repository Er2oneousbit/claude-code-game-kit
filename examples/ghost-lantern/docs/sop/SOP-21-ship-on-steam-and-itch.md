# SOP-21: Ship on Steam and itch.io (stores, builds, signing, CI, legal)

## Goal
Get from a release build (`SOP-06`) to a game players can buy or download, with store pages that follow the rules, a
build pipeline that cannot ship an untested build, signed executables, and the legal basics in place. Steam facts here
are from Valve's own documentation read on 2026-11-01 (F39), itch.io facts from butler's documentation read on
2026-11-13 (E84); check the linked pages again before you rely on a number.

## 1. Before anything: what you need
| Item | Where | Cost or limit |
|---|---|---|
| Steamworks account and an app (Steam Direct) | partner.steamgames.com | A one-time fee per app (verify the current amount on Steamworks) |
| itch.io account | itch.io | Free; you pick the revenue share |
| Store art | Steam sizes in step 2; an image editor (pixel art: scale by whole numbers, then place on each canvas), or Dotwork's `store` lane in Godot | Logo or title only on capsules (E77, E102) |
| Signing certificate (Windows), Apple Developer Program (macOS) | step 5 | Paid; Windows SmartScreen warns about unsigned downloads (verify) |
| Age rating (consoles, mobile, many stores) | IARC, through each participating store (E88) | IARC states developers have rated "at no cost" |

## 2. Steam store page (A)
1. Put up the **Coming Soon page as early as you can**: players can wishlist it, wishlisters are emailed at launch and
   on discounts of at least 20 % on the lowest-priced package lasting over 8 hours (at most one wishlist email every
   two weeks), and wishlists are "an important factor"
   in where Steam shows a game (E82).
2. **Graphical assets** (E77): header capsule 920x430, small capsule 462x174, main capsule 1232x706, vertical capsule
   748x896, at least five screenshots of 1920x1080 or more (16:9), optional page background 1438x810. Library assets
   (E101): capsule 600x900, header 920x430, hero 3840x1240 with no text and the key content in the centred 860x380, and
   a transparent logo 1280 wide or 720 tall. In Godot, Dotwork's `store` lane makes every one of these sizes, the icons
   and the boot splash from one key art ([Dotwork store art](../../tools/art/dotwork/README.md#store-art-steam-sizes)).
   Capsules carry only the logo or title (no quotes, awards or other text), and the logo must stay readable on the small
   capsule. Screenshots show real gameplay only; mark at least four as suitable for all ages. Pixel art: scale the
   artwork by a whole number to the largest size that fits each canvas, then place it on that canvas and fill the rest
   with the background colour or more scene; never resample by a fraction.
3. **AI disclosure:** fill the Content Survey's generative AI section as `SOP-04` says (F11).
4. **Accessibility:** list the options from `SOP-20` in the description.

## 3. Uploading builds (A)
1. Steamworks: create depots (one per platform), publish.
2. Write an app build VDF (AppID, content root, the Depots list) and one depot build VDF per depot (FileMapping with
   LocalPath and DepotPath, FileExclusion for debug files) (E76). Keep them in the repo under `tools/steam/`, without
   any login.
3. Upload with `steamcmd +login <build account> +run_app_build <app_build.vdf> +quit`. The build account needs "Edit App
   Metadata" rights; the first login asks for a Steam Guard code, so run it by hand once on the machine that uploads
   (verify the current flow on Steamworks). Use `SetLive` to put a build on a beta branch automatically; the default branch can only be set
   live by hand in the App Admin panel (E76), which is the last human check before players get it.
4. **itch.io** with butler (E84): `butler push <folder> user/game:<channel> --userversion 1.2.0`. butler uploads only
   what changed. Channel names containing `win`/`windows`, `linux`, `mac`/`osx` or `android` tag the platform
   (`win-linux-mac-stable` tags three); lower case, dash-separated. A web build is marked "playable in browser" on the
   itch.io Edit game page after the first push (butler cannot), with the project's kind set to HTML. The kit wires it:
   ```
   python tools/dev.py ship --target itch --project user/game --dry-run          # the web build, channel html5
   python tools/dev.py ship --target itch --project user/game --yes              # push it
   python tools/dev.py ship --target itch --project user/game --site build/windows --channel windows --dry-run
   python tools/dev.py ship --target itch --project user/game --channel html5 --status   # what itch.io did with it
   ```
   `--dry-run` checks that butler is found (`BUTLER_BIN` or PATH), the folder exists, is not empty and holds no
   secret-type file or token, the project is `user/game`, the channel is valid, and the version is known (the engine's
   version source from `SOP-06`, or `--userversion`), then prints the exact butler command and uploads nothing. A push
   needs a login: `butler login` once on the machine, or `BUTLER_API_KEY` (in CI, a repository secret); the kit only
   checks that one is there and never reads, prints or writes it. A push asks for the game's slug in a terminal and
   needs `--yes` anywhere else. Not done yet: a real upload through the kit (tested with a stand-in butler only,
   **verify** on the first push), and `--status`, which runs `butler status` (seen in butler's own output, not its docs:
   **verify**). Steam has no `ship` target yet (#84): use step 3 by hand.
5. Never put store passwords, butler keys or Steam credentials in the repo or in a log (`CLAUDE.md` guardrails). In
   CI they live in the repository's secrets.

## 4. Steam features (A)
- **Achievements** (E78): defined on the App Admin page; unlock with `SetAchievement` then `StoreStats`; reset for
  testing with `ResetAllStats(true)` or the Steam console. Up to 100 at first. All-ages names and icons. Before release
  they do not show in the Community, so the game should show what was earned. Tip: design them as goals that point at
  the game's pillars, not chores ("kill 10,000 rats").
- **Steam Cloud** (E79): Auto-Cloud (folders set on Steamworks, no code) suits the shell's save folder; keep settings
  that depend on the machine (resolution, vsync) out of the cloud. Test with `testappcloudpaths` on every OS.
- **Steam Input and Deck:** the Deck review wants full controller support by default and glyphs that match (E75); the
  shell's prompt switching covers the second.
- **Demo** (E80): a separate App ID with its own builds; one wishlist notification within 14 days of the demo's first
  release. Disable achievements in the demo; carry progress over through the cloud.
- **Playtest** (E83): a child app with signups on your store page; free, no NDA, keys possible before the page is live.
- **Next Fest** (E81): once per game, unreleased, with a public demo by the start; demo builds due 3 to 5 weeks before.

## 5. Signing (A where marked)
- **Windows** (E85): `signtool sign /f cert.pfx /p <password> /fd SHA256 /tr <timestamp server> /td SHA256 game.exe`,
  then `signtool verify /pa game.exe`. Always timestamp, so the signature outlives the certificate. The certificate's
  password goes in a secret store, never the repo (the kit's deny rules block `*.pfx` and `*.p12`).
- **macOS:** sign with a Developer ID certificate and the hardened runtime, notarize with `xcrun notarytool submit
  <zip> --wait`, then `xcrun stapler staple <app>`. Not run by the kit (verify against Apple's documentation).
- **Linux:** no signing; ship a tarball or an AppImage, or let Steam and itch handle it.

## 6. Legal checklist (not legal advice)
The full fill-in checklist is `docs/LEGAL.md`; the short version, with a lawyer for anything commercial at scale:
- **Licenses and credits:** `python tools/credits.py` builds CREDITS.md and THIRD_PARTY_LICENSES.md from
  `docs/ASSET_LOG.md` and `docs/licenses/`; ship both with the build. An asset without a known license does not ship
  (`SOP-04`).
- **Privacy policy:** needed as soon as anything about players leaves their machine (telemetry upload, crash upload,
  accounts, analytics SDKs). State what, why, where it goes, how long it is kept, and how to opt out. The shell's
  telemetry writes nothing until the player agrees and sends nothing (`SOP-19` step 8).
- **EULA:** Steam has a default subscriber agreement; a custom EULA is optional on Steam (verify on Steamworks). itch.io
  pages state your terms in the description.
- **Age ratings:** IARC gives ratings for many regions from one questionnaire through participating stores (E88; check
  which stores you ship to). Steam asks content questions in its own survey.
- **Engine and middleware terms:** Unity, Unreal and others have revenue thresholds and splash rules; read
  `docs/resources/licenses.md` and the engine row in `docs/ENGINE.md`.

## 7. Continuous integration (standard practice)
`.github/workflows/ci.yml` runs `python tools/dev.py check` and `test` on every push and pull request (the shipped file
sets up Godot or Node for those overlays and documents the rest). `.github/workflows/audio.yml` runs every Wavesmith
exam on Linux, Windows and macOS whenever `tools/audio/` or `data/golden/` change. A red build blocks a release. Builds for stores come
from a tagged commit (`SOP-06`), never from a working copy.

## Done when
- The store page is live as Coming Soon with assets at the listed sizes and the AI disclosure filled.
- A build from a tagged commit with green CI went to a beta branch (or an itch channel) and was played from there on a
  clean machine. The kit's CI checks and tests; the upload is a step you run (step 3).
- Executables are signed and verified (or the reason they are not is written down).
- CREDITS and THIRD_PARTY_LICENSES ship with the build; the privacy policy exists if anything is collected.

## Common mistakes
- A Coming Soon page put up a month before launch, which leaves little time to gather wishlists (tip).
- Marketing text, awards or review quotes on capsules (E77 forbids them).
- Uploading straight to the default branch with no human check.
- Credentials in a VDF, a script or CI logs.
- Shipping an unsigned exe and losing players to the browser's download warning.
