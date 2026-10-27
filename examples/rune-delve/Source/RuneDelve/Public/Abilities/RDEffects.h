// ---------------------------------------------------------------------------
// RDEffects.h
// Purpose : The game's few Gameplay Effects, all defined in C++ and all fed by SetByCaller magnitudes, so the
//           numbers come from URDTuning at the moment of use instead of being baked into assets.
// Usage   : FGameplayEffectSpecHandle S = Asc->MakeOutgoingSpec(URDEffect_Damage::StaticClass(), 1, Asc->MakeEffectContext());
//           S.Data->SetSetByCallerMagnitude(RDTags::Data_Amount, 12.f);
// Notes   : URDEffect_Timed is the workhorse: a duration effect with no modifiers; the spec adds the tag it
//           grants (Cooldown.Bolt, State.Warded, State.Staggered, State.Dashing) via DynamicGrantedTags.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameplayEffect.h"
#include "RDEffects.generated.h"

/** Instant: adds Data.Amount to the Damage meta attribute (resolved in URDAttributeSet). */
UCLASS()
class RUNEDELVE_API URDEffect_Damage : public UGameplayEffect
{
	GENERATED_BODY()
public:
	URDEffect_Damage();
};

/** Instant: adds Data.Amount to Mana (negative for a spell's cost). */
UCLASS()
class RUNEDELVE_API URDEffect_Mana : public UGameplayEffect
{
	GENERATED_BODY()
public:
	URDEffect_Mana();
};

/** Instant: adds Data.Amount to Health (the room-clear heal). */
UCLASS()
class RUNEDELVE_API URDEffect_Heal : public UGameplayEffect
{
	GENERATED_BODY()
public:
	URDEffect_Heal();
};

/** Lasts Data.Duration seconds and grants whatever tags the spec carries. */
UCLASS()
class RUNEDELVE_API URDEffect_Timed : public UGameplayEffect
{
	GENERATED_BODY()
public:
	URDEffect_Timed();
};

/** Infinite, every PeriodSeconds: adds Data.Amount to Mana (regeneration). */
UCLASS()
class RUNEDELVE_API URDEffect_ManaRegen : public UGameplayEffect
{
	GENERATED_BODY()
public:
	static constexpr float PeriodSeconds = 0.1f;
	URDEffect_ManaRegen();
};
