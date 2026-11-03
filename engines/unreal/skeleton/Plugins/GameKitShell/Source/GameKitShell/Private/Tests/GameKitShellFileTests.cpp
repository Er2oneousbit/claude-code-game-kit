// ---------------------------------------------------------------------------
// GameKitShellFileTests.cpp
// Purpose : Tests the crash-safe file layer on the real filesystem (atomic writes, the save store's backup and
//           newer-save rules, the settings file round trip) and the API edges the vectors do not reach.
// Usage   : python tools/dev.py test --filter GameKit.Shell      (or `test` for everything)
// Notes   : Each test works in its own folder under the user's temp folder whose name contains a non-ASCII
//           letter (narrow-path APIs mangle it), removed again at the end. A "crash" is simulated by stopping
//           after WriteTemp(), before CommitTemp(): exactly the window an atomic write must survive.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAtomicFile.h"
#include "GameKitBindings.h"
#include "GameKitEase.h"
#include "GameKitI18n.h"
#include "GameKitJson.h"
#include "GameKitSaveStore.h"
#include "GameKitSettings.h"
#include "GameKitSpring.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

namespace GameKitShellFileTests
{
	// ---- Constants ----
	constexpr EAutomationTestFlags FileTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	const FString TempFolderPrefix = FString(TEXT("gamekit-shell-")) + static_cast<TCHAR>(0x00CD);   // "I acute"

	/** A fresh, uniquely named folder under the user's temp folder, deleted with everything in it at scope exit. */
	struct FTempFolder
	{
		FString Path;
		FTempFolder()
		{
			Path = FPaths::Combine(FPlatformProcess::UserTempDir(), TempFolderPrefix + TEXT("-") + FGuid::NewGuid().ToString());
			IFileManager::Get().MakeDirectory(*Path, /*Tree*/ true);
		}
		~FTempFolder()
		{
			IFileManager::Get().DeleteDirectory(*Path, /*RequireExists*/ false, /*Tree*/ true);
		}
		FTempFolder(const FTempFolder&) = delete;
		FTempFolder& operator=(const FTempFolder&) = delete;

		FString operator/(const TCHAR* Name) const { return FPaths::Combine(Path, Name); }
	};

	FString ReadOrMissing(const FString& Path)
	{
		return GameKit::ReadTextFile(Path).Get(TEXT("<missing>"));
	}

	bool FileExists(const FString& Path)
	{
		return IFileManager::Get().FileExists(*Path);
	}

	/** {"level": N}, the game data the save tests write. */
	TSharedRef<FJsonObject> Level(int32 N)
	{
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetNumberField(TEXT("level"), N);
		return Data;
	}

	/** data.level of a loaded envelope, or -1. */
	int32 LevelOf(const FGameKitSaveLoad& Loaded)
	{
		const TSharedPtr<FJsonObject> Data = GameKit::Json::FindObject(Loaded.Envelope, TEXT("data"));
		return static_cast<int32>(GameKit::Json::GetNumber(Data, TEXT("level"), -1.0));
	}

// The tests live in the namespace too, so its helpers need no prefix and nothing leaks into a unity build

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAtomicReplaceTest, "GameKit.Shell.AtomicFile.Replace", FileTestFlags)
bool FGameKitAtomicReplaceTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = Dir / TEXT("data.txt");
	FString Error;
	TestTrue(TEXT("first write"), GameKit::WriteFileAtomic(File, TEXT("one"), &Error));
	TestTrue(TEXT("write over an existing file: ") + Error, GameKit::WriteFileAtomic(File, TEXT("two"), &Error));
	TestEqual(TEXT("the new text is there"), ReadOrMissing(File), FString(TEXT("two")));
	TestFalse(TEXT("no .tmp left behind"), FileExists(GameKit::TempPathFor(File)));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAtomicCrashTest, "GameKit.Shell.AtomicFile.CrashBeforeRename", FileTestFlags)
bool FGameKitAtomicCrashTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = Dir / TEXT("data.txt");
	TestTrue(TEXT("old version written"), GameKit::WriteFileAtomic(File, TEXT("old")));
	TestTrue(TEXT("new version reaches .tmp"), GameKit::WriteTemp(File, TEXT("new but never committed")));   // the process dies here
	TestEqual(TEXT("the old file is intact"), ReadOrMissing(File), FString(TEXT("old")));
	TestTrue(TEXT("the next write replaces the stale .tmp"), GameKit::WriteFileAtomic(File, TEXT("next")));
	TestEqual(TEXT("and lands"), ReadOrMissing(File), FString(TEXT("next")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAtomicReadTest, "GameKit.Shell.AtomicFile.MissingVsEmpty", FileTestFlags)
bool FGameKitAtomicReadTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	FString Error = TEXT("x");
	TestFalse(TEXT("a missing file reads as unset"), GameKit::ReadTextFile(Dir / TEXT("nope.json"), &Error).IsSet());
	TestTrue(TEXT("missing is not an error"), Error.IsEmpty());
	TestTrue(TEXT("an empty file can be written"), GameKit::WriteFileAtomic(Dir / TEXT("empty.json"), FString()));
	const TOptional<FString> Empty = GameKit::ReadTextFile(Dir / TEXT("empty.json"));
	TestTrue(TEXT("an empty file reads as set and empty"), Empty.IsSet() && Empty->IsEmpty());
	TestFalse(TEXT("a folder is not a file"), GameKit::ReadTextFile(Dir.Path, &Error).IsSet());
	TestFalse(TEXT("and says so"), Error.IsEmpty());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAtomicFoldersTest, "GameKit.Shell.AtomicFile.CreatesFolders", FileTestFlags)
bool FGameKitAtomicFoldersTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = FPaths::Combine(Dir.Path, TEXT("saves"), TEXT("slot1.json"));
	TestTrue(TEXT("write into a missing folder"), GameKit::WriteFileAtomic(File, TEXT("{}")));
	TestEqual(TEXT("it is there"), ReadOrMissing(File), FString(TEXT("{}")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAtomicUtf8Test, "GameKit.Shell.AtomicFile.Utf8", FileTestFlags)
bool FGameKitAtomicUtf8Test::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = Dir / TEXT("text.json");
	// "Pla" + y acute + a CJK character + a surrogate pair (U+1F600): bytes a narrow (cp1252) path would mangle
	FString Text = TEXT("Pla");
	Text.AppendChar(static_cast<TCHAR>(0x00FD));
	Text.AppendChar(static_cast<TCHAR>(0x904A));
	Text.AppendChar(static_cast<TCHAR>(0xD83D));
	Text.AppendChar(static_cast<TCHAR>(0xDE00));
	TestTrue(TEXT("written"), GameKit::WriteFileAtomic(File, Text));
	TestEqual(TEXT("read back unchanged"), ReadOrMissing(File), Text);
	const TOptional<TArray<uint8>> Bytes = GameKit::ReadFileBytes(File);
	TestTrue(TEXT("UTF-8 without a BOM (3 + 2 + 3 + 4 bytes)"), Bytes.IsSet() && Bytes->Num() == 12 && (*Bytes)[0] == 'P');
	TestEqual(TEXT("the pair counts as one character"), GameKit::CodePointLength(Text), 6);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveBackupTest, "GameKit.Shell.SaveStore.KeepsBackup", FileTestFlags)
bool FGameKitSaveBackupTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	TestTrue(TEXT("first save"), Store.Save(Level(1)));
	TestFalse(TEXT("nothing to keep yet"), FileExists(Store.GetBackupFile()));
	TestTrue(TEXT("second save"), Store.Save(Level(2)));
	const FGameKitSaveLoad Loaded = Store.Load();
	TestEqual(TEXT("loads the main file"), Loaded.Source, FString(TEXT("primary")));
	TestEqual(TEXT("at the current version"), static_cast<int32>(GameKit::Json::GetNumber(Loaded.Envelope, TEXT("version"), -1)), GameKit::SaveVersion);
	TestEqual(TEXT("the latest data"), LevelOf(Loaded), 2);
	TestEqual(TEXT("the backup holds the previous save"), LevelOf(GameKit::SaveLoad(GameKit::ReadTextFile(Store.GetBackupFile()), {})), 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveCorruptTest, "GameKit.Shell.SaveStore.CorruptFallsBack", FileTestFlags)
bool FGameKitSaveCorruptTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	TestTrue(TEXT("save 1"), Store.Save(Level(1)));
	TestTrue(TEXT("save 2"), Store.Save(Level(2)));                                         // .bak = level 1
	TestTrue(TEXT("torn by some other tool"), GameKit::WriteFileAtomic(Store.GetFile(), TEXT("{\"format\": \"sa")));
	FGameKitSaveLoad Loaded = Store.Load();
	TestEqual(TEXT("falls back to the backup"), Loaded.Source, FString(TEXT("backup")));
	TestEqual(TEXT("one problem"), Loaded.Problems.Num(), 1);
	TestEqual(TEXT("the backup's data"), LevelOf(Loaded), 1);
	TestTrue(TEXT("save 3"), Store.Save(Level(3)));   // the corrupt file is not good, so .bak stays level 1
	TestEqual(TEXT("the good backup survives"), LevelOf(GameKit::SaveLoad(GameKit::ReadTextFile(Store.GetBackupFile()), {})), 1);
	TestEqual(TEXT("the new save loads"), LevelOf(Store.Load()), 3);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveCrashTest, "GameKit.Shell.SaveStore.CrashDuringSave", FileTestFlags)
bool FGameKitSaveCrashTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	TestTrue(TEXT("save 4"), Store.Save(Level(4)));
	const FString Next = GameKit::Json::Write(GameKit::SaveEnvelope(Level(5)));
	TestTrue(TEXT("save 5 reaches .tmp"), GameKit::WriteTemp(Store.GetFile(), Next));   // the process dies here
	const FGameKitSaveLoad Loaded = Store.Load();
	TestEqual(TEXT("the main file still loads"), Loaded.Source, FString(TEXT("primary")));
	TestEqual(TEXT("with the last committed save"), LevelOf(Loaded), 4);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveNewerTest, "GameKit.Shell.SaveStore.NewerNotOverwritten", FileTestFlags)
bool FGameKitSaveNewerTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	const FString Newer = FString::Printf(TEXT("{\"format\": \"save\", \"version\": %d, \"data\": {}}"), GameKit::SaveVersion + 1);
	TestTrue(TEXT("a newer game's save"), GameKit::WriteFileAtomic(Store.GetFile(), Newer));
	const FGameKitSaveLoad Loaded = Store.Load();
	TestFalse(TEXT("is not loaded"), Loaded.Envelope.IsValid());
	TestTrue(TEXT("and is reported as newer"), Loaded.bNewer);
	FString Error;
	TestFalse(TEXT("saving over it is refused"), Store.Save(Level(1), &Error));
	TestFalse(TEXT("with a reason"), Error.IsEmpty());
	TestEqual(TEXT("the newer save is untouched"), ReadOrMissing(Store.GetFile()), Newer);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveNewerBackupTest, "GameKit.Shell.SaveStore.NewerBackupBlocksSaving", FileTestFlags)
bool FGameKitSaveNewerBackupTest::RunTest(const FString&)
{
	// a newer build saved twice, then the primary was deleted: every port refuses the slot, so a later save never
	// copies this build's file over the newer .bak
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	const FString Newer = FString::Printf(TEXT("{\"format\": \"save\", \"version\": %d, \"data\": {}}"), GameKit::SaveVersion + 1);
	TestTrue(TEXT("a newer game's backup"), GameKit::WriteFileAtomic(Store.GetBackupFile(), Newer));
	FString Error;
	TestFalse(TEXT("saving the slot is refused"), Store.Save(Level(1), &Error));
	TestFalse(TEXT("no primary was written"), FileExists(Store.GetFile()));
	TestEqual(TEXT("the newer backup is untouched"), ReadOrMissing(Store.GetBackupFile()), Newer);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSaveMigrateTest, "GameKit.Shell.SaveStore.MigratesOnLoad", FileTestFlags)
bool FGameKitSaveMigrateTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FGameKitSaveStore Store(Dir / TEXT("save.json"));
	TestTrue(TEXT("a version 1 save"), GameKit::WriteFileAtomic(Store.GetFile(), TEXT("{\"format\": \"save\", \"version\": 1, \"data\": {\"hp\": 3}}")));
	const FGameKitSaveLoad Loaded = Store.Load();
	const TSharedPtr<FJsonObject> Data = GameKit::Json::FindObject(Loaded.Envelope, TEXT("data"));
	TestEqual(TEXT("is migrated to the current version"), static_cast<int32>(GameKit::Json::GetNumber(Loaded.Envelope, TEXT("version"), -1)), GameKit::SaveVersion);
	TestEqual(TEXT("hp became health"), GameKit::Json::GetNumber(Data, TEXT("health"), -1.0), 3.0);
	TestFalse(TEXT("hp is gone"), Data.IsValid() && Data->HasField(TEXT("hp")));
	TestEqual(TEXT("difficulty was added"), GameKit::Json::GetString(Data, TEXT("difficulty"), FString()), FString(TEXT("normal")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSettingsRoundTripTest, "GameKit.Shell.Settings.RoundTrip", FileTestFlags)
bool FGameKitSettingsRoundTripTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = Dir / TEXT("settings.json");
	TestEqual(TEXT("no file yet: defaults, no problems"), GameKit::SettingsLoadFile(File).Problems.Num(), 0);
	TSharedRef<FJsonObject> S = GameKit::DefaultSettings();
	S->GetObjectField(TEXT("access"))->SetNumberField(TEXT("text_scale"), 1.5);
	S->SetStringField(TEXT("language"), TEXT("fr-CA"));
	TSharedRef<FJsonObject> Mod = MakeShared<FJsonObject>();
	Mod->SetBoolField(TEXT("turbo"), true);
	Mod->SetField(TEXT("nothing"), GameKit::Json::MakeNull());   // a null survives too (the engine's Duplicate drops it)
	S->SetObjectField(TEXT("mod_options"), Mod);                  // a key only a newer build knows
	FString Error;
	TestTrue(TEXT("saved: ") + Error, GameKit::SettingsSaveFile(File, S, &Error));
	const FGameKitSettingsLoad Loaded = GameKit::SettingsLoadFile(File);
	TestEqual(TEXT("no problems"), Loaded.Problems.Num(), 0);
	const FString Why = GameKit::Json::Diff(GameKit::Json::MakeObject(Loaded.Settings), GameKit::Json::MakeObject(S));
	TestTrue(TEXT("loads back the same ") + Why, Why.IsEmpty());
	TestTrue(TEXT("numbers are written short (0.8, not 0.80000000000000004)"), ReadOrMissing(File).Contains(TEXT("\"music\": 0.8,")));
	TestEqual(TEXT("typed read"), GameKit::SettingNumber(*Loaded.Settings, TEXT("access"), TEXT("text_scale")), 1.5);
	TestEqual(TEXT("language read"), GameKit::SettingLanguage(*Loaded.Settings), FString(TEXT("fr-CA")));
	TestTrue(TEXT("resolution read"), GameKit::SettingResolution(*Loaded.Settings) == FIntPoint(1920, 1080));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitSettingsBrokenTest, "GameKit.Shell.Settings.BrokenFile", FileTestFlags)
bool FGameKitSettingsBrokenTest::RunTest(const FString&)
{
	const FTempFolder Dir;
	const FString File = Dir / TEXT("settings.json");
	TestTrue(TEXT("a torn file"), GameKit::WriteFileAtomic(File, TEXT("{\"audio\": ")));
	const FGameKitSettingsLoad Loaded = GameKit::SettingsLoadFile(File);
	const FString Why = GameKit::Json::Diff(GameKit::Json::MakeObject(Loaded.Settings), GameKit::Json::MakeObject(GameKit::DefaultSettings()));
	TestTrue(TEXT("loads as the defaults ") + Why, Why.IsEmpty());
	TestEqual(TEXT("with one problem"), Loaded.Problems.Num(), 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitApiEdgesTest, "GameKit.Shell.ApiEdges", FileTestFlags)
bool FGameKitApiEdgesTest::RunTest(const FString&)
{
	TestFalse(TEXT("an unknown easing name is an error"), GameKit::EaseByName(TEXT("out_wobble"), 0.5).IsSet());
	TestFalse(TEXT("names are case-sensitive"), GameKit::EaseFromName(TEXT("Linear")).IsSet());
	TestFalse(TEXT("rebind past the last slot is refused"), GameKit::Rebind(GameKit::DefaultBindings(), TEXT("jump"), 3, TEXT("key:k")).IsSet());
	TestFalse(TEXT("a negative slot is refused"), GameKit::Rebind(GameKit::DefaultBindings(), TEXT("jump"), -1, TEXT("key:k")).IsSet());
	TestEqual(TEXT("squash never reaches zero width"), GameKit::Squash(-5.0).X, 1.0 + GameKit::SquashMinAmount);
	TestEqual(TEXT("a bare scalar is not a settings object"), GameKit::SettingsLoad(FString(TEXT("5"))).Problems.Num(), 1);
	TestEqual(TEXT("an enum value differing only in case is a problem"),
	          GameKit::SettingsLoad(FString(TEXT("{\"display\": {\"mode\": \"Fullscreen\"}}"))).Problems.Num(), 1);
	TestEqual(TEXT("a number that needs 17 digits keeps them"), GameKit::Json::FormatNumber(0.1 + 0.2), FString(TEXT("0.30000000000000004")));
	TestEqual(TEXT("whole numbers print as integers"), GameKit::Json::FormatNumber(1920.0), FString(TEXT("1920")));
	return true;
}

} // namespace GameKitShellFileTests

#endif // WITH_DEV_AUTOMATION_TESTS

// {{FOOTER}}
