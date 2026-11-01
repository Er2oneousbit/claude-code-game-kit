// ---------------------------------------------------------------------------
// GameKitShake.h
// Purpose : Trauma-based screen shake plus the smooth 1D value noise it samples. Plain C++, no world, no
//           clock: time comes in as Dt, so tests are deterministic.
// Usage   : FGameKitShake Shake;                    // or FGameKitShake(MaxOffset, MaxAngle, Decay, Frequency, Seed)
//           on a hit:   Shake.AddTrauma(0.4);
//           each Tick:  const FGameKitShakeOffset O = Shake.Update(DeltaSeconds, GameKit::EffectiveShake(*Settings));
//                       offset the camera by (O.X, O.Y) in your units and roll it by O.Angle (radians;
//                       FMath::RadiansToDegrees for an FRotator)
// Notes   : The shake is trauma squared, so small hits stay small. Intensity is the player's shake setting
//           (0 with reduce motion, see GameKitSettings.h). Matches tools/golden_vectors.py (Shake, noise),
//           checked against data/golden/juice.json by the GameKit.Golden.Juice tests.
//           Noise() uses Park-Miller integer arithmetic in int64, so every port gets the same values.
//
// Pseudocode:
//   Lattice(seed, i, ch) = Park-Miller twice on a mix of the inputs, mapped to (-1, 1]
//   Noise(seed, t, ch)   = lattice values at floor(t) and floor(t) + 1 blended with smoothstep
//   AddTrauma(a)         : trauma = clamp(trauma + a, 0, 1)
//   Update(dt, k)        : time += dt; trauma -= decay * dt (not below 0); s = trauma^2 * k
//                          return max_offset * s * noise(ch 0), max_offset * s * noise(ch 1), max_angle * s * noise(ch 2)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables (defaults; a game passes its own to the constructor) ----
	inline constexpr double ShakeMaxOffset = 8.0;    // units at full trauma (pixels in 2D, cm in 3D: pick your own)
	inline constexpr double ShakeMaxAngle = 0.05;    // radians at full trauma
	inline constexpr double ShakeDecay = 1.5;        // trauma lost per second
	inline constexpr double ShakeFrequency = 15.0;   // noise lattice points per second
	inline constexpr int64 ShakeSeed = 1;

	// Park-Miller "minimal standard" generator: modulus 2^31 - 1, multiplier 16807
	inline constexpr int64 NoiseModulus = 2147483647;
	inline constexpr int64 NoiseMultiplier = 16807;

	/** A value in (-1, 1] for integer lattice point I of channel Ch. */
	inline double NoiseLattice(int64 Seed, int64 I, int64 Ch)
	{
		int64 S = (Seed * 7919 + I * 104729 + Ch * 15485863) % NoiseModulus;
		if (S < 0)
		{
			S += NoiseModulus;   // C++ % keeps the sign of the left side; the reference (Python) never goes negative
		}
		if (S == 0)
		{
			S = 1;               // 0 is a fixed point of Park-Miller
		}
		S = (S * NoiseMultiplier) % NoiseModulus;
		S = (S * NoiseMultiplier) % NoiseModulus;
		return static_cast<double>(S) / static_cast<double>(NoiseModulus - 1) * 2.0 - 1.0;
	}

	/** Smooth 1D value noise in about -1..1. T >= 0 in normal use; NaN or infinite T gives 0 (no shake). */
	inline double Noise(int64 Seed, double T, int64 Ch)
	{
		if (!FMath::IsFinite(T))
		{
			return 0.0;
		}
		const double Fi = FMath::FloorToDouble(T);
		const int64 I = static_cast<int64>(Fi);
		const double F = T - Fi;
		const double A = NoiseLattice(Seed, I, Ch);
		const double B = NoiseLattice(Seed, I + 1, Ch);
		const double U = F * F * (3.0 - 2.0 * F);   // smoothstep
		return A + (B - A) * U;
	}
}

struct FGameKitShakeOffset
{
	double X = 0.0;
	double Y = 0.0;
	double Angle = 0.0;   // radians
};

class FGameKitShake
{
public:
	explicit FGameKitShake(double InMaxOffset = GameKit::ShakeMaxOffset, double InMaxAngle = GameKit::ShakeMaxAngle,
	                       double InDecay = GameKit::ShakeDecay, double InFrequency = GameKit::ShakeFrequency,
	                       int64 InSeed = GameKit::ShakeSeed)
		: MaxOffset(InMaxOffset), MaxAngle(InMaxAngle), Decay(InDecay), Frequency(InFrequency), Seed(InSeed)
	{
	}

	/** Adds (or with a negative amount removes) trauma, kept within 0..1. */
	void AddTrauma(double Amount)
	{
		Trauma = FMath::Min(FMath::Max(Trauma + Amount, 0.0), 1.0);
	}

	/** Advances by Dt seconds and returns this frame's offset. Intensity scales it (the player's setting). */
	FGameKitShakeOffset Update(double Dt, double Intensity = 1.0)
	{
		Time += Dt;
		Trauma = FMath::Max(Trauma - Decay * Dt, 0.0);
		const double S = Trauma * Trauma * Intensity;
		const double T = Time * Frequency;
		FGameKitShakeOffset Out;
		Out.X = MaxOffset * S * GameKit::Noise(Seed, T, 0);
		Out.Y = MaxOffset * S * GameKit::Noise(Seed, T, 1);
		Out.Angle = MaxAngle * S * GameKit::Noise(Seed, T, 2);
		return Out;
	}

	double GetTrauma() const { return Trauma; }

private:
	double MaxOffset;
	double MaxAngle;
	double Decay;
	double Frequency;
	int64 Seed;
	double Trauma = 0.0;
	double Time = 0.0;
};
