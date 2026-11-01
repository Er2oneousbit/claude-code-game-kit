// ---------------------------------------------------------------------------
// GameKitFlashLimiter.h
// Purpose : Photosensitivity guard: at most MaxFlashes full-screen flashes in any WindowSeconds (three per
//           second by default), so effects cannot strobe at the rates that trigger seizures.
// Usage   : FGameKitFlashLimiter Flashes;                  // or FGameKitFlashLimiter(MaxFlashes, WindowSeconds)
//           when an effect wants a flash:
//             if (Flashes.Request(GetWorld()->GetRealTimeSeconds())) { PlayFlash(bFlashLimitSetting); }
//             else { PlaySubtleVersion(); }               // e.g. a vignette pulse instead of a white screen
// Notes   : The limiter is always on: no setting skips it (docs/sop/SOP-18, F34); the player's flash_limit
//           setting only makes the allowed flashes gentler. Pass real time (not dilated game time), so
//           hitstop or slow motion cannot squeeze flashes together.
//           The three-per-second rule is WCAG's flash rule (docs/sop/SOP-20). Matches
//           tools/golden_vectors.py (FlashLimiter), checked against data/golden/juice.json.
//
// Pseudocode:
//   Request(now): forget flashes at or before now - window ; fewer than max left -> record now, true ; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr int32 FlashMaxPerWindow = 3;
	inline constexpr double FlashWindowSeconds = 1.0;
}

class FGameKitFlashLimiter
{
public:
	explicit FGameKitFlashLimiter(int32 InMaxFlashes = GameKit::FlashMaxPerWindow,
	                              double InWindowSeconds = GameKit::FlashWindowSeconds)
		: MaxFlashes(InMaxFlashes), WindowSeconds(InWindowSeconds)
	{
	}

	/** True (and the flash is counted) when one more flash at time Now stays within the limit. */
	bool Request(double Now)
	{
		const double Oldest = Now - WindowSeconds;
		Times.RemoveAll([Oldest](double T) { return !(T > Oldest); });
		if (Times.Num() < MaxFlashes)
		{
			Times.Add(Now);
			return true;
		}
		return false;
	}

	void Reset() { Times.Reset(); }

private:
	int32 MaxFlashes;
	double WindowSeconds;
	TArray<double> Times;   // when the recent flashes started
};

// {{FOOTER}}
