// ---------------------------------------------------------------------------
// GameKitEase.h
// Purpose : The standard easing curves (quad, cubic, sine, back, elastic, bounce) for tweens, UI motion
//           and squash recovery, by enum or by the name a data file uses ("out_back").
// Usage   : const double K = GameKit::Ease(EGameKitEase::OutBack, Elapsed / Duration);
//           const FVector2D P = FMath::Lerp(From, To, K);
//           if (const TOptional<double> V = GameKit::EaseByName(TEXT("in_out_sine"), T)) { ... *V ... }
// Notes   : T is clamped to 0..1, so callers can pass a raw elapsed fraction. back and elastic overshoot
//           past 1 on purpose. An unknown name is an error in every port: EaseFromName and EaseByName
//           return an unset TOptional. Matches tools/golden_vectors.py (EASES), checked against
//           data/golden/juice.json. Formulas: easings.net.
//
// Pseudocode:
//   Ease(kind, t) = curve(kind)(clamp(t, 0, 1))
//   EaseFromName  = the enum whose snake_case name matches exactly, else unset
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

enum class EGameKitEase : uint8
{
	Linear,
	InQuad,
	OutQuad,
	InOutQuad,
	InCubic,
	OutCubic,
	InOutCubic,
	InSine,
	OutSine,
	InOutSine,
	InBack,
	OutBack,
	OutElastic,
	OutBounce,
};

namespace GameKit
{
	// ---- Curve constants (easings.net) ----
	inline constexpr double EaseBackC1 = 1.70158;               // back overshoot
	inline constexpr double EaseBackC3 = EaseBackC1 + 1.0;
	inline constexpr double EaseElasticC4 = 2.0 * UE_DOUBLE_PI / 3.0;
	inline constexpr double EaseBounceN1 = 7.5625;
	inline constexpr double EaseBounceD1 = 2.75;

	/** The data-file name of each curve, in enum order. */
	inline constexpr const TCHAR* EaseNames[] = {
		TEXT("linear"), TEXT("in_quad"), TEXT("out_quad"), TEXT("in_out_quad"), TEXT("in_cubic"), TEXT("out_cubic"),
		TEXT("in_out_cubic"), TEXT("in_sine"), TEXT("out_sine"), TEXT("in_out_sine"), TEXT("in_back"), TEXT("out_back"),
		TEXT("out_elastic"), TEXT("out_bounce"),
	};

	inline double EaseOutBounce(double T)
	{
		if (T < 1.0 / EaseBounceD1)
		{
			return EaseBounceN1 * T * T;
		}
		if (T < 2.0 / EaseBounceD1)
		{
			T -= 1.5 / EaseBounceD1;
			return EaseBounceN1 * T * T + 0.75;
		}
		if (T < 2.5 / EaseBounceD1)
		{
			T -= 2.25 / EaseBounceD1;
			return EaseBounceN1 * T * T + 0.9375;
		}
		T -= 2.625 / EaseBounceD1;
		return EaseBounceN1 * T * T + 0.984375;
	}

	/** The eased value of T (clamped to 0..1) on the given curve. */
	inline double Ease(EGameKitEase Kind, double T)
	{
		T = FMath::Clamp(T, 0.0, 1.0);
		switch (Kind)
		{
		case EGameKitEase::Linear:     return T;
		case EGameKitEase::InQuad:     return T * T;
		case EGameKitEase::OutQuad:    return 1.0 - (1.0 - T) * (1.0 - T);
		case EGameKitEase::InOutQuad:  return T < 0.5 ? 2.0 * T * T : 1.0 - FMath::Square(-2.0 * T + 2.0) / 2.0;
		case EGameKitEase::InCubic:    return T * T * T;
		case EGameKitEase::OutCubic:   return 1.0 - FMath::Cube(1.0 - T);
		case EGameKitEase::InOutCubic: return T < 0.5 ? 4.0 * T * T * T : 1.0 - FMath::Cube(-2.0 * T + 2.0) / 2.0;
		case EGameKitEase::InSine:     return 1.0 - FMath::Cos(T * UE_DOUBLE_PI / 2.0);
		case EGameKitEase::OutSine:    return FMath::Sin(T * UE_DOUBLE_PI / 2.0);
		case EGameKitEase::InOutSine:  return -(FMath::Cos(UE_DOUBLE_PI * T) - 1.0) / 2.0;
		case EGameKitEase::InBack:     return EaseBackC3 * T * T * T - EaseBackC1 * T * T;
		case EGameKitEase::OutBack:    return 1.0 + EaseBackC3 * FMath::Cube(T - 1.0) + EaseBackC1 * FMath::Square(T - 1.0);
		case EGameKitEase::OutElastic:
			if (T <= 0.0)
			{
				return 0.0;
			}
			if (T >= 1.0)
			{
				return 1.0;
			}
			return FMath::Pow(2.0, -10.0 * T) * FMath::Sin((T * 10.0 - 0.75) * EaseElasticC4) + 1.0;
		case EGameKitEase::OutBounce:  return EaseOutBounce(T);
		}
		return T;
	}

	/** The curve with this exact name ("out_back"), or unset for an unknown name. */
	inline TOptional<EGameKitEase> EaseFromName(const FString& Name)
	{
		for (int32 I = 0; I < static_cast<int32>(UE_ARRAY_COUNT(EaseNames)); ++I)
		{
			if (Name.Equals(EaseNames[I], ESearchCase::CaseSensitive))
			{
				return static_cast<EGameKitEase>(I);
			}
		}
		return {};
	}

	/** Ease() by curve name; unset for an unknown name (log it: a typo in a data file). */
	inline TOptional<double> EaseByName(const FString& Name, double T)
	{
		const TOptional<EGameKitEase> Kind = EaseFromName(Name);
		if (!Kind.IsSet())
		{
			return {};
		}
		return Ease(Kind.GetValue(), T);
	}
}
