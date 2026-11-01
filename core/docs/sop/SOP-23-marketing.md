# SOP-23: Marketing (store page, trailer, press kit, wishlists)

## Goal
The people who would love the game hear about it, can see in five seconds what it is, and have a way to follow it until
launch. Steam facts here come from Valve's documentation (F39); the rest is labeled practice or tips.

## 1. Start early (A)
- Put up the Steam Coming Soon page as soon as the game has a hook you can show (E82): wishlisters are notified at
  launch and at qualifying discounts (subject to Valve's cooldowns and their own email settings), and wishlists affect
  where Steam shows the game. There is no minimum count before Steam starts showing it.
- Plan the big moments: a demo (one wishlist notification within 14 days of its first release, E80), Steam Next Fest
  (once per game, unreleased, demo required, E81), the launch, the first discount (wishlist emails go out for a discount
  of at least 20 % on the lowest-priced package lasting over 8 hours, at most one such email per two weeks, E82). Space them so the notifications do not collide.

## 2. The hook and the store page
1. One sentence that says what the player does and why it is different (the GDD's pitch and twist). Test it on people
   who have not seen the game.
2. Capsules: logo or title only, readable at the small size (E77); the art session's store lane makes every size. The
   capsule is what most players see first: show the genre and mood at a glance.
3. Screenshots: real gameplay only (E77), the most readable moments, UI visible. The first screenshot and the first
   seconds of the trailer do most of the work (tip).
4. Description: the hook first, then three to five short bullets of what you do, then features (including accessibility
   options, `SOP-20`). The AI disclosure itself goes in Steam's Content Survey (`SOP-04`, F11); a line about it in the
   description is optional.

## 3. Trailer (practice)
1. Record real gameplay at the target resolution: `dev.py smoke --record` gives frame bursts; the art session's capture
   command records longer sequences; OBS for live play.
2. Gameplay in the first few seconds, no long logo intro. 30 to 90 seconds; end on the logo, the platforms and "Wishlist
   now".
3. Captions on screen for any spoken words (players watch muted; `SOP-20` applies to trailers too).

## 4. Press kit and devlog (practice)
- Press kit page (or a folder): a short and a long description, the fact sheet (developer, release date, platforms,
  price), logo files, five to ten screenshots, GIFs, the trailer link, contact (`docs/resources/learning-and-release.md`).
- Devlog on a steady rhythm (every one or two weeks) where the game's players already are; show a moment, not a feature
  list. Each post links to the store page.
- Send keys to press and creators who cover the genre, with a personal note and the press kit.

## 5. Measure (A where marked)
- The Wishlists report shows additions, purchases and deletions per day (E82). Note each beat (a post, a festival, a
  video) next to the curve to see what moved it.
- Track one number per channel (store visits, wishlists, click-through on the capsule) rather than everything.

## Done when
- The Coming Soon page is live with capsules, five or more screenshots and a trailer.
- A beat plan exists (demo, Next Fest, launch, first discount) with dates spaced for the wishlist email limits.
- The press kit exists and the devlog has a rhythm.

## Common mistakes
- Waiting for the game to be "ready" before the store page: wishlists take months to grow.
- Text, quotes or awards on capsules (E77).
- A trailer that opens with logos and cinematics instead of play.
- Joining Next Fest with a weak demo: a game gets one Next Fest (E81).
