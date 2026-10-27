// ---------------------------------------------------------------------------
// RDHUD.cpp
// Purpose : See RDHUD.h.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDHUD.h"

#include "Abilities/RDTags.h"
#include "Core/RDOrcBrain.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Game/RDCommon.h"
#include "Game/RDGameMode.h"
#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "Game/RDTuning.h"

namespace
{
	const FLinearColor Ink(0.92f, 0.9f, 0.85f);
	const FLinearColor Panel(0.f, 0.f, 0.f, 0.55f);
}

void ARDHUD::DrawBar(float X, float Y, float W, float H, float Fraction, const FLinearColor& Color, const FString& Label)
{
	DrawRect(Panel, X - 2.f, Y - 2.f, W + 4.f, H + 4.f);
	DrawRect(Color, X, Y, W * FMath::Clamp(Fraction, 0.f, 1.f), H);
	if (!Label.IsEmpty())
	{
		DrawText(Label, Ink, X + 6.f, Y + 1.f, GEngine->GetSmallFont());
	}
}

void ARDHUD::DrawSpell(float X, float Y, const TCHAR* Name, const TCHAR* Key, float CooldownLeft, bool bAffordable)
{
	const float Size = 64.f;
	DrawRect(Panel, X, Y, Size, Size);
	const bool bReady = CooldownLeft <= 0.f && bAffordable;
	DrawRect(bReady ? FLinearColor(0.2f, 0.45f, 0.9f, 0.8f) : FLinearColor(0.25f, 0.25f, 0.3f, 0.8f), X + 3.f, Y + 3.f, Size - 6.f, Size - 6.f);
	DrawText(Name, Ink, X + 6.f, Y + 6.f, GEngine->GetSmallFont());
	DrawText(Key, FLinearColor(0.7f, 0.7f, 0.7f), X + 6.f, Y + Size - 20.f, GEngine->GetSmallFont());
	if (CooldownLeft > 0.f)
	{
		DrawText(FString::Printf(TEXT("%.1f"), CooldownLeft), FLinearColor::White, X + 28.f, Y + 24.f, GEngine->GetMediumFont());
	}
}

void ARDHUD::DrawHUD()
{
	Super::DrawHUD();
	ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>();
	ARDMage* Mage = Game ? Game->GetMage() : nullptr;
	if (!Canvas || !Game || !Mage)
	{
		return;
	}
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	const float W = Canvas->SizeX;
	const float H = Canvas->SizeY;

	DrawOrcs();

	// Top left: where you are
	DrawText(FString::Printf(TEXT("RUNE DELVE   Room %d/3   %d:%02d"), Game->GetCurrentRoom() + 1,
	                         int32(Game->GetElapsed()) / 60, int32(Game->GetElapsed()) % 60),
	         Ink, 20.f, 16.f, GEngine->GetMediumFont());

	// Bottom centre: health, mana, spells
	const float BarW = 360.f;
	const float X0 = (W - BarW) * 0.5f;
	DrawBar(X0, H - 150.f, BarW, 18.f, Mage->GetHealth() / Mage->GetMaxHealth(), FLinearColor(0.75f, 0.12f, 0.1f),
	        FString::Printf(TEXT("Health %.0f"), Mage->GetHealth()));
	DrawBar(X0, H - 126.f, BarW, 14.f, Mage->GetMana() / Mage->GetMaxMana(), FLinearColor(0.15f, 0.35f, 0.95f),
	        FString::Printf(TEXT("Mana %.0f"), Mage->GetMana()));
	const float SpellsX = (W - 3.f * 74.f) * 0.5f;
	DrawSpell(SpellsX, H - 100.f, TEXT("BOLT"), TEXT("LMB"), Mage->CooldownLeft(RDTags::Cooldown_Bolt), Mage->GetMana() >= N.BoltCost);
	DrawSpell(SpellsX + 74.f, H - 100.f, TEXT("WARD"), TEXT("RMB"), Mage->CooldownLeft(RDTags::Cooldown_Ward), Mage->GetMana() >= N.WardCost);
	DrawSpell(SpellsX + 148.f, H - 100.f, TEXT("DASH"), TEXT("SPACE"), Mage->CooldownLeft(RDTags::Cooldown_Dash), true);
	if (Mage->HasTag(RDTags::State_Warded))
	{
		DrawText(TEXT("WARD UP"), FLinearColor(0.4f, 0.9f, 1.f), X0 + BarW + 16.f, H - 150.f, GEngine->GetMediumFont());
	}

	// Messages
	if (Game->GetToastLeft() > 0.f)
	{
		float TW, TH;
		GetTextSize(Game->GetToast(), TW, TH, GEngine->GetLargeFont());
		DrawRect(Panel, (W - TW) * 0.5f - 16.f, H * 0.3f - 8.f, TW + 32.f, TH + 16.f);
		DrawText(Game->GetToast(), FLinearColor(1.f, 0.85f, 0.4f), (W - TW) * 0.5f, H * 0.3f, GEngine->GetLargeFont());
	}
	const FRDLaunchOptions& O = FRDLaunchOptions::Get();
	if (O.Bot != ERDBotMode::None)
	{
		DrawText(FString::Printf(TEXT("autoplay: %s, seed %d%s%s"), RDBot::Name(O.Bot), O.Seed,
		                         O.bDebugAI ? TEXT(", ") : TEXT(""), O.bDebugAI ? Mage->BotReason() : TEXT("")),
		         FLinearColor(0.6f, 0.8f, 1.f), 20.f, 44.f, GEngine->GetSmallFont());
	}
}

void ARDHUD::DrawOrcs()
{
	ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>();
	const bool bDebug = FRDLaunchOptions::Get().bDebugAI;
	for (const ARDOrc* Orc : Game->GetOrcs())
	{
		if (!Orc || !Orc->IsAlive())
		{
			continue;
		}
		const float Top = Orc->IsWarden() ? 260.f : 190.f;
		const FVector Head = Project(Orc->GetActorLocation() + FVector(0.f, 0.f, Top));
		if (Head.Z <= 0.f)
		{
			continue;
		}
		const float BarW = Orc->IsWarden() ? 90.f : 56.f;
		if (Orc->GetHealth() < Orc->GetMaxHealth())
		{
			DrawBar(Head.X - BarW * 0.5f, Head.Y, BarW, 6.f, Orc->GetHealth() / Orc->GetMaxHealth(), FLinearColor(0.85f, 0.2f, 0.1f), TEXT(""));
		}
		if (Orc->AlertMarkLeft() > 0.f)
		{
			DrawText(TEXT("!"), FLinearColor(1.f, 0.85f, 0.2f), Head.X - 6.f, Head.Y - 40.f, GEngine->GetLargeFont());
		}
		if (Orc->GetState() == ERDOrcState::Windup)
		{
			DrawText(TEXT("!!"), FLinearColor(1.f, 0.2f, 0.1f), Head.X - 12.f, Head.Y - 40.f, GEngine->GetLargeFont());
		}
		if (Orc->HasTag(RDTags::State_Staggered))
		{
			DrawText(TEXT("staggered"), FLinearColor(0.5f, 0.9f, 1.f), Head.X - 30.f, Head.Y - 24.f, GEngine->GetSmallFont());
		}
		if (bDebug)
		{
			DrawText(FRDOrcBrain::StateName(Orc->GetState()), Ink, Head.X - 24.f, Head.Y + 10.f, GEngine->GetSmallFont());
		}
	}
}
