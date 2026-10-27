// ---------------------------------------------------------------------------
// RDAbilities.h
// Purpose : The mage's three spells as Gameplay Abilities in C++: Bolt (cheap, noisy), Ward (blocks one swing
//           and staggers the swinger), Dash (dodges while it lasts).
// Usage   : Asc->GiveAbility(FGameplayAbilitySpec(URDAbility_Bolt::StaticClass()));
//           Asc->TryActivateAbilityByClass(URDAbility_Bolt::StaticClass());
// Notes   : Cost and cooldown come from URDTuning at activation (CheckCost/ApplyCost/ApplyCooldown are
//           overridden), so there is no cost or cooldown asset. The cooldown is a URDEffect_Timed spec that
//           grants Cooldown.<Spell>, which the default CheckCooldown finds through GetCooldownTags.
//           The effect of each spell (spawning the bolt, moving for the dash) is done by the mage.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Abilities/GameplayAbility.h"
#include "Core/RDNumbers.h"
#include "RDAbilities.generated.h"

class ARDMage;

UCLASS(Abstract)
class RUNEDELVE_API URDAbility : public UGameplayAbility
{
	GENERATED_BODY()

public:
	URDAbility();

	virtual const FGameplayTagContainer* GetCooldownTags() const override { return &CooldownTags; }
	virtual bool CheckCost(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
	                       FGameplayTagContainer* OptionalRelevantTags) const override;
	virtual void ApplyCost(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
	                       const FGameplayAbilityActivationInfo ActivationInfo) const override;
	virtual void ApplyCooldown(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
	                           const FGameplayAbilityActivationInfo ActivationInfo) const override;
	virtual void ActivateAbility(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
	                             const FGameplayAbilityActivationInfo ActivationInfo, const FGameplayEventData* TriggerEventData) override;

protected:
	virtual float CostOf(const FRDNumbers& N) const { return 0.f; }
	virtual float CooldownOf(const FRDNumbers& N) const { return 0.f; }
	virtual void Perform(ARDMage& Mage, const FRDNumbers& N) {}

	FGameplayTagContainer CooldownTags;
};

UCLASS()
class RUNEDELVE_API URDAbility_Bolt : public URDAbility
{
	GENERATED_BODY()
public:
	URDAbility_Bolt();
protected:
	virtual float CostOf(const FRDNumbers& N) const override { return N.BoltCost; }
	virtual float CooldownOf(const FRDNumbers& N) const override { return N.BoltCooldown; }
	virtual void Perform(ARDMage& Mage, const FRDNumbers& N) override;
};

UCLASS()
class RUNEDELVE_API URDAbility_Ward : public URDAbility
{
	GENERATED_BODY()
public:
	URDAbility_Ward();
protected:
	virtual float CostOf(const FRDNumbers& N) const override { return N.WardCost; }
	virtual float CooldownOf(const FRDNumbers& N) const override { return N.WardCooldown; }
	virtual void Perform(ARDMage& Mage, const FRDNumbers& N) override;
};

UCLASS()
class RUNEDELVE_API URDAbility_Dash : public URDAbility
{
	GENERATED_BODY()
public:
	URDAbility_Dash();
protected:
	virtual float CooldownOf(const FRDNumbers& N) const override { return N.DashCooldown; }
	virtual void Perform(ARDMage& Mage, const FRDNumbers& N) override;
};
