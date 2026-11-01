// ---------------------------------------------------------------------------
// GameKitSpring.h
// Purpose : A damped spring for squash and stretch recovery, UI pops and wobble, plus the volume-keeping
//           squash scale it usually drives.
// Usage   : FGameKitSpring Spring(4.0, 0.5);            // frequency (Hz), damping (0 wobbles forever, 1 no overshoot)
//           on landing: Spring.X = 0.4;                  // kick it: 0.4 = squashed by 40 %
//           each Tick:  const FVector2D S = GameKit::Squash(Spring.Update(DeltaSeconds));
//                       Mesh->SetRelativeScale3D(FVector(S.X, S.X, S.Y));   // wide and flat, or tall and thin
// Notes   : Semi-implicit Euler: stable at game frame rates for the frequencies UI and characters use (keep
//           frequency * dt well below 1). Squash keeps the area: width times height stays 1, and amounts
//           below -0.9 are clamped so the scale never reaches 0. Matches tools/golden_vectors.py (Spring,
//           squash), checked against data/golden/juice.json.
//
// Pseudocode:
//   w = 2 pi frequency ; a = -w^2 (x - target) - 2 damping w v ; v += a dt ; x += v dt
//   Squash(a) = (1 + a, 1 / (1 + a)) with a clamped to >= SquashMinAmount
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double SpringFrequency = 4.0;    // oscillations per second
	inline constexpr double SpringDamping = 0.5;      // damping ratio: 0 wobbles forever, 1 settles without overshoot
	inline constexpr double SquashMinAmount = -0.9;   // the most stretch allowed (scale 0.1 wide, 10 tall)

	/** (width, height) scale for a squash amount: > 0 widens and flattens, < 0 stretches; area stays 1. */
	inline FVector2D Squash(double Amount)
	{
		const double A = FMath::Max(Amount, SquashMinAmount);
		return FVector2D(1.0 + A, 1.0 / (1.0 + A));
	}
}

class FGameKitSpring
{
public:
	explicit FGameKitSpring(double InFrequency = GameKit::SpringFrequency, double InDamping = GameKit::SpringDamping)
		: Frequency(InFrequency), Damping(InDamping)
	{
	}

	/** Steps the spring by Dt seconds and returns the new position. */
	double Update(double Dt)
	{
		const double W = 2.0 * UE_DOUBLE_PI * Frequency;
		const double A = -W * W * (X - Target) - 2.0 * Damping * W * V;
		V += A * Dt;
		X += V * Dt;
		return X;
	}

	double Frequency;
	double Damping;
	double X = 0.0;        // position (set it to kick the spring)
	double V = 0.0;        // velocity
	double Target = 0.0;   // rest position
};

// {{FOOTER}}
