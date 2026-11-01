// ---------------------------------------------------------------------------
// GameKitHitstop.h
// Purpose : Hitstop: freezes game time for a moment on impact, so a hit lands with weight.
// Usage   : FGameKitHitstop Hitstop;                     // or FGameKitHitstop(MaxSeconds)
//           on a heavy hit: Hitstop.Hit(0.08);
//           each Tick:      const double GameDt = Hitstop.ScaledDt(DeltaSeconds);  // step gameplay with GameDt
// Notes   : Overlapping hits keep the longest freeze, capped at MaxSeconds, so a flurry never locks the
//           game. Freeze gameplay only: menus, audio and the camera shake keep the real delta. In a world,
//           scale the gameplay actors' delta (an actor's CustomTimeDilation, or your own tick), not
//           UGameplayStatics::SetGlobalTimeDilation, which also slows UI and timers (docs/sop/SOP-18).
//           Matches tools/golden_vectors.py (Hitstop), checked against data/golden/juice.json.
//
// Pseudocode:
//   Hit(d)        : remaining = min(max(remaining, d), max_s)
//   ScaledDt(dt)  : remaining <= 0 -> dt ; else used = min(remaining, dt); remaining -= used; return dt - used
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double HitstopMaxSeconds = 0.25;   // longest freeze, however many hits overlap
}

class FGameKitHitstop
{
public:
	explicit FGameKitHitstop(double InMaxSeconds = GameKit::HitstopMaxSeconds)
		: MaxSeconds(InMaxSeconds)
	{
	}

	/** Starts (or extends) a freeze of Duration seconds. Shorter hits during a longer freeze change nothing. */
	void Hit(double Duration)
	{
		Remaining = FMath::Min(FMath::Max(Remaining, Duration), MaxSeconds);
	}

	/** The game's delta for this frame: the frozen part of RealDt is removed. */
	double ScaledDt(double RealDt)
	{
		if (Remaining <= 0.0)
		{
			return RealDt;
		}
		const double Used = FMath::Min(Remaining, RealDt);
		Remaining -= Used;
		return RealDt - Used;
	}

	double GetRemaining() const { return Remaining; }
	bool IsFrozen() const { return Remaining > 0.0; }

private:
	double MaxSeconds;
	double Remaining = 0.0;
};
