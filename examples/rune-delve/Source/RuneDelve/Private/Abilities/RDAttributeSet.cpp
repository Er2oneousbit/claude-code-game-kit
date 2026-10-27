// ---------------------------------------------------------------------------
// RDAttributeSet.cpp
// Purpose : See RDAttributeSet.h.
//
// Pseudocode:
//   Damage arrives -> read the target's tags (dashing, warded, staggered) and whether it is a melee swing
//   -> RDRules::ResolveHit -> lose health, or block (stagger the swinger, the ward is spent), or dodge
//   -> tell the character
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix: a block removes the ward, so it stops one swing as the GDD says (it used to
//           block every swing inside its 0.45 s window)
// ---------------------------------------------------------------------------
#include "Abilities/RDAttributeSet.h"

#include "Abilities/RDTags.h"
#include "Core/RDRules.h"
#include "Game/RDCharacterBase.h"
#include "Game/RDTuning.h"
#include "GameplayEffectExtension.h"

void URDAttributeSet::PreAttributeChange(const FGameplayAttribute& Attribute, float& NewValue)
{
	Super::PreAttributeChange(Attribute, NewValue);
	if (Attribute == GetHealthAttribute())
	{
		NewValue = FMath::Clamp(NewValue, 0.f, GetMaxHealth());
	}
	else if (Attribute == GetManaAttribute())
	{
		NewValue = FMath::Clamp(NewValue, 0.f, GetMaxMana());
	}
}

void URDAttributeSet::PostGameplayEffectExecute(const FGameplayEffectModCallbackData& Data)
{
	Super::PostGameplayEffectExecute(Data);
	if (Data.EvaluatedData.Attribute == GetManaAttribute())
	{
		SetMana(FMath::Clamp(GetMana(), 0.f, GetMaxMana()));
		return;
	}
	if (Data.EvaluatedData.Attribute == GetHealthAttribute())
	{
		SetHealth(FMath::Clamp(GetHealth(), 0.f, GetMaxHealth()));
		return;
	}
	if (Data.EvaluatedData.Attribute != GetDamageAttribute())
	{
		return;
	}

	const float Raw = GetDamage();
	SetDamage(0.f);
	ARDCharacterBase* Target = Cast<ARDCharacterBase>(Data.Target.GetAvatarActor());
	if (!Target || !Target->IsAlive())
	{
		return;
	}
	UAbilitySystemComponent* SourceAsc = Data.EffectSpec.GetContext().GetInstigatorAbilitySystemComponent();
	ARDCharacterBase* Source = SourceAsc ? Cast<ARDCharacterBase>(SourceAsc->GetAvatarActor()) : nullptr;
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	const bool bMelee = Data.EffectSpec.GetDynamicAssetTags().HasTag(RDTags::Data_Melee);

	const FRDHitResult Hit = RDRules::ResolveHit(Raw, Data.Target.HasMatchingGameplayTag(RDTags::State_Warded),
	                                             Data.Target.HasMatchingGameplayTag(RDTags::State_Dashing),
	                                             Data.Target.HasMatchingGameplayTag(RDTags::State_Staggered), bMelee,
	                                             N.StaggerDamageMult);
	if (Hit.bDodged)
	{
		Target->OnDodged();
		return;
	}
	if (Hit.bBlocked)
	{
		if (Hit.bStaggerAttacker && Source)
		{
			Source->ApplyTimedTag(RDTags::State_Staggered, N.StaggerSeconds);
		}
		Data.Target.RemoveActiveEffectsWithGrantedTags(FGameplayTagContainer(RDTags::State_Warded));   // one swing per ward
		Target->OnWardBlock(Source);
		return;
	}
	if (Hit.Damage <= 0.f || Target->IsGod())
	{
		return;
	}
	SetHealth(FMath::Clamp(GetHealth() - Hit.Damage, 0.f, GetMaxHealth()));
	Target->OnHurt(Hit.Damage, Source);
	if (GetHealth() <= 0.f)
	{
		Target->OnZeroHealth(Source);
	}
}
