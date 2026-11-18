// ---------------------------------------------------------------------------
// GameKitPlatform.h
// Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
//           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null backend
//           (it records every call); the Steam adapter (GameKitShellUI's GameKitPlatformSteam.cpp, compiled only
//           when the game's Build.cs turns GAMEKIT_STEAM on) replaces it in a store build. Checked against
//           data/golden/platform.json (every case, GameKit.Golden.Platform).
// Usage   : GameKit::FPlatformService& P = Shell->Model()->Platform();
//           P.Unlock(TEXT("first_win"));  P.AddStat(TEXT("enemies_defeated"), 1);  P.Flush();   // at checkpoints
//           P.SetPresence(TEXT("status"), TEXT("In the crypt"));  P.Saved(TEXT("save_1.json"));
//           pure parts: AchievementsLoad(Text), CloudPartition(Path), OverlayAction(bActive, Screen),
//           GameKit::FPlatformRules Rules(Defs, &Backend, bOnline, Cloud), PlatformStateLoad(Defs, Text)
// Notes   : Values are Unreal JSON (TSharedPtr<FJsonValue>) and calls are JSON arrays (["set_stat", "coins", 7]),
//           so tests compare them with the vectors as they are. SetStat takes a JSON value so a string or a bool is
//           refused by the rules, never by a cast. Every id compare is case-sensitive (FString's == is not, and
//           FJsonObject keys are case-insensitive: two stats that differ only in case are one stat here). With no
//           data/achievements.json every call is "unknown" and nothing is written, so a game without achievements
//           runs exactly as before. The state file is a cache, written atomically only when it changed.
//
// Pseudocode:
//   rules op -> update local state -> online: send calls to the backend one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   service: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): TakeStoreFailure and StoreFailed: a store that failed
//           after it was accepted (Steam's UserStatsStored) goes back on the queue
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

namespace GameKit
{
	// ---- Constants (the same in every engine: data/golden/platform.json "names and limits") ----
	inline constexpr const TCHAR* PlatformFormat = TEXT("platform_state");
	inline constexpr int32 PlatformStateVersion = 1;
	inline constexpr const TCHAR* PlatformStateFile = TEXT("platform_state.json");
	inline constexpr const TCHAR* AchievementsFile = TEXT("data/achievements.json");   // under the project folder
	inline constexpr int32 PlatformIdMax = 64;
	inline constexpr int32 PresenceMaxKeys = 30;                 // Steam's rich presence limits (verify)
	inline constexpr int32 PresenceMaxValueBytes = 255;
	inline constexpr const TCHAR* CloudMode = TEXT("auto");      // "auto" (Steam Auto-Cloud, preferred) or "api"
	GAMEKITSHELL_API const TArray<FString>& PlatformStatTypes();
	GAMEKITSHELL_API const TArray<FString>& PlatformCloudModes();
	GAMEKITSHELL_API const TArray<FString>& CloudLocalNames();
	GAMEKITSHELL_API const TArray<FString>& CloudLocalSuffixes();
	GAMEKITSHELL_API const TArray<FString>& CloudLocalDirs();
	GAMEKITSHELL_API const TArray<FString>& OverlayPauseScreens();

	/** An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first. */
	GAMEKITSHELL_API bool PlatformIdOk(const TSharedPtr<FJsonValue>& Value);
	/** data/achievements.json text (unset or "" = no file) -> the definitions; OutProblems counts dropped entries. */
	GAMEKITSHELL_API TSharedRef<FJsonObject> AchievementsLoad(const TOptional<FString>& Text, int32& OutProblems);
	/** Which user-data file syncs: "cloud" or "local" (ASCII-only folding, never a locale's lowercase). */
	GAMEKITSHELL_API FString CloudPartition(const FString& Path);
	/** The store overlay opened (active) or closed over Screen: "pause" opens the pause menu; closing never resumes. */
	GAMEKITSHELL_API FString OverlayAction(bool bActive, const FString& Screen);

	/** The backend interface (PLATFORM.md section 4). Send returns false only for a store_stats the store refused. */
	class GAMEKITSHELL_API IPlatformBackend
	{
	public:
		virtual ~IPlatformBackend() = default;
		virtual FString Name() const = 0;
		virtual bool Available() = 0;
		/** {"unlocked": [...], "stats": {...}} as the store holds them. */
		virtual TSharedRef<FJsonObject> Remote() = 0;
		virtual bool Send(const TArray<TSharedPtr<FJsonValue>>& Call) = 0;
		/** Each frame: run the SDK's callbacks. Set to the new state when the store overlay opened or closed. */
		virtual TOptional<bool> Update() { return {}; }
		/** A store that failed after Send(["store_stats"]) returned true (Steam's UserStatsStored): its set_stat and
		 *  set_achievement calls, oldest first; unset when none. */
		virtual TOptional<TArray<TSharedPtr<FJsonValue>>> TakeStoreFailure() { return {}; }
	};

	/** The backend every game runs by default: records every call and keeps what a store would hold. */
	class GAMEKITSHELL_API FNullPlatformBackend : public IPlatformBackend
	{
	public:
		virtual FString Name() const override { return TEXT("null"); }
		virtual bool Available() override { return true; }
		virtual TSharedRef<FJsonObject> Remote() override;
		virtual bool Send(const TArray<TSharedPtr<FJsonValue>>& Call) override;
		TArray<TSharedPtr<FJsonValue>> PresenceList() const;   // [[key, value], ...] sorted

		TArray<TSharedPtr<FJsonValue>> Calls;
		TArray<FString> Unlocked;
		TArray<TPair<FString, TSharedPtr<FJsonValue>>> Stats;   // in the order first stored (case-sensitive ids)
		TArray<TPair<FString, FString>> Presence;
		TArray<FString> Cloud;
		int32 FailStores = 0;                                    // test hook: the next N store_stats fail

	private:
		TArray<FString> StagedUnlocks;
		TArray<TPair<FString, TSharedPtr<FJsonValue>>> StagedStats;
	};

	/** A status word (null for a test hook step) and the calls sent during the operation, in order. */
	struct FPlatformOut
	{
		TSharedPtr<FJsonValue> Out;
		TArray<TSharedPtr<FJsonValue>> Calls;
	};

	/** The rules (PLATFORM.md section 3). */
	class GAMEKITSHELL_API FPlatformRules
	{
	public:
		FPlatformRules(const TSharedRef<FJsonObject>& InDefs, IPlatformBackend* InBackend, bool bInOnline = false,
		               const FString& InCloud = TEXT("auto"));

		FPlatformOut Unlock(const FString& Id);
		FPlatformOut SetStat(const FString& Id, const TSharedPtr<FJsonValue>& Value);
		FPlatformOut AddStat(const FString& Id, const TSharedPtr<FJsonValue>& Delta);
		FPlatformOut Flush();
		FPlatformOut SetPresence(const TSharedPtr<FJsonValue>& Key, const TSharedPtr<FJsonValue>& Value);
		FPlatformOut ClearPresence();
		FPlatformOut Saved(const FString& Path);
		FPlatformOut Connect(const TSharedPtr<FJsonObject>& Remote);
		FPlatformOut Disconnect();
		FPlatformOut ResetAll();
		/** A store the backend accepted failed later: the same as a refused store_stats. The batch's stats and unlocks
		 *  are pending again and the layer is offline until Connect(). */
		FPlatformOut StoreFailed(const TArray<TSharedPtr<FJsonValue>>& Batch);

		/** What the state file holds (and what the golden steps compare). */
		TSharedRef<FJsonObject> State() const;
		/** Takes over PlatformStateLoad's state. */
		void Restore(const TSharedRef<FJsonObject>& InState);
		TArray<TSharedPtr<FJsonValue>> PresenceList() const;
		bool IsOnline() const { return bOnline; }
		void SetCloud(const FString& Mode) { Cloud = Mode; }
		const TSharedRef<FJsonObject>& Defs() const { return DefsObj; }
		const TArray<FString>& GetUnlocked() const { return Unlocked; }

		// ---- used by PlatformStateLoad ----
		TSharedPtr<FJsonObject> StatDef(const FString& Id) const;
		bool HasAchievement(const FString& Id) const;
		void SetStatValue(const FString& Id, double Value);
		TArray<FString> Unlocked;
		TArray<FString> PendingStats;
		TArray<FString> PendingUnlocks;
		TArray<FString> PendingCloud;

	private:
		void ResetLocal();
		bool Send(const TArray<TSharedPtr<FJsonValue>>& Call);
		FPlatformOut Done(const TCHAR* Word);
		void UnlockLocal(const FString& Id);
		bool Check(const FString& StatId, double Old, double Now, bool bNotify);
		const TCHAR* FlushInner();
		double StatValue(const FString& Id) const;

		TSharedRef<FJsonObject> DefsObj;
		TArray<TSharedPtr<FJsonObject>> StatDefs;
		TArray<TSharedPtr<FJsonObject>> AchDefs;
		IPlatformBackend* Backend;
		bool bOnline;
		FString Cloud;
		TArray<TPair<FString, double>> StatValues;     // definition order
		TArray<TPair<FString, FString>> Presence;      // kept sorted (case-sensitive)
		TArray<TSharedPtr<FJsonValue>> Sent;
	};

	/** platform_state.json text (unset or "" = no file) -> the state; OutProblems counts dropped entries. */
	GAMEKITSHELL_API TSharedRef<FJsonObject> PlatformStateLoad(const TSharedRef<FJsonObject>& Defs, const TOptional<FString>& Text,
	                                                           int32& OutProblems);

	/** The rules, the backend and the cached state file: what the shell owns (FGameKitShellModel::Platform()). */
	class GAMEKITSHELL_API FPlatformService
	{
	public:
		/** AchievementsText: data/achievements.json (unset = none). InBackend: null = a FNullPlatformBackend. */
		FPlatformService(const FString& DataDir, const TOptional<FString>& AchievementsText,
		                 TUniquePtr<IPlatformBackend> InBackend = nullptr, const FString& InCloud = CloudMode);

		bool IsActive() const { return bActive; }   // false without achievements: nothing is ever written
		FString Unlock(const FString& Id) { return After(Rules.Unlock(Id)); }
		FString SetStat(const FString& Id, double Value);
		FString AddStat(const FString& Id, double Delta);
		FString Flush() { return After(Rules.Flush()); }   // at checkpoints: level end, pause, quit
		FString SetPresence(const FString& Key, const FString& Value);
		FString ClearPresence() { return After(Rules.ClearPresence()); }
		FString Saved(const FString& Path) { return After(Rules.Saved(Path)); }
		FString Overlay(bool bOverlayActive, const FString& Screen) const { return OverlayAction(bOverlayActive, Screen); }
		/** The backend's callbacks; a store that failed late goes back on the queue, offline. The overlay's change. */
		TOptional<bool> Update();
		IPlatformBackend& GetBackend() { return *Backend; }
		FPlatformRules& GetRules() { return Rules; }
		/** What went wrong while loading or writing (the shell logs it). */
		TArray<FString> Problems;

	private:
		FString After(const FPlatformOut& R);
		void Persist();

		FString File;
		TUniquePtr<IPlatformBackend> Backend;
		FPlatformRules Rules;
		bool bActive = false;
		FString Last;
	};
}
