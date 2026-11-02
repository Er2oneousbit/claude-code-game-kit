// ---------------------------------------------------------------------------
// GameKitMusicDirector.h
// Purpose : The adaptive-music rules of data/music.json: the sample grid, loop points, where playback is, the next
//           beat / bar / phrase / loop end, which transition rule applies, and the plan for a change of track (when,
//           fade, stinger, entry point). Plain C++; a player (MetaSounds, a Quartz clock, your own) carries it out.
// Usage   : FGameKitMusicDirector Music(MusicObject);               // data/music.json parsed (GameKit::Json::Parse)
//           const FGameKitMusicPlan P = Music.Plan(TEXT("explore"), Since, Entry, TEXT("combat"), Now);   // samples
//           P.SwitchAt, P.FromStopAt, P.ToStartAt, P.ToOffset, P.Stinger, P.StingerAt
// Notes   : A port of tools/audio/wavesmith/music.py (the reference); data/golden/music.json must come out exactly
//           (integers, tolerance 0; GameKitGoldenTests.cpp). Beat k starts at floor(k * 60 * rate / bpm + 0.5),
//           computed in the same order as the reference so every engine lands on the same sample; FMath::RoundToDouble
//           is not the rule. In Unreal, a Quartz clock (UQuartzSubsystem) can start sounds on a sample: convert a
//           plan's samples to its time with the music's sample rate.
//
// Pseudocode:
//   Position: p = now - since + entry; past the loop end -> wrap into [loop start, loop end)
//   Plan: rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
//         -> SwitchAt = now + (boundary - p); stinger -> the target enters after the stinger's bars
//         -> sync (same bpm and meter) -> enter at the same place in the bar
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitJson.h"

namespace GameKit::Audio
{
	/** First sample of beat K: floor(K * 60 * Rate / Bpm + 0.5), in the reference's operation order. */
	inline int64 BeatSample(double K, double Bpm, double Rate)
	{
		return static_cast<int64>(FMath::FloorToDouble(K * 60 * Rate / Bpm + 0.5));
	}
}

struct FGameKitMusicTrack
{
	double Bpm = 120.0;
	int32 BeatsPerBar = 4;
	int32 Bars = 1;
	int32 LoopStartBar = 0;
};

struct FGameKitMusicRule
{
	FString From, To;
	FString Quantize = TEXT("bar");   // immediate | beat | bar | phrase | loop_end
	double FadeMs = 0.0;
	bool bSync = false;
	TOptional<FString> Stinger;
	int32 PhraseBars = 4;
};

struct FGameKitMusicPlan
{
	int64 SwitchAt = 0, FromStopAt = 0, Fade = 0, ToOffset = 0, ToStartAt = 0;
	TOptional<FString> Stinger;
	TOptional<int64> StingerAt;
};

class FGameKitMusicDirector
{
public:
	explicit FGameKitMusicDirector(const TSharedPtr<FJsonObject>& M)
	{
		using namespace GameKit::Json;
		Rate = GetNumber(M, TEXT("sample_rate"), 44100.0);
		if (const TSharedPtr<FJsonObject> Tracks = FindObject(M, TEXT("tracks")))
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Tracks->Values)
			{
				if (!Is(Pair.Value, EJson::Object)) { continue; }
				const TSharedPtr<FJsonObject> T = Pair.Value->AsObject();
				FGameKitMusicTrack Track;
				Track.Bpm = GetNumber(T, TEXT("bpm"), 120.0);
				Track.BeatsPerBar = static_cast<int32>(GetNumber(T, TEXT("beats_per_bar"), 4.0));
				Track.Bars = static_cast<int32>(GetNumber(T, TEXT("bars"), 1.0));
				Track.LoopStartBar = static_cast<int32>(GetNumber(T, TEXT("loop_start_bar"), 0.0));
				TracksByName.Add(Pair.Key, Track);
			}
		}
		if (const TSharedPtr<FJsonObject> Stingers = FindObject(M, TEXT("stingers")))
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Stingers->Values)
			{
				if (Is(Pair.Value, EJson::Object)) { StingerBars.Add(Pair.Key, GetNumber(Pair.Value->AsObject(), TEXT("bars"), 1.0)); }
			}
		}
		if (const TSharedPtr<FJsonObject> D = FindObject(M, TEXT("default_transition"))) { Default = ReadRule(D, FGameKitMusicRule()); }
		const TSharedPtr<FJsonValue> Rules = Find(M, TEXT("transitions"));
		if (Is(Rules, EJson::Array))
		{
			for (const TSharedPtr<FJsonValue>& R : Rules->AsArray())
			{
				if (!Is(R, EJson::Object)) { continue; }
				FGameKitMusicRule Rule = ReadRule(R->AsObject(), Default);
				Rule.From = GetString(R->AsObject(), TEXT("from"), FString());
				Rule.To = GetString(R->AsObject(), TEXT("to"), FString());
				RulesInOrder.Add(Rule);
			}
		}
	}

	const FGameKitMusicTrack* FindTrack(const FString& Name) const { return TracksByName.Find(Name); }

	int64 BarSample(int32 B, const FGameKitMusicTrack& T) const { return GameKit::Audio::BeatSample(static_cast<double>(B) * T.BeatsPerBar, T.Bpm, Rate); }

	/** The bar that contains Sample, exact on the rounded grid. */
	int32 BarIndexAt(int64 Sample, const FGameKitMusicTrack& T) const
	{
		int32 B = static_cast<int32>(FMath::FloorToDouble(static_cast<double>(Sample) * T.Bpm / (60 * Rate * T.BeatsPerBar)));
		while (BarSample(B + 1, T) <= Sample) { ++B; }
		while (B > 0 && BarSample(B, T) > Sample) { --B; }
		return B;
	}

	void LoopPoints(const FGameKitMusicTrack& T, int64& OutStart, int64& OutEnd) const
	{
		OutStart = BarSample(T.LoopStartBar, T);
		OutEnd = BarSample(T.Bars, T);
	}

	int64 Position(const FGameKitMusicTrack& T, int64 Since, int64 NowSample, int64 Entry = 0) const
	{
		int64 P = NowSample - Since + Entry;
		int64 Start, End;
		LoopPoints(T, Start, End);
		if (P >= End) { P = Start + (P - Start) % (End - Start); }
		return P;
	}

	int64 NextBoundary(const FGameKitMusicTrack& T, int64 P, const FString& Quantize, int32 PhraseBars) const
	{
		if (Quantize == TEXT("immediate")) { return P; }
		int64 Start, End;
		LoopPoints(T, Start, End);
		if (Quantize == TEXT("loop_end")) { return End; }
		const int32 Step = Quantize == TEXT("beat") ? 1 : Quantize == TEXT("bar") ? T.BeatsPerBar : T.BeatsPerBar * PhraseBars;
		int64 K = static_cast<int64>(FMath::FloorToDouble(static_cast<double>(P) * T.Bpm / (60 * Rate)));
		while (GameKit::Audio::BeatSample(static_cast<double>(K), T.Bpm, Rate) < P) { ++K; }
		while (K % Step != 0) { ++K; }
		return FMath::Min(GameKit::Audio::BeatSample(static_cast<double>(K), T.Bpm, Rate), End);
	}

	/** Exact pair, then from "*", then to "*", then default_transition, then the built-in default. */
	FGameKitMusicRule RuleFor(const FString& From, const FString& To) const
	{
		const TPair<FString, FString> Wants[] = {{From, To}, {TEXT("*"), To}, {From, TEXT("*")}};
		for (const TPair<FString, FString>& Want : Wants)
		{
			for (const FGameKitMusicRule& R : RulesInOrder)
			{
				if (R.From.Equals(Want.Key, ESearchCase::CaseSensitive) && R.To.Equals(Want.Value, ESearchCase::CaseSensitive)) { return R; }
			}
		}
		return Default;
	}

	/** When and how to change from track From (playing since Since from offset Entry) to To, asked at NowSample. */
	FGameKitMusicPlan Plan(const FString& From, int64 Since, int64 Entry, const FString& To, int64 NowSample) const
	{
		FGameKitMusicPlan Out;
		const FGameKitMusicTrack* A = TracksByName.Find(From);
		const FGameKitMusicTrack* B = TracksByName.Find(To);
		if (!A || !B) { return Out; }   // unknown track: an empty plan (switch at 0); check FindTrack first
		const FGameKitMusicRule Rule = RuleFor(From, To);
		const int64 P = Position(*A, Since, NowSample, Entry);
		const int64 Boundary = NextBoundary(*A, P, Rule.Quantize, Rule.PhraseBars);
		Out.SwitchAt = NowSample + (Boundary - P);
		Out.Fade = static_cast<int64>(FMath::FloorToDouble(Rule.FadeMs * Rate / 1000 + 0.5));
		Out.FromStopAt = Out.SwitchAt + Out.Fade;
		Out.ToStartAt = Out.SwitchAt;
		Out.Stinger = Rule.Stinger;
		if (Rule.Stinger.IsSet())
		{
			const double* Bars = StingerBars.Find(Rule.Stinger.GetValue());
			Out.StingerAt = Out.SwitchAt;
			Out.ToStartAt = Out.SwitchAt + GameKit::Audio::BeatSample((Bars ? *Bars : 1.0) * B->BeatsPerBar, B->Bpm, Rate);
		}
		else if (Rule.bSync && A->Bpm == B->Bpm && A->BeatsPerBar == B->BeatsPerBar)
		{
			Out.ToOffset = Boundary - BarSample(BarIndexAt(Boundary, *A), *A);
		}
		return Out;
	}

private:
	/** A rule's fields over a base (the file's default_transition, itself over the built-in default). */
	static FGameKitMusicRule ReadRule(const TSharedPtr<FJsonObject>& R, FGameKitMusicRule Base)
	{
		using namespace GameKit::Json;
		Base.Quantize = GetString(R, TEXT("quantize"), Base.Quantize);
		Base.FadeMs = GetNumber(R, TEXT("fade_ms"), Base.FadeMs);
		Base.bSync = GetBool(R, TEXT("sync"), Base.bSync);
		Base.PhraseBars = static_cast<int32>(GetNumber(R, TEXT("phrase_bars"), Base.PhraseBars));
		const TSharedPtr<FJsonValue> S = Find(R, TEXT("stinger"));
		if (S.IsValid())
		{
			if (Is(S, EJson::String)) { Base.Stinger = S->AsString(); }
			else { Base.Stinger.Reset(); }   // an explicit null clears an inherited stinger
		}
		return Base;
	}

	double Rate = 44100.0;
	TMap<FString, FGameKitMusicTrack> TracksByName;
	TMap<FString, double> StingerBars;
	TArray<FGameKitMusicRule> RulesInOrder;
	FGameKitMusicRule Default;
};

// {{FOOTER}}
