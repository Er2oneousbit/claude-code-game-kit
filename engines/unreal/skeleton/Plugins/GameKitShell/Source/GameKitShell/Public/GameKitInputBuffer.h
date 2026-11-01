// ---------------------------------------------------------------------------
// GameKitInputBuffer.h
// Purpose : Input buffering: remembers a press for a short window, so a jump pressed just before landing
//           (or an attack pressed during the last one) still happens.
// Usage   : FGameKitInputBuffer Buffer;                    // or FGameKitInputBuffer(WindowSeconds)
//           on the Enhanced Input "started" event: Buffer.Press(TEXT("jump"));
//           each Tick: Buffer.Update(DeltaSeconds);
//                      if (bOnFloor && Buffer.Consume(TEXT("jump"))) { Jump(); }
// Notes   : A press counts once: Consume() removes it. A new press of the same action restarts its window.
//           Actions are FName (case-insensitive, like every Unreal name). Matches tools/golden_vectors.py
//           (InputBuffer), checked against data/golden/juice.json.
//
// Pseudocode:
//   Press(a)   : pending[a] = window
//   Update(dt) : every pending time -= dt; drop the ones at or below ExpiredEpsilon
//   Consume(a) : pending[a] > 0 -> remove it, true ; else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double InputBufferWindow = 0.12;    // seconds a press stays usable
	inline constexpr double InputBufferEpsilon = 1e-12;  // a window this close to 0 has run out (float rounding)
}

class FGameKitInputBuffer
{
public:
	explicit FGameKitInputBuffer(double InWindowSeconds = GameKit::InputBufferWindow)
		: Window(InWindowSeconds)
	{
	}

	void Press(FName Action)
	{
		Pending.Add(Action, Window);
	}

	void Update(double Dt)
	{
		for (auto It = Pending.CreateIterator(); It; ++It)
		{
			It.Value() -= Dt;
			if (It.Value() <= GameKit::InputBufferEpsilon)
			{
				It.RemoveCurrent();
			}
		}
	}

	/** True once per buffered press of Action that is still inside its window. */
	bool Consume(FName Action)
	{
		const double* Left = Pending.Find(Action);
		if (Left && *Left > 0.0)
		{
			Pending.Remove(Action);
			return true;
		}
		return false;
	}

	bool IsPending(FName Action) const
	{
		const double* Left = Pending.Find(Action);
		return Left && *Left > 0.0;
	}

	void Clear() { Pending.Reset(); }

private:
	double Window;
	TMap<FName, double> Pending;   // action -> seconds left
};

// {{FOOTER}}
