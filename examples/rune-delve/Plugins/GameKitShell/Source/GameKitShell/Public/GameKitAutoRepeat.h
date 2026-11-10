// ---------------------------------------------------------------------------
// GameKitAutoRepeat.h
// Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats its press, so a player who cannot
//           tap fast (one hand, a switch, a tremor) can still mash. Plain C++, no input system.
// Usage   : FGameKitAutoRepeat Repeat;
//           const bool bHeld = PC->IsInputKeyDown(EKeys::SpaceBar);
//           if (bJustPressed || (GameKit::SettingBool(*S, TEXT("access"), TEXT("auto_repeat")) && Repeat.Update(DeltaSeconds, bHeld)))
//           {
//               Attack();
//           }
// Notes   : The first repeat comes after DelayS, then one every IntervalS while held; releasing resets it. The
//           times are the kit's starting point (a tip: tune them per game), not from a source. Same numbers as
//           the Godot, LÖVE and web ports.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

struct FGameKitAutoRepeat
{
	// ---- Tunables ----
	static constexpr double DelayS = 0.35;      // held this long before the first repeat
	static constexpr double IntervalS = 0.15;   // then one repeat this often

	double Held = 0.0;
	double Next = DelayS;

	/** Call every frame with whether the button is held; true on a frame that repeats the press. */
	bool Update(double Dt, bool bHeld)
	{
		if (!bHeld)
		{
			Held = 0.0;
			Next = DelayS;
			return false;
		}
		Held += Dt;
		if (Held >= Next)
		{
			Next += IntervalS;
			return true;
		}
		return false;
	}
};
