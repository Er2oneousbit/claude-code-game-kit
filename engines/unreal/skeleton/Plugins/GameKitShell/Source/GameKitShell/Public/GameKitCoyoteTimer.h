// ---------------------------------------------------------------------------
// GameKitCoyoteTimer.h
// Purpose : Coyote time: a short grace window to jump after walking off a ledge, so a late press still counts.
// Usage   : FGameKitCoyoteTimer Coyote;                    // or FGameKitCoyoteTimer(WindowSeconds)
//           each Tick:      Coyote.Update(DeltaSeconds, GetCharacterMovement()->IsMovingOnGround());
//           on jump input:  if (Coyote.CanJump()) { Coyote.Consume(); Jump(); }
// Notes   : One jump per ground contact: Consume() closes the window, and landing again reopens it. Pair it
//           with FGameKitInputBuffer for presses that come slightly early. Same rules as the Godot and web
//           CoyoteTimer and tools/golden_vectors.py (Coyote), checked against data/golden/juice.json.
//
// Pseudocode:
//   Update(dt, on_floor): on floor -> (landing resets consumed) grounded, time_left = window
//                         in air   -> not grounded, time_left = max(time_left - dt, 0)
//   CanJump  = not consumed and (grounded or time_left > 0)
//   Consume  : consumed, time_left = 0
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double CoyoteWindow = 0.1;   // seconds after leaving the ground that a jump still works
}

class FGameKitCoyoteTimer
{
public:
	explicit FGameKitCoyoteTimer(double InWindowSeconds = GameKit::CoyoteWindow)
		: Window(FMath::Max(InWindowSeconds, 0.0))
	{
	}

	void Update(double Dt, bool bOnFloor)
	{
		if (bOnFloor)
		{
			if (!bGrounded)
			{
				bConsumed = false;   // a landing gives the next jump back
			}
			bGrounded = true;
			TimeLeft = Window;
		}
		else
		{
			bGrounded = false;
			TimeLeft = FMath::Max(TimeLeft - Dt, 0.0);
		}
	}

	bool CanJump() const
	{
		return !bConsumed && (bGrounded || TimeLeft > 0.0);
	}

	/** Call when the jump happens, so the grace window cannot give a second one. */
	void Consume()
	{
		bConsumed = true;
		TimeLeft = 0.0;
	}

	double GetTimeLeft() const { return TimeLeft; }

private:
	double Window;
	double TimeLeft = 0.0;
	bool bGrounded = false;
	bool bConsumed = false;
};

// {{FOOTER}}
