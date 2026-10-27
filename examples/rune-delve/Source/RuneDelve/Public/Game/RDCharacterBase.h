// ---------------------------------------------------------------------------
// RDCharacterBase.h
// Purpose : What the mage and the orcs share: an Ability System Component with URDAttributeSet, a Kenney
//           body with single-node animation (no Animation Blueprint, so nothing editor-made), timed tags
//           (cooldowns, ward, stagger, dash), sounds, and the hooks the attribute set calls on a hit.
// Usage   : subclass; in the constructor call SetupBody(TEXT("character-orc")) (the mesh loads in BeginPlay, never in a
//           constructor: see docs/ENGINE.md gotcha 12); in BeginPlay InitStats(...)
// Notes   : Kenney characters are about 78 cm tall and face along Y; they are drawn at FRDLevel::WorldScale
//           and turned by MeshYaw so they face the actor's forward (+X).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "AbilitySystemInterface.h"
#include "GameFramework/Character.h"
#include "GameplayTagContainer.h"
#include "RDCharacterBase.generated.h"

class UAbilitySystemComponent;
class UAnimSequence;
class UGameplayEffect;
class URDAttributeSet;

UCLASS(Abstract)
class RUNEDELVE_API ARDCharacterBase : public ACharacter, public IAbilitySystemInterface
{
	GENERATED_BODY()

public:
	static constexpr float CapsuleHalfHeight = 80.f;
	static constexpr float CapsuleRadius = 36.f;
	static constexpr float MeshYaw = -90.f;

	ARDCharacterBase();

	virtual UAbilitySystemComponent* GetAbilitySystemComponent() const override { return Asc; }

	bool IsAlive() const;
	virtual bool IsGod() const { return false; }
	float GetHealth() const;
	float GetMaxHealth() const;
	float GetMana() const;
	float GetMaxMana() const;
	FVector2D Ground() const { return FVector2D(GetActorLocation()); }

	/** Grant Tag for Seconds (a URDEffect_Timed spec). */
	void ApplyTimedTag(const FGameplayTag& Tag, float Seconds);
	bool HasTag(const FGameplayTag& Tag) const;
	/** Seconds left on the longest active effect granting Tag, 0 if none. */
	float TimeLeft(const FGameplayTag& Tag) const;
	/** Apply an instant SetByCaller effect from this character to Target (damage, mana, heal). */
	void ApplyInstant(TSubclassOf<UGameplayEffect> Effect, float Amount, UAbilitySystemComponent* Target, bool bMelee = false);

	// Called by URDAttributeSet when a hit resolves
	virtual void OnHurt(float Damage, ARDCharacterBase* Source) {}
	virtual void OnWardBlock(ARDCharacterBase* Attacker) {}
	virtual void OnDodged() {}
	virtual void OnZeroHealth(ARDCharacterBase* Killer) {}

	void PlaySound(const TCHAR* Name, float Volume = 1.f) const;

protected:
	virtual void BeginPlay() override;
	void SetupBody(const TCHAR* Model, float Scale = 1.f);
	void InitStats(float Health, float Mana);
	/** Play an animation of this body by Kenney name ("walk", "die"); restarts only if it changed or bForce. */
	void PlayAnim(const TCHAR* Anim, bool bLoop, float Rate = 1.f, bool bForce = false);

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UAbilitySystemComponent> Asc;
	UPROPERTY()
	TObjectPtr<URDAttributeSet> Attributes;
	UPROPERTY()
	TMap<FName, TObjectPtr<UAnimSequence>> AnimCache;

	FString Model;
	FName CurrentAnim;
};
