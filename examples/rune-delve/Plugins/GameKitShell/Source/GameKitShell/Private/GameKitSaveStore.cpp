// ---------------------------------------------------------------------------
// GameKitSaveStore.cpp
// Purpose : Implementation of the save envelope, migrations and the crash-safe store (see GameKitSaveStore.h).
// Usage   : compiled into the GameKitShell module; call through GameKitSaveStore.h.
// Notes   : SaveMigrations is the example chain from the kit's reference (v2 renamed hp to health, v3 added
//           the difficulty the game was started on). Replace it with your game's own steps; keep one step per
//           version and never edit a step that has shipped (old saves still need it). The .bak is a byte copy
//           of the previous file, so it is exactly what that build wrote.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitSaveStore.h"

#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "GenericPlatform/GenericPlatformFile.h"
#include "HAL/PlatformFileManager.h"

namespace GameKit
{
	namespace
	{
		// ---- Tunables ----
		constexpr int32 SaveIndent = 1;   // small but still readable when a bug report attaches a save

		// ---- Migrations: SaveMigrations[v - 1] turns a version v save's data into version v + 1 ----
		void MigrateSave1To2(FJsonObject& Data)
		{
			if (const TSharedPtr<FJsonValue> Hp = Data.TryGetField(TEXT("hp")))   // v2 renamed hp to health
			{
				Data.SetField(TEXT("health"), Hp);
				Data.RemoveField(TEXT("hp"));
			}
		}

		void MigrateSave2To3(FJsonObject& Data)
		{
			if (!Data.HasField(TEXT("difficulty")))   // v3 added the difficulty the game was started on
			{
				Data.SetStringField(TEXT("difficulty"), TEXT("normal"));
			}
		}

		using FSaveMigration = void (*)(FJsonObject& Data);
		const FSaveMigration SaveMigrations[] = {MigrateSave1To2, MigrateSave2To3};
		static_assert(UE_ARRAY_COUNT(SaveMigrations) == SaveVersion - 1,
		              "SaveVersion changed: add one migration step per version to SaveMigrations");

		struct FParsedSave
		{
			TSharedPtr<FJsonObject> Envelope;   // null on a problem
			FString Problem;                    // "" when Envelope is good
		};

		FParsedSave BadSave(const TCHAR* Problem)
		{
			FParsedSave P;
			P.Problem = Problem;
			return P;
		}

		/** One file's text as an envelope at its own version, or the reason it cannot be loaded. */
		FParsedSave ParseSave(const TOptional<FString>& Text)
		{
			if (!Text.IsSet())
			{
				return BadSave(TEXT("missing"));
			}
			const TSharedPtr<FJsonValue> Root = Json::Parse(Text.GetValue());
			if (!Root.IsValid())
			{
				return BadSave(TEXT("unreadable"));
			}
			const TSharedPtr<FJsonObject> Env = Json::Is(Root, EJson::Object) ? Root->AsObject() : nullptr;
			const TSharedPtr<FJsonValue> Format = Json::Find(Env, TEXT("format"));
			if (!Env.IsValid() || !Json::Is(Format, EJson::String) || !Format->AsString().Equals(SaveFormat, ESearchCase::CaseSensitive) ||
			    !Json::FindObject(Env, TEXT("data")).IsValid())
			{
				return BadSave(TEXT("not a save"));
			}
			const TSharedPtr<FJsonValue> V = Json::Find(Env, TEXT("version"));
			if (!Json::Is(V, EJson::Number))   // true/false are not numbers here
			{
				return BadSave(TEXT("bad version"));
			}
			const double Version = V->AsNumber();
			if (!FMath::IsFinite(Version) || Version != FMath::FloorToDouble(Version) || Version < 1.0)
			{
				return BadSave(TEXT("bad version"));
			}
			if (Version > SaveVersion)
			{
				return BadSave(TEXT("newer"));
			}
			FParsedSave P;
			P.Envelope = Env;
			P.Envelope->SetNumberField(TEXT("version"), Version);   // 2.0 in the file reads as version 2
			return P;
		}

		FParsedSave ParseSaveFile(const FString& Path)
		{
			return ParseSave(ReadTextFile(Path));
		}
	}

	TSharedRef<FJsonObject> SaveMigrate(const TSharedRef<FJsonObject>& Envelope)
	{
		TSharedRef<FJsonObject> Env = Json::CloneObject(Envelope);
		int32 Version = static_cast<int32>(Json::GetNumber(Env, TEXT("version"), SaveVersion));
		TSharedPtr<FJsonObject> Data = Json::FindObject(Env, TEXT("data"));
		if (!Data.IsValid())
		{
			Data = MakeShared<FJsonObject>();
			Env->SetObjectField(TEXT("data"), Data);
		}
		while (Version >= 1 && Version < SaveVersion)
		{
			SaveMigrations[Version - 1](*Data);
			++Version;
			Env->SetNumberField(TEXT("version"), Version);
		}
		return Env;
	}

	TSharedRef<FJsonObject> SaveEnvelope(const TSharedRef<FJsonObject>& Data)
	{
		TSharedRef<FJsonObject> Env = MakeShared<FJsonObject>();
		Env->SetStringField(TEXT("format"), SaveFormat);
		Env->SetNumberField(TEXT("version"), SaveVersion);
		Env->SetObjectField(TEXT("data"), Json::CloneObject(Data));
		return Env;
	}

	FGameKitSaveLoad SaveLoad(const TOptional<FString>& Primary, const TOptional<FString>& Backup)
	{
		struct FSaveSource
		{
			const TCHAR* Name;
			const TOptional<FString>* Text;
		};
		FGameKitSaveLoad R;
		const FSaveSource Files[] = {{TEXT("primary"), &Primary}, {TEXT("backup"), &Backup}};
		for (const FSaveSource& Entry : Files)
		{
			const FParsedSave P = ParseSave(*Entry.Text);
			if (P.Problem.IsEmpty())
			{
				R.Envelope = SaveMigrate(P.Envelope.ToSharedRef());
				R.Source = Entry.Name;
				return R;
			}
			R.bNewer = R.bNewer || P.Problem == TEXT("newer");
			R.Problems.Add(FString::Printf(TEXT("%s: %s"), Entry.Name, *P.Problem));
		}
		R.Source = TEXT("none");
		return R;
	}
}

FString FGameKitSaveStore::GetBackupFile() const
{
	return GameKit::BackupPathFor(File);
}

FGameKitSaveLoad FGameKitSaveStore::Load() const
{
	return GameKit::SaveLoad(GameKit::ReadTextFile(File), GameKit::ReadTextFile(GetBackupFile()));
}

bool FGameKitSaveStore::Save(const TSharedRef<FJsonObject>& Data, FString* OutError) const
{
	using namespace GameKit;
	const TOptional<TArray<uint8>> Current = ReadFileBytes(File);
	const FParsedSave Now = ParseSaveFile(File);
	if (Now.Problem == TEXT("newer") || ParseSaveFile(GetBackupFile()).Problem == TEXT("newer"))
	{
		if (OutError)
		{
			*OutError = TEXT("a newer version of the game wrote this save; not overwriting it");
		}
		return false;
	}
	if (!WriteTemp(File, Json::Write(SaveEnvelope(Data), SaveIndent) + TEXT("\n"), OutError))
	{
		return false;   // nothing on disk changed
	}
	// Keep the previous save only when it is a good one: a corrupt file must not replace a good backup
	if (Now.Problem.IsEmpty() && Current.IsSet() && !WriteFileAtomic(GetBackupFile(), Current.GetValue(), OutError))
	{
		FPlatformFileManager::Get().GetPlatformFile().DeleteFile(*TempPathFor(File));
		return false;
	}
	return CommitTemp(File, OutError);
}
