// ---------------------------------------------------------------------------
// GameKitAudioAccess.h
// Purpose : Audio accessibility rules: which settings slider turns which bus of data/audio_events.json up or down
//           (never twice down one branch), and which arrow a directional caption gets when its sound is off screen.
// Usage   : const TMap<FString, double> Gains = GameKit::Audio::UserBusGains(EventsBuses, SettingsAudio);   // 0..1
//           const int32 K = GameKit::Audio::CaptionDirection(Dx, Dy, HalfW, HalfH);   // -1 on screen, else 0..7
//           if (K >= 0) { draw GameKit::Audio::CaptionArrows[K] beside the caption }
// Notes   : A port of tools/audio/wavesmith/access.py (the reference); data/golden/access.json must come out the same.
//           Sliders are linear 0..1; a missing or non-numeric one counts as 1 and others clamp. Parents default to
//           "master"; a cycle stops after one step per bus. Directions: screen y grows downwards (project the
//           sound's world position to the viewport first), -1 while it is inside the view (edges included), else
//           k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, clockwise from the right. FMath::RoundToInt is not
//           the rule. Bus names compare case-sensitively, like the reference.
//
// Pseudocode:
//   gains: for each bus: slider = SliderForBus[bus]; a parent with the same slider -> 1; none -> 1; else clamp
//   direction: inside the half sizes -> -1; else k from atan2
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitJson.h"

namespace GameKit::Audio
{
	/** Bus name -> settings slider. Edit it when your audio_events.json uses other bus names. */
	inline const TCHAR* SliderForBus(const FString& Bus)
	{
		static const TCHAR* const Pairs[][2] = {{TEXT("master"), TEXT("master")}, {TEXT("music"), TEXT("music")},
		                                        {TEXT("sfx"), TEXT("sfx")},       {TEXT("ambience"), TEXT("sfx")},
		                                        {TEXT("ui"), TEXT("ui")},         {TEXT("dialogue"), TEXT("voice")},
		                                        {TEXT("voice"), TEXT("voice")}};
		for (const auto& P : Pairs)
		{
			if (Bus.Equals(P[0], ESearchCase::CaseSensitive)) { return P[1]; }
		}
		return nullptr;
	}

	/** Clockwise from the right (y down): right, down-right, down, down-left, left, up-left, up, up-right. */
	inline const TCHAR* const CaptionArrows[8] = {TEXT("→"), TEXT("↘"), TEXT("↓"), TEXT("↙"),
	                                              TEXT("←"), TEXT("↖"), TEXT("↑"), TEXT("↗")};

	/** A slider's value: 1 when missing or not a number, else clamped to 0..1. */
	inline double SliderValue(const TSharedPtr<FJsonObject>& Sliders, const TCHAR* Name)
	{
		const TSharedPtr<FJsonValue> V = GameKit::Json::Find(Sliders, Name);
		if (!GameKit::Json::Is(V, EJson::Number)) { return 1.0; }
		const double X = V->AsNumber();
		return FMath::IsFinite(X) ? FMath::Clamp(X, 0.0, 1.0) : 1.0;
	}

	/** {bus: linear gain} from the player's sliders, a slider never applied twice down one branch. */
	inline TMap<FString, double> UserBusGains(const TSharedPtr<FJsonObject>& Buses, const TSharedPtr<FJsonObject>& Sliders)
	{
		TMap<FString, double> Out;
		if (!Buses.IsValid()) { return Out; }
		auto ParentOf = [&Buses](const FString& B) -> TOptional<FString>
		{
			const TSharedPtr<FJsonObject> O = GameKit::Json::FindObject(Buses, B);
			const TSharedPtr<FJsonValue> P = GameKit::Json::Find(O, TEXT("parent"));
			if (GameKit::Json::Is(P, EJson::String)) { return P->AsString(); }
			if (B.Equals(TEXT("master"), ESearchCase::CaseSensitive)) { return TOptional<FString>(); }
			return FString(TEXT("master"));
		};
		const int32 Count = Buses->Values.Num();
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Buses->Values)
		{
			const TCHAR* Slider = SliderForBus(Pair.Key);
			bool bInherited = false;
			TOptional<FString> P = ParentOf(Pair.Key);
			for (int32 N = 0; P.IsSet() && N < Count; ++N, P = ParentOf(P.GetValue()))
			{
				const TCHAR* PS = SliderForBus(P.GetValue());
				if (Slider && PS && FCString::Strcmp(Slider, PS) == 0) { bInherited = true; }
			}
			Out.Add(Pair.Key, (!Slider || bInherited) ? 1.0 : SliderValue(Sliders, Slider));
		}
		return Out;
	}

	/** -1 while the source is inside the view (edges included), else 0..7 clockwise from the right. */
	inline int32 CaptionDirection(double Dx, double Dy, double HalfW, double HalfH)
	{
		if (!FMath::IsFinite(Dx) || !FMath::IsFinite(Dy)) { return -1; }
		if (FMath::Abs(Dx) <= HalfW && FMath::Abs(Dy) <= HalfH) { return -1; }
		const int64 K = static_cast<int64>(FMath::FloorToDouble(FMath::Atan2(Dy, Dx) / (UE_DOUBLE_PI / 4) + 0.5));
		return static_cast<int32>(((K % 8) + 8) % 8);
	}

	inline FString CaptionArrow(double Dx, double Dy, double HalfW, double HalfH)
	{
		const int32 K = CaptionDirection(Dx, Dy, HalfW, HalfH);
		return K < 0 ? FString() : FString(CaptionArrows[K]);
	}
}

// {{FOOTER}}
