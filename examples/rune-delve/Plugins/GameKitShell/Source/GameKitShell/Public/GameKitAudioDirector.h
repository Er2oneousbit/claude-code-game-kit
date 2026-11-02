// ---------------------------------------------------------------------------
// GameKitAudioDirector.h
// Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
//           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
//           dialogue ducks the music and ambience buses. Data comes from data/audio_events.json. Plain C++.
// Usage   : FGameKitAudioDirector Director(EventsObject);            // {"seed", "events", "ducking"} (GameKit::Json::Parse)
//           const FGameKitPlayDecision D = Director.Play(TEXT("step_stone"), NowMs);
//           if (D.Result == EGameKitPlayResult::Played) { spawn the sound: Files[D.Variant], pitch D.PitchRatio, D.GainDb }
//           each Tick: for (const TPair<FString, double>& Bus : Director.Duck(NowMs)) set that bus's duck in dB
// Notes   : A port of tools/audio/wavesmith/audio_events.py (the reference); every step of data/golden/audio.json
//           must come out the same (GameKitGoldenTests.cpp). The random source is Park-Miller in int64 (exact, no
//           bit operations), drawn in a fixed order (variant, pitch, volume) and never by a rejected play. Each
//           event needs "lengths_ms" (one per file, from the loaded sounds' durations). Calls must come in time
//           order; an earlier time is ignored with a warning in the result (Played is never returned for it).
//
// Pseudocode:
//   Play(e, t) -> drop finished voices -> cooldown? Cooldown -> at max_voices: steal oldest or Capped
//              -> variant by pick rule -> pitch -> volume -> new voice (ends at t + length / pitch ratio)
//   Duck(t)    -> per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitJson.h"

namespace GameKit::Audio
{
	// ---- Tunables ----
	inline constexpr int32 DefaultMaxVoices = 8;
	inline constexpr int64 ParkMillerM = 2147483647;   // 2^31 - 1
	inline constexpr int64 ParkMillerA = 16807;

	/** Park-Miller minimal standard generator: exact in int64, so every engine draws the same numbers. */
	struct FParkMiller
	{
		int64 S = 1;
		explicit FParkMiller(int64 Seed = 1)
		{
			S = ((Seed % ParkMillerM) + ParkMillerM) % ParkMillerM;
			if (S == 0) { S = 1; }
		}
		double Next()
		{
			S = (S * ParkMillerA) % ParkMillerM;
			return static_cast<double>(S - 1) / static_cast<double>(ParkMillerM - 1);
		}
	};

	/** Per-event seed: a polynomial hash of the ASCII event id mixed with the file's seed (never 0). */
	inline int64 EventSeed(const FString& EventId, int64 GlobalSeed)
	{
		int64 H = 0;
		for (const TCHAR C : EventId) { H = (H * 31 + static_cast<int64>(C)) % ParkMillerM; }
		const int64 G = ((GlobalSeed % ParkMillerM) + ParkMillerM) % ParkMillerM;
		const int64 S = (H + G * 7919) % ParkMillerM;
		return S == 0 ? 1 : S;
	}
}

enum class EGameKitPlayResult : uint8 { Played, Cooldown, Capped };

struct FGameKitPlayDecision
{
	EGameKitPlayResult Result = EGameKitPlayResult::Played;
	int32 Variant = 0;
	double PitchSemitones = 0.0, PitchRatio = 1.0, GainDb = 0.0;
	int32 Voice = 0;
	TOptional<int32> Stolen;   // the voice stopped to make room, if any
	double EndsMs = 0.0;
};

class FGameKitAudioDirector
{
public:
	explicit FGameKitAudioDirector(const TSharedPtr<FJsonObject>& Params)
	{
		using namespace GameKit::Json;
		const int64 Seed = static_cast<int64>(GetNumber(Params, TEXT("seed"), 1.0));
		if (const TSharedPtr<FJsonObject> Events = FindObject(Params, TEXT("events")))
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Events->Values)
			{
				if (!Is(Pair.Value, EJson::Object)) { continue; }
				const TSharedPtr<FJsonObject> E = Pair.Value->AsObject();
				FEvent Ev;
				Ev.Bus = GetString(E, TEXT("bus"), TEXT("sfx"));
				for (const TSharedPtr<FJsonValue>& L : ArrayOf(E, TEXT("lengths_ms"))) { Ev.LengthsMs.Add(L->AsNumber()); }
				Ev.Pick = GetString(E, TEXT("pick"), TEXT("random_no_repeat"));
				ReadRange(E, TEXT("pitch_semitones"), Ev.PitchLo, Ev.PitchHi);
				ReadRange(E, TEXT("volume_db"), Ev.VolLo, Ev.VolHi);
				Ev.MaxVoices = static_cast<int32>(GetNumber(E, TEXT("max_voices"), GameKit::Audio::DefaultMaxVoices));
				Ev.Steal = GetString(E, TEXT("steal"), TEXT("oldest"));
				Ev.CooldownMs = GetNumber(E, TEXT("cooldown_ms"), 0.0);
				EventsByName.Add(Pair.Key, Ev);
				Rng.Add(Pair.Key, GameKit::Audio::FParkMiller(GameKit::Audio::EventSeed(Pair.Key, Seed)));
			}
		}
		for (const TSharedPtr<FJsonValue>& R : ArrayOf(Params, TEXT("ducking")))
		{
			if (!Is(R, EJson::Object)) { continue; }
			const TSharedPtr<FJsonObject> O = R->AsObject();
			FDuckRule Rule;
			Rule.Trigger = GetString(O, TEXT("trigger"), FString());
			for (const TSharedPtr<FJsonValue>& T : ArrayOf(O, TEXT("targets"))) { Rule.Targets.Add(T->AsString()); }
			Rule.DepthDb = GetNumber(O, TEXT("depth_db"), 0.0);
			Rule.AttackMs = GetNumber(O, TEXT("attack_ms"), 0.0);
			Rule.ReleaseMs = GetNumber(O, TEXT("release_ms"), 0.0);
			Triggers.Add(Rule.Trigger);
			Ducking.Add(Rule);
			DuckGain.Add(0.0);
			DuckTime.Add(0.0);
		}
	}

	bool HasEvent(const FString& Name) const { return EventsByName.Contains(Name); }

	/** The decision for one play of Name at T (ms). An unknown event or an earlier time than the last call is Capped. */
	FGameKitPlayDecision Play(const FString& Name, double T)
	{
		FGameKitPlayDecision D;
		const FEvent* Ev = EventsByName.Find(Name);
		if (!Ev || T < Now)
		{
			D.Result = EGameKitPlayResult::Capped;
			return D;
		}
		Now = T;
		Voices.RemoveAll([T](const FVoice& V) { return V.End <= T; });
		if (Ev->CooldownMs != 0.0)
		{
			if (const double* Last = LastPlay.Find(Name); Last && T - *Last < Ev->CooldownMs)
			{
				D.Result = EGameKitPlayResult::Cooldown;
				return D;
			}
		}
		int32 Mine = 0;
		for (const FVoice& V : Voices) { Mine += V.Event == Name ? 1 : 0; }
		if (Mine >= Ev->MaxVoices)
		{
			if (Ev->Steal == TEXT("none"))
			{
				D.Result = EGameKitPlayResult::Capped;
				return D;
			}
			int32 Victim = INDEX_NONE;   // the oldest copy: earliest start, then lowest id
			for (int32 I = 0; I < Voices.Num(); ++I)
			{
				const FVoice& V = Voices[I];
				if (V.Event != Name) { continue; }
				if (Victim == INDEX_NONE || V.Start < Voices[Victim].Start || (V.Start == Voices[Victim].Start && V.Id < Voices[Victim].Id))
				{
					Victim = I;
				}
			}
			D.Stolen = Voices[Victim].Id;
			for (FVoice& H : History)
			{
				if (H.Id == Voices[Victim].Id) { H.End = T; }   // it stops now: the ducking envelope sees that edge
			}
			Voices.RemoveAt(Victim);
		}
		GameKit::Audio::FParkMiller& R = Rng.FindChecked(Name);
		const int32 Idx = PickVariant(Name, *Ev, R);
		const double Semis = Ev->PitchLo == Ev->PitchHi ? Ev->PitchLo : Ev->PitchLo + (Ev->PitchHi - Ev->PitchLo) * R.Next();
		const double Gain = Ev->VolLo == Ev->VolHi ? Ev->VolLo : Ev->VolLo + (Ev->VolHi - Ev->VolLo) * R.Next();
		const double Ratio = FMath::Pow(2.0, Semis / 12.0);
		const double Length = Ev->LengthsMs.IsValidIndex(Idx) ? Ev->LengthsMs[Idx] : 0.0;
		const FVoice Voice{NextId++, Name, Ev->Bus, T, T + Length / Ratio};
		Voices.Add(Voice);
		if (Triggers.Contains(Voice.Bus)) { History.Add(Voice); }
		LastPlay.Add(Name, T);
		LastVariant.Add(Name, Idx);
		D.Variant = Idx;
		D.PitchSemitones = Semis;
		D.PitchRatio = Ratio;
		D.GainDb = Gain;
		D.Voice = Voice.Id;
		D.EndsMs = Voice.End;
		return D;
	}

	/** Duck gain in dB per target bus at T (every rule advanced to T). An earlier time than the last call changes nothing. */
	TMap<FString, double> Duck(double T)
	{
		TMap<FString, double> Out;
		if (T < Now) { return Out; }
		Now = T;
		for (int32 I = 0; I < Ducking.Num(); ++I)
		{
			const FDuckRule& Rule = Ducking[I];
			TArray<const FVoice*> Mine;
			TArray<double> Edges;
			for (const FVoice& V : History)
			{
				if (V.Bus != Rule.Trigger) { continue; }
				Mine.Add(&V);
				for (const double E : {V.Start, V.End})
				{
					if (DuckTime[I] < E && E < T) { Edges.AddUnique(E); }
				}
			}
			Edges.Sort();
			Edges.Add(T);
			double Gain = DuckGain[I], At = DuckTime[I];
			for (const double Edge : Edges)
			{
				bool bActive = false;
				for (const FVoice* V : Mine) { bActive = bActive || (V->Start <= At && At < V->End); }
				Gain = Ramp(Gain, bActive, Rule, Edge - At);
				At = Edge;
			}
			DuckGain[I] = Gain;
			DuckTime[I] = T;
			for (const FString& Bus : Rule.Targets)
			{
				const double* Have = Out.Find(Bus);
				Out.Add(Bus, Have ? FMath::Min(*Have, Gain) : FMath::Min(0.0, Gain));
			}
		}
		// every rule now stands at T: voices that ended by then add no later edge (results unchanged)
		History.RemoveAll([T](const FVoice& V) { return V.End <= T; });
		return Out;
	}

private:
	struct FEvent
	{
		FString Bus;
		TArray<double> LengthsMs;
		FString Pick;
		double PitchLo = 0.0, PitchHi = 0.0, VolLo = 0.0, VolHi = 0.0;
		int32 MaxVoices = GameKit::Audio::DefaultMaxVoices;
		FString Steal;
		double CooldownMs = 0.0;
	};
	struct FDuckRule
	{
		FString Trigger;
		TArray<FString> Targets;
		double DepthDb = 0.0, AttackMs = 0.0, ReleaseMs = 0.0;
	};
	struct FVoice
	{
		int32 Id;
		FString Event, Bus;
		double Start, End;
	};

	static TArray<TSharedPtr<FJsonValue>> ArrayOf(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
	{
		const TSharedPtr<FJsonValue> V = GameKit::Json::Find(O, Key);
		return GameKit::Json::Is(V, EJson::Array) ? V->AsArray() : TArray<TSharedPtr<FJsonValue>>();
	}

	static void ReadRange(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, double& Lo, double& Hi)
	{
		const TArray<TSharedPtr<FJsonValue>> R = ArrayOf(O, Key);
		if (R.Num() == 2 && GameKit::Json::Is(R[0], EJson::Number) && GameKit::Json::Is(R[1], EJson::Number))
		{
			Lo = R[0]->AsNumber();
			Hi = R[1]->AsNumber();
		}
	}

	int32 PickVariant(const FString& Name, const FEvent& Ev, GameKit::Audio::FParkMiller& R)
	{
		const int32 N = Ev.LengthsMs.Num();
		const int32* LastPtr = LastVariant.Find(Name);
		const int32 Last = LastPtr ? *LastPtr : -1;
		if (N <= 1) { return 0; }
		if (Ev.Pick == TEXT("sequence")) { return (Last + 1) % N; }
		if (Ev.Pick == TEXT("random")) { return FMath::Min(static_cast<int32>(FMath::FloorToDouble(R.Next() * N)), N - 1); }
		if (Ev.Pick == TEXT("random_no_repeat"))
		{
			if (Last < 0) { return FMath::Min(static_cast<int32>(FMath::FloorToDouble(R.Next() * N)), N - 1); }
			const int32 K = FMath::Min(static_cast<int32>(FMath::FloorToDouble(R.Next() * (N - 1))), N - 2);
			return K >= Last ? K + 1 : K;
		}
		TArray<int32>& Bag = Bags.FindOrAdd(Name);   // shuffle: every file once per round
		if (Bag.IsEmpty())
		{
			for (int32 I = 0; I < N; ++I) { Bag.Add(I); }
			for (int32 I = N - 1; I > 0; --I)
			{
				const int32 J = FMath::Min(static_cast<int32>(FMath::FloorToDouble(R.Next() * (I + 1))), I);
				Bag.Swap(I, J);
			}
			if (Bag[0] == Last) { Bag.Swap(0, 1); }   // never the same file twice across a refill
		}
		const int32 Idx = Bag[0];
		Bag.RemoveAt(0);
		return Idx;
	}

	static double Ramp(double Gain, bool bActive, const FDuckRule& Rule, double Dt)
	{
		const double Depth = Rule.DepthDb;
		if (bActive)
		{
			if (Rule.AttackMs <= 0.0) { return Depth; }
			return FMath::Max(Depth, Gain + Depth / Rule.AttackMs * Dt);
		}
		if (Rule.ReleaseMs <= 0.0) { return 0.0; }
		return FMath::Min(0.0, Gain - Depth / Rule.ReleaseMs * Dt);
	}

	TMap<FString, FEvent> EventsByName;
	TMap<FString, GameKit::Audio::FParkMiller> Rng;
	TArray<FDuckRule> Ducking;
	TArray<double> DuckGain, DuckTime;   // per rule: gain in dB, time of the last update
	TSet<FString> Triggers;
	TArray<FVoice> Voices, History;
	TMap<FString, double> LastPlay;
	TMap<FString, int32> LastVariant;
	TMap<FString, TArray<int32>> Bags;
	int32 NextId = 1;
	double Now = 0.0;
};
