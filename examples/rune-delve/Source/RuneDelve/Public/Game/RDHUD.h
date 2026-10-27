// ---------------------------------------------------------------------------
// RDHUD.h
// Purpose : The whole UI, drawn on the canvas in C++ (no widget assets): health and mana bars, the three
//           spells with their cooldowns, room and time, orc health bars, the "!" when an orc spots you, a
//           red ring during a wind-up, and messages. -debugai adds orc states and the bot's reason.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "RDHUD.generated.h"

UCLASS()
class RUNEDELVE_API ARDHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;

private:
	void DrawBar(float X, float Y, float W, float H, float Fraction, const FLinearColor& Color, const FString& Label);
	void DrawSpell(float X, float Y, const TCHAR* Name, const TCHAR* Key, float CooldownLeft, bool bAffordable);
	void DrawOrcs();
};
