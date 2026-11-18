// ---------------------------------------------------------------------------
// GameKitFeel.h
// Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): Impact (a hit confirm scaled by damage),
//           FloatText (a damage number's rise, pop and fade) and the tracer's point history by distance
//           (TrailPush, TrailShrink, TrailLength).
// Usage   : const GameKit::FImpact Hit = GameKit::Impact(Damage, MaxHp);
//           Hitstop.Hit(Hit.Hitstop); Shake.AddTrauma(Hit.Trauma);
//           if (Hit.bFlash && Flashes.Request(FPlatformTime::Seconds())) { Flash(); }
//           const GameKit::FFloatText F = GameKit::FloatText(Age);        // F.Dy, F.Scale, F.Alpha, F.bDone
//           Points = GameKit::TrailPush(Points, Pos.X, Pos.Y, Spacing, Length);   // every Tick; after the hit:
//           Points = GameKit::TrailShrink(Points, Speed * DeltaSeconds);          // until fewer than two points
// Notes   : No settings, no clock, no random numbers, no UObjects. Points are FVector2D (doubles in UE 5), tail
//           first, head last; each trail function returns a new array. The defaults are SOP-18's starting points.
//           Matches tools/golden_vectors.py, checked against data/golden/juice.json ("impact", "float_text",
//           "trail").
//
// Pseudocode:
//   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); nothing for damage <= 0; lerp hitstop, trauma; flash f >= at
//   float_text: u = t / life; dy = -rise * out_cubic(u); scale = out_back(t / pop); alpha = 1 - in_cubic(u)
//   trail_push: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
//   trail_shrink: cut the trail to (length - amount) from the tail
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
//           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameKitEase.h"

namespace GameKit
{
	// ---- Tunables (SOP-18 step 4 starting points) ----
	inline constexpr double ImpactHitstopMin = 0.03;   // s, the smallest hit
	inline constexpr double ImpactHitstopMax = 0.1;    // s, a full hit (under Hitstop's 0.25 s cap)
	inline constexpr double ImpactTraumaMin = 0.15;
	inline constexpr double ImpactTraumaMax = 0.6;
	inline constexpr double ImpactFlashAt = 0.5;       // a hit of at least half of Full asks for a flash
	inline constexpr double FloatLife = 0.8;           // s
	inline constexpr double FloatRise = 24.0;          // px
	inline constexpr double FloatPop = 0.12;           // s
	inline constexpr double TrailSpacing = 6.0;        // px between kept points
	inline constexpr double TrailLengthMax = 48.0;     // px, the longest trail
	inline constexpr double TrailEps = 1e-12;          // a cut this close to a point removes the point

	struct FImpact
	{
		double Hitstop = 0.0;
		double Trauma = 0.0;
		bool bFlash = false;
	};

	struct FFloatText
	{
		double Dy = 0.0;
		double Scale = 1.0;
		double Alpha = 1.0;
		bool bDone = false;
	};

	inline FImpact Impact(double Damage, double Full, double HitstopMin = ImpactHitstopMin, double HitstopMax = ImpactHitstopMax,
		double TraumaMin = ImpactTraumaMin, double TraumaMax = ImpactTraumaMax, double FlashAt = ImpactFlashAt)
	{
		FImpact R;
		if (Damage <= 0.0)
		{
			return R;
		}
		const double F = Full <= 0.0 ? 1.0 : FMath::Min(FMath::Max(Damage / Full, 0.0), 1.0);
		R.Hitstop = HitstopMin + (HitstopMax - HitstopMin) * F;
		R.Trauma = TraumaMin + (TraumaMax - TraumaMin) * F;
		R.bFlash = F >= FlashAt;
		return R;
	}

	inline FFloatText FloatText(double T, double Life = FloatLife, double Rise = FloatRise, double PopS = FloatPop)
	{
		const double U = Life > 0.0 ? FMath::Min(FMath::Max(T / Life, 0.0), 1.0) : 1.0;
		FFloatText R;
		R.Dy = -Rise * Ease(EGameKitEase::OutCubic, U);
		R.Scale = PopS > 0.0 ? Ease(EGameKitEase::OutBack, T / PopS) : 1.0;
		R.Alpha = 1.0 - Ease(EGameKitEase::InCubic, U);
		R.bDone = T >= Life;
		return R;
	}

	inline double TrailSegment(const FVector2D& A, const FVector2D& B)
	{
		const double Dx = B.X - A.X;
		const double Dy = B.Y - A.Y;
		return FMath::Sqrt(Dx * Dx + Dy * Dy);
	}

	/** Total length, tail to head (summed in order, as the reference does). */
	inline double TrailLength(const TArray<FVector2D>& Points)
	{
		double Total = 0.0;
		for (int32 I = 0; I + 1 < Points.Num(); ++I)
		{
			Total += TrailSegment(Points[I], Points[I + 1]);
		}
		return Total;
	}

	inline TArray<FVector2D> TrailTrimTo(TArray<FVector2D> Pts, double Keep)
	{
		double Excess = TrailLength(Pts) - FMath::Max(Keep, 0.0);
		while (Excess > TrailEps && Pts.Num() > 1)
		{
			const double S = TrailSegment(Pts[0], Pts[1]);
			if (S <= Excess + TrailEps)
			{
				Pts.RemoveAt(0);
				Excess -= S;
			}
			else
			{
				const double K = Excess / S;
				Pts[0] = FVector2D(Pts[0].X + (Pts[1].X - Pts[0].X) * K, Pts[0].Y + (Pts[1].Y - Pts[0].Y) * K);
				Excess = 0.0;
			}
		}
		return Pts;
	}

	/** A tracer's path: the head follows (X, Y); a new point is kept once the head is Spacing past the point before
	 *  it (by distance, not frame); longer than MaxLen, the tail is cut. */
	inline TArray<FVector2D> TrailPush(TArray<FVector2D> Pts, double X, double Y, double Spacing = TrailSpacing,
		double MaxLen = TrailLengthMax)
	{
		const int32 N = Pts.Num();
		if (N < 2 || TrailSegment(Pts[N - 2], Pts[N - 1]) >= Spacing)
		{
			Pts.Add(FVector2D(X, Y));
		}
		else
		{
			Pts[N - 1] = FVector2D(X, Y);
		}
		return TrailTrimTo(MoveTemp(Pts), MaxLen);
	}

	/** The tail catching up after the shot dies: remove Amount px from the tail (fewer than two points: draw nothing). */
	inline TArray<FVector2D> TrailShrink(const TArray<FVector2D>& Points, double Amount)
	{
		return TrailTrimTo(Points, TrailLength(Points) - Amount);
	}
}
