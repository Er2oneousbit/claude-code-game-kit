// ---------------------------------------------------------------------------
// RDAttributeSet.h
// Purpose : Health and mana for the mage and the orcs, plus a Damage meta attribute: every hit goes in as
//           Damage and is resolved here with RDRules (dash dodges, ward blocks and staggers, stagger doubles).
// Usage   : created as a default subobject of ARDCharacterBase; the ASC finds it on its own
// Notes   : The resolution calls back into the owning character (OnHurt, OnWardBlock, OnDodged, OnZeroHealth)
//           for sounds, animation and markers; the numbers stay here.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "AbilitySystemComponent.h"
#include "AttributeSet.h"
#include "RDAttributeSet.generated.h"

UCLASS()
class RUNEDELVE_API URDAttributeSet : public UAttributeSet
{
	GENERATED_BODY()

public:
	UPROPERTY() FGameplayAttributeData Health;
	ATTRIBUTE_ACCESSORS_BASIC(URDAttributeSet, Health);
	UPROPERTY() FGameplayAttributeData MaxHealth;
	ATTRIBUTE_ACCESSORS_BASIC(URDAttributeSet, MaxHealth);
	UPROPERTY() FGameplayAttributeData Mana;
	ATTRIBUTE_ACCESSORS_BASIC(URDAttributeSet, Mana);
	UPROPERTY() FGameplayAttributeData MaxMana;
	ATTRIBUTE_ACCESSORS_BASIC(URDAttributeSet, MaxMana);
	/** Meta attribute: incoming damage, turned into Health loss in PostGameplayEffectExecute. */
	UPROPERTY() FGameplayAttributeData Damage;
	ATTRIBUTE_ACCESSORS_BASIC(URDAttributeSet, Damage);

	virtual void PreAttributeChange(const FGameplayAttribute& Attribute, float& NewValue) override;
	virtual void PostGameplayEffectExecute(const FGameplayEffectModCallbackData& Data) override;
};
