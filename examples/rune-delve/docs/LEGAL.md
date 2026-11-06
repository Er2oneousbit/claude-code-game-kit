# Legal checklist (Rune Delve)

> Fill-in checklists, **not legal advice**. They make sure nothing obvious is missing before you ask a lawyer (do, for
> anything commercial at scale). Procedure: `docs/sop/SOP-21-ship-on-steam-and-itch.md` step 6. Items marked
> **(verify)** were not checked against the official source by the kit.

## 1. Licenses and credits
- [ ] Every shipped asset has a row in `docs/ASSET_LOG.md` with a known license; `python tools/credits.py --check` passes.
- [ ] CREDITS.md and THIRD_PARTY_LICENSES.md ship inside the build folder or the game's About screen.
- [ ] The engine's own notice ships (LÖVE's license.txt, Godot's MIT notice, Unity and Unreal splash and credit rules,
      SDL3 and other library notices) (verify per engine version).
- [ ] Fonts: the font license allows embedding in a game; OFL fonts keep their license file.

## 2. Privacy policy (needed as soon as anything about a player leaves their machine)
Answer each question in plain words; the answers are the policy.
- [ ] What is collected (crash reports, telemetry events, account data, purchases, chat)? List it.
- [ ] Why each item is collected.
- [ ] Where it goes (your server, which third-party services; name them) and in which countries.
- [ ] How long it is kept, and how a player asks for it to be deleted.
- [ ] How a player turns it off in the game (the shell's consent setting, `SOP-19` step 8).
- [ ] Children: if players under 13 (or 16 in some regions) may play, what changes (verify the rules for your markets).
- [ ] Contact address for privacy questions.
- [ ] Link to the policy from the store page and from the game's settings.
If nothing leaves the machine (the kit's default: local logs, local telemetry file, local saves), say so in one line in the
store description; no policy page is needed for that (verify for your stores).

## 3. EULA and terms
- [ ] Steam: Valve's subscriber agreement covers purchases; a custom EULA is optional (verify on Steamworks).
- [ ] itch.io: state your terms in the page description (personal use, no redistribution, refunds).
- [ ] If the game has online features or user content: rules for conduct and what happens to content players upload.
- [ ] Mods: the policy from `SOP-06` "After launch", and whether mod authors may sell their mods.

## 4. Age ratings
- [ ] Stores that need a rating (consoles, mobile, Microsoft Store, Nintendo eShop): get it through IARC in each store's
      submission (one questionnaire, ratings for many regions; IARC states developers rate "at no cost", E88). Which
      stores use IARC: check globalratings.com (verify).
- [ ] Steam: answer the content questions in Steamworks' Content Survey (and its generative AI section, `SOP-04`).
- [ ] Physical or retail releases need the regional board directly (ESRB, PEGI, USK, CERO; verify fees and process).
- [ ] Questions to prepare for any rating: violence (and toward whom), blood, language, sexual content, gambling or loot
      boxes with real money, drugs and alcohol, user interaction (chat), shared location, in-game purchases.

## 5. Business and money (verify each with the platform)
- [ ] Engine revenue terms (Unreal royalty above its threshold and the Release Form; Unity plan by revenue and funding).
- [ ] Store tax and bank forms completed (Steamworks and itch.io payout settings).
- [ ] Music: the license covers streaming of gameplay (players' videos); some licenses forbid it.
- [ ] AI-made content disclosed where the store asks (`SOP-04`).
