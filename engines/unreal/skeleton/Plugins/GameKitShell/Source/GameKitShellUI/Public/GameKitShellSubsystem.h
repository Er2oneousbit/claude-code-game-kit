// ---------------------------------------------------------------------------
// GameKitShellSubsystem.h
// Purpose : Puts the shell's screens on the game viewport when the game starts: the title, then the menus, with
//           the game's own map running underneath. Opt-in: Project Settings > Plugins > Game Kit Shell >
//           "Show screens" (Config/DefaultGame.ini), or -GameKitShell on the command line.
// Usage   : Config/DefaultGame.ini:
//             [/Script/GameKitShellUI.GameKitShellSettings]
//             bShowScreens=True
//           From C++: UGameKitShellSubsystem* Shell = GetGameInstance()->GetSubsystem<UGameKitShellSubsystem>();
//             Shell->OnShellEvent.AddLambda([](const FString& What) { if (What == TEXT("play")) { ... } });
//             Shell->SetObjective(TEXT("Find the key"));  Shell->Say(TEXT("Guide"), TEXT("Welcome."));
//           From Blueprints: Get Game Instance Subsystem (Game Kit Shell) -> Set Objective, Say, Show Screens.
// Notes   : Events: "play" (the loading screen finished: start or unpause your game), "resume", "quit_title"
//           (back to the title: reset your level), "quit" (ends the game, or the PIE session), "settings_changed"
//           (read the settings again: window mode, volumes, timing_scale ...), "consent". The subsystem gives
//           the widget keyboard focus and sets the first player controller's input mode to Game and UI; while
//           the model's top screen is "play" the widget draws nothing but subtitles and lets input through.
//           Settings live in Saved/GameKit/settings.json (DataFolder changes that).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "GameKitShellModel.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "GameKitShellSubsystem.generated.h"

class SGameKitShell;

UCLASS(config=Game, defaultconfig, meta=(DisplayName="Game Kit Shell"))
class GAMEKITSHELLUI_API UGameKitShellSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	/** Show the kit's screens (title, main menu, settings, pause) over the game when it starts. */
	UPROPERTY(config, EditAnywhere, Category = "Screens")
	bool bShowScreens = false;

	/** Where settings.json is kept; empty means <Saved>/GameKit. */
	UPROPERTY(config, EditAnywhere, Category = "Screens")
	FString DataFolder;

	virtual FName GetCategoryName() const override { return TEXT("Plugins"); }
};

DECLARE_MULTICAST_DELEGATE_OneParam(FGameKitShellEvent, const FString&);

UCLASS()
class GAMEKITSHELLUI_API UGameKitShellSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** The screens' model (made on the first map load; null before). */
	TSharedPtr<FGameKitShellModel> GetModel() const { return Model; }
	TSharedPtr<SGameKitShell> GetWidget() const { return Widget; }

	/** Fires with every shell event (see the header notes). */
	FGameKitShellEvent OnShellEvent;

	/** Puts the screens on the viewport of World now (done for you after the first map loads). */
	UFUNCTION(BlueprintCallable, Category = "Game Kit Shell")
	void ShowScreens(UWorld* World);

	/** The goal "What now?" shows on the pause menu (#167); "" clears it. */
	UFUNCTION(BlueprintCallable, Category = "Game Kit Shell")
	void SetObjective(const FString& Text);

	/** Shows a line as a subtitle and records it for the dialogue history; Seconds 0 = from its length. */
	UFUNCTION(BlueprintCallable, Category = "Game Kit Shell")
	void Say(const FString& Speaker, const FString& Text, float Seconds = 0.f);

	/** One accessibility or audio number as set now, e.g. ("access", "timing_scale") or ("audio", "music"). */
	UFUNCTION(BlueprintPure, Category = "Game Kit Shell")
	float SettingNumber(const FString& Section, const FString& Field) const;

	UFUNCTION(BlueprintPure, Category = "Game Kit Shell")
	bool SettingFlag(const FString& Section, const FString& Field) const;

	/** The screen on top ("title", "main_menu", "settings", "play", "pause" ...). */
	UFUNCTION(BlueprintPure, Category = "Game Kit Shell")
	FString TopScreen() const;

private:
	TSharedPtr<FGameKitShellModel> Model;
	TSharedPtr<SGameKitShell> Widget;
	FDelegateHandle MapHandle;

	void OnMapLoaded(UWorld* World);
	void MakeModel();
};

// {{FOOTER}}
