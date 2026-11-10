// ---------------------------------------------------------------------------
// GameKitShellReport.cpp
// Purpose : The log tail and crash files behind GameKitShellReport.h.
// Usage   : compiled into the GameKitShellUI module; the module starts the log tail and binds OnSystemError().
// Notes   : The tail is a ring of KeepLines strings behind a lock. The crash path (OnSystemError, on the crash
//           thread) only TryLocks: a crash inside the log device itself would otherwise wait forever.
//
// Pseudocode:
//   log line -> ring (oldest dropped) ; LogTail(n) = the newest n, oldest first
//   WriteCrash(error): target set? -> crashes/crash_<stamp>.txt (unique) = CrashText(target, error, tail, time)
//     -> write -> log CRASH_WRITTEN <path>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitShellReport.h"

#include "GameKitShellLog.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/OutputDevice.h"
#include "Misc/OutputDeviceRedirector.h"
#include "Misc/Paths.h"

namespace GameKit::ShellReport
{
	namespace
	{
		FCriticalSection TailLock;
		TArray<FString> Ring;                // the newest KeepLines log lines
		int32 RingNext = 0;                  // where the next line goes once the ring is full

		FCriticalSection TargetLock;
		const void* TargetOwner = nullptr;
		FCrashTarget Target;

		/** Every logged line into the ring (any thread). */
		class FTailDevice final : public FOutputDevice
		{
		public:
			virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
			{
				AddLogLine(FString::Printf(TEXT("%s: %s: %s"), *Category.ToString(), ::ToString(Verbosity), V));
			}
			virtual bool CanBeUsedOnAnyThread() const override { return true; }
			virtual bool CanBeUsedOnMultipleThreads() const override { return true; }
			virtual bool IsMemoryOnly() const override { return true; }
		};

		TUniquePtr<FTailDevice> Device;

		/** The newest N lines of the ring, oldest first; the caller holds TailLock. */
		FString TailLocked(int32 Lines)
		{
			TArray<FString> Out;
			const int32 Count = Ring.Num();
			const int32 Take = FMath::Clamp(Lines, 0, Count);
			const int32 Oldest = Count < KeepLines ? 0 : RingNext;   // a full ring starts at its next slot
			for (int32 I = Count - Take; I < Count; ++I)
			{
				Out.Add(Ring[(Oldest + I) % Count]);
			}
			return FString::Join(Out, TEXT("\n"));
		}
	}

	void StartLogTail()
	{
		if (!Device.IsValid() && GLog)
		{
			Device = MakeUnique<FTailDevice>();
			GLog->AddOutputDevice(Device.Get());
		}
	}

	void StopLogTail()
	{
		if (Device.IsValid())
		{
			if (GLog)
			{
				GLog->RemoveOutputDevice(Device.Get());
			}
			Device.Reset();
		}
	}

	void AddLogLine(const FString& Line)
	{
		FScopeLock Lock(&TailLock);
		if (Ring.Num() < KeepLines)
		{
			Ring.Add(Line.TrimEnd());
		}
		else
		{
			Ring[RingNext] = Line.TrimEnd();
			RingNext = (RingNext + 1) % KeepLines;
		}
	}

	FString LogTail(int32 Lines)
	{
		FScopeLock Lock(&TailLock);
		return TailLocked(Lines);
	}

	void SetCrashTarget(const void* Owner, const FCrashTarget& InTarget)
	{
		FScopeLock Lock(&TargetLock);
		TargetOwner = Owner;
		Target = InTarget;
	}

	void UpdateCrashSettings(const void* Owner, const FString& SettingsJson)
	{
		FScopeLock Lock(&TargetLock);
		if (TargetOwner == Owner)
		{
			Target.SettingsJson = SettingsJson;
		}
	}

	void ClearCrashTarget(const void* Owner)
	{
		FScopeLock Lock(&TargetLock);
		if (TargetOwner == Owner)
		{
			TargetOwner = nullptr;
			Target = FCrashTarget();
		}
	}

	bool HasCrashTarget()
	{
		FScopeLock Lock(&TargetLock);
		return TargetOwner != nullptr;
	}

	FString CrashText(const FCrashTarget& T, const FString& Error, const FString& Tail, const FString& Time)
	{
		TArray<FString> Lines;
		Lines.Add((T.GameName.IsEmpty() ? FString(TEXT("game")) : T.GameName) + TEXT(" crash report"));
		Lines.Add(TEXT("version: ") + (T.Version.IsEmpty() ? FString(TEXT("unknown")) : T.Version));
		Lines.Add(TEXT("time: ") + Time);
		Lines.Add(TEXT("engine: ") + FEngineVersion::Current().ToString());
		Lines.Add(TEXT("os: ") + FPlatformMisc::GetOSVersion());
		Lines.Add(FString());
		Lines.Add(TEXT("error: ") + (Error.IsEmpty() ? FString(TEXT("(none given: see the log tail)")) : Error.TrimStartAndEnd()));
		Lines.Add(FString());
		Lines.Add(TEXT("log tail:"));
		Lines.Add(Tail.IsEmpty() ? FString(TEXT("(no log lines)")) : Tail);
		Lines.Add(FString());
		Lines.Add(TEXT("settings:"));
		Lines.Add(T.SettingsJson.IsEmpty() ? FString(TEXT("(unknown)")) : T.SettingsJson);
		return FString::Join(Lines, TEXT("\n")) + TEXT("\n");
	}

	FString Stamp()
	{
		return FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S"));
	}

	FString UniquePath(const FString& Dir, const FString& Prefix, const FString& InStamp, const FString& Ext)
	{
		FString Path = FPaths::Combine(Dir, Prefix + InStamp + Ext);
		for (int32 N = 2; N <= MaxSameSecond && (FPaths::FileExists(Path) || FPaths::DirectoryExists(Path)); ++N)
		{
			Path = FPaths::Combine(Dir, FString::Printf(TEXT("%s%s_%d%s"), *Prefix, *InStamp, N, *Ext));
		}
		return Path;
	}

	FString WriteCrash(const FString& Error)
	{
		FCrashTarget T;
		{
			if (!TargetLock.TryLock())
			{
				return FString();   // the crashed thread holds it: no report rather than a hang
			}
			const bool bArmed = TargetOwner != nullptr;
			T = Target;
			TargetLock.Unlock();
			if (!bArmed || T.DataDir.IsEmpty())
			{
				return FString();
			}
		}
		FString Tail;
		if (TailLock.TryLock())
		{
			Tail = TailLocked(CrashTailLines);
			TailLock.Unlock();
		}
		const FString Dir = FPaths::Combine(T.DataDir, CrashFolder);
		IFileManager::Get().MakeDirectory(*Dir, /*Tree*/ true);
		const FString Path = FPaths::ConvertRelativePathToFull(UniquePath(Dir, TEXT("crash_"), Stamp(), TEXT(".txt")));
		const FString Text = CrashText(T, Error, Tail, FDateTime::UtcNow().ToIso8601());
		if (!FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
		{
			UE_LOG(LogGameKitShell, Error, TEXT("crash report not written: %s"), *Path);
			return FString();
		}
		UE_LOG(LogGameKitShell, Display, TEXT("CRASH_WRITTEN %s"), *Path);
		return Path;
	}

	void OnSystemError()
	{
		// GErrorHist holds a fatal log line or an assert; a crash (an access violation) leaves its text in the other one
		const FString Error = GErrorHist[0] ? FString(GErrorHist) : FString(GErrorExceptionDescription);
		WriteCrash(Error);   // the engine's GLog->Panic() right after this flushes CRASH_WRITTEN to the log file
	}
}

// {{FOOTER}}
