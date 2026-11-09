// ---------------------------------------------------------------------------
// GameKitShellSubsystem.cpp
// Purpose : The game-instance subsystem behind GameKitShellSubsystem.h: makes the model, adds the widget to the
//           viewport after the first map loads, routes the model's events.
// Usage   : compiled into the GameKitShellUI module.
// Notes   : -GameKitShell on the command line turns the screens on for one run (the smoke tests and a quick look);
//           the project setting turns them on for good. Quit goes through UKismetSystemLibrary::QuitGame, which
//           ends a PIE session instead of closing the editor.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellSubsystem.h"

#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "GameKitShellLog.h"
#include "Kismet/KismetSystemLibrary.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "SGameKitShell.h"
#include "GeneralProjectSettings.h"

namespace
{
	constexpr int32 ShellZOrder = 100;   // above the game's own HUD widgets
	const TCHAR* DefaultDataFolder = TEXT("GameKit");   // under Saved/
}

bool UGameKitShellSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return GetDefault<UGameKitShellSettings>()->bShowScreens || FParse::Param(FCommandLine::Get(), TEXT("GameKitShell"));
}

void UGameKitShellSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	MapHandle = FCoreUObjectDelegates::PostLoadMapWithWorld.AddUObject(this, &UGameKitShellSubsystem::OnMapLoaded);
}

void UGameKitShellSubsystem::Deinitialize()
{
	FCoreUObjectDelegates::PostLoadMapWithWorld.Remove(MapHandle);
	if (Widget.IsValid())
	{
		if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
		{
			Viewport->RemoveViewportWidgetContent(Widget.ToSharedRef());
		}
		Widget.Reset();
	}
	Model.Reset();
	Super::Deinitialize();
}

void UGameKitShellSubsystem::MakeModel()
{
	if (Model.IsValid())
	{
		return;
	}
	const UGameKitShellSettings* Cfg = GetDefault<UGameKitShellSettings>();
	FGameKitShellModel::FOptions Opt;
	Opt.ProjectDir = FPaths::ProjectDir();
	Opt.DataDir = Cfg->DataFolder.IsEmpty() ? FPaths::Combine(FPaths::ProjectSavedDir(), DefaultDataFolder) : Cfg->DataFolder;
	FString DataDir;
	if (FParse::Value(FCommandLine::Get(), TEXT("GameKitDataDir="), DataDir))
	{
		Opt.DataDir = DataDir;
	}
	Opt.GameName = FApp::GetProjectName();
	Opt.Version = GetDefault<UGeneralProjectSettings>()->ProjectVersion;
	FParse::Value(FCommandLine::Get(), TEXT("GameKitLocale="), Opt.Locale);
	Opt.bAutomated = FParse::Param(FCommandLine::Get(), TEXT("unattended"));
#if !UE_BUILD_SHIPPING
	Opt.bDebugBuild = true;
#endif
	Model = MakeShared<FGameKitShellModel>(Opt);
	Model->OnEvent = [this](const FString& What)
	{
		OnShellEvent.Broadcast(What);
		if (What == TEXT("quit"))
		{
			UWorld* World = GetGameInstance() ? GetGameInstance()->GetWorld() : nullptr;
			UKismetSystemLibrary::QuitGame(World, World ? World->GetFirstPlayerController() : nullptr, EQuitPreference::Quit, false);
		}
	};
	Model->OnNarrate = [](const FString& Line)
	{
		// Hook a text-to-speech here (Unreal's TextToSpeech plugin, or the platform's); the line is always logged
		UE_LOG(LogGameKitShell, Log, TEXT("narrate: %s"), *Line);
	};
	Model->Push(TEXT("title"));
}

void UGameKitShellSubsystem::OnMapLoaded(UWorld* World)
{
	if (!World || World->GetGameInstance() != GetGameInstance())
	{
		return;   // another PIE session's world
	}
	ShowScreens(World);
}

void UGameKitShellSubsystem::ShowScreens(UWorld* World)
{
	MakeModel();
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (!Viewport)
	{
		UE_LOG(LogGameKitShell, Warning, TEXT("no game viewport yet: the screens show on the next map load"));
		return;
	}
	if (!Widget.IsValid())
	{
		Widget = SNew(SGameKitShell, Model.ToSharedRef());
		Viewport->AddViewportWidgetContent(Widget.ToSharedRef(), ShellZOrder);
	}
	if (APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr)
	{
		FInputModeGameAndUI Mode;
		Mode.SetWidgetToFocus(Widget);
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		Mode.SetHideCursorDuringCapture(false);
		PC->SetInputMode(Mode);
	}
	FSlateApplication::Get().SetAllUserFocus(Widget, EFocusCause::SetDirectly);
	UE_LOG(LogGameKitShell, Display, TEXT("SHELL_SHOWN %s"), *Model->TopName());
}

void UGameKitShellSubsystem::SetObjective(const FString& Text)
{
	MakeModel();
	Model->SetObjective(Text);
}

void UGameKitShellSubsystem::Say(const FString& Speaker, const FString& Text, float Seconds)
{
	MakeModel();
	Model->Say(Speaker, Text, Seconds);
}

float UGameKitShellSubsystem::SettingNumber(const FString& Section, const FString& Field) const
{
	return Model.IsValid() ? static_cast<float>(Model->Num(*Section, *Field)) : 0.f;
}

bool UGameKitShellSubsystem::SettingFlag(const FString& Section, const FString& Field) const
{
	return Model.IsValid() && Model->Flag(*Section, *Field);
}

FString UGameKitShellSubsystem::TopScreen() const
{
	return Model.IsValid() ? Model->TopName() : FString();
}

// {{FOOTER}}
