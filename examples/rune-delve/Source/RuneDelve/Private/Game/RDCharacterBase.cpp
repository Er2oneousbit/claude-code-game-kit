// ---------------------------------------------------------------------------
// RDCharacterBase.cpp
// Purpose : See RDCharacterBase.h.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDCharacterBase.h"

#include "AbilitySystemComponent.h"
#include "Abilities/RDAttributeSet.h"
#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "Animation/AnimSequence.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/RDLevel.h"
#include "Engine/SkeletalMesh.h"
#include "Game/RDCommon.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"

ARDCharacterBase::ARDCharacterBase()
{
	PrimaryActorTick.bCanEverTick = true;
	Asc = CreateDefaultSubobject<UAbilitySystemComponent>(TEXT("AbilitySystem"));
	Attributes = CreateDefaultSubobject<URDAttributeSet>(TEXT("Attributes"));
	GetCapsuleComponent()->InitCapsuleSize(CapsuleRadius, CapsuleHalfHeight);
	GetMesh()->SetRelativeLocationAndRotation(FVector(0.f, 0.f, -CapsuleHalfHeight), FRotator(0.f, MeshYaw, 0.f));
	GetMesh()->SetAnimationMode(EAnimationMode::AnimationSingleNode);
	GetMesh()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	GetMesh()->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
}

void ARDCharacterBase::SetupBody(const TCHAR* InModel, float Scale)
{
	// Constructor-time: only remember the model. Loading it here would run when the class default object is built,
	// at module load, before a fresh clone has run build_content.py (and that error fails every editor command).
	Model = InModel;
	GetMesh()->SetRelativeScale3D(FVector(FRDLevel::WorldScale * Scale));
}

void ARDCharacterBase::BeginPlay()
{
	Super::BeginPlay();
	if (USkeletalMesh* Body = LoadObject<USkeletalMesh>(nullptr, *RDAssets::Object(RDAssets::Characters, Model)))
	{
		GetMesh()->SetSkeletalMeshAsset(Body);
	}
	else
	{
		UE_LOG(LogRuneDelve, Error, TEXT("missing character mesh %s (run python tools/dev.py exec tools/unreal/build_content.py)"), *Model);
	}
	Asc->InitAbilityActorInfo(this, this);
}

void ARDCharacterBase::InitStats(float Health, float Mana)
{
	Attributes->InitMaxHealth(Health);
	Attributes->InitHealth(Health);
	Attributes->InitMaxMana(FMath::Max(Mana, 0.f));
	Attributes->InitMana(FMath::Max(Mana, 0.f));
}

bool ARDCharacterBase::IsAlive() const { return Attributes && Attributes->GetHealth() > 0.f; }
float ARDCharacterBase::GetHealth() const { return Attributes->GetHealth(); }
float ARDCharacterBase::GetMaxHealth() const { return Attributes->GetMaxHealth(); }
float ARDCharacterBase::GetMana() const { return Attributes->GetMana(); }
float ARDCharacterBase::GetMaxMana() const { return Attributes->GetMaxMana(); }

void ARDCharacterBase::ApplyTimedTag(const FGameplayTag& Tag, float Seconds)
{
	FGameplayEffectSpecHandle Spec = Asc->MakeOutgoingSpec(URDEffect_Timed::StaticClass(), 1.f, Asc->MakeEffectContext());
	Spec.Data->SetSetByCallerMagnitude(RDTags::Data_Duration, Seconds);
	Spec.Data->DynamicGrantedTags.AddTag(Tag);
	Asc->ApplyGameplayEffectSpecToSelf(*Spec.Data);
}

bool ARDCharacterBase::HasTag(const FGameplayTag& Tag) const
{
	return Asc->HasMatchingGameplayTag(Tag);
}

float ARDCharacterBase::TimeLeft(const FGameplayTag& Tag) const
{
	const UWorld* World = GetWorld();
	if (!World || !HasTag(Tag))
	{
		return 0.f;
	}
	float Left = 0.f;
	for (const FActiveGameplayEffectHandle& Handle : Asc->GetActiveEffects(FGameplayEffectQuery()))
	{
		const FActiveGameplayEffect* Active = Asc->GetActiveGameplayEffect(Handle);
		if (Active && Active->Spec.DynamicGrantedTags.HasTagExact(Tag))
		{
			Left = FMath::Max(Left, Active->GetTimeRemaining(World->GetTimeSeconds()));
		}
	}
	return Left;
}

void ARDCharacterBase::ApplyInstant(TSubclassOf<UGameplayEffect> Effect, float Amount, UAbilitySystemComponent* Target, bool bMelee)
{
	if (!Target)
	{
		return;
	}
	FGameplayEffectSpecHandle Spec = Asc->MakeOutgoingSpec(Effect, 1.f, Asc->MakeEffectContext());
	Spec.Data->SetSetByCallerMagnitude(RDTags::Data_Amount, Amount);
	if (bMelee)
	{
		Spec.Data->AddDynamicAssetTag(RDTags::Data_Melee);
	}
	Asc->ApplyGameplayEffectSpecToTarget(*Spec.Data, Target);
}

void ARDCharacterBase::PlayAnim(const TCHAR* Anim, bool bLoop, float Rate, bool bForce)
{
	const FName Key(Anim);
	if (Key == CurrentAnim && !bForce)
	{
		GetMesh()->SetPlayRate(Rate);
		return;
	}
	TObjectPtr<UAnimSequence>& Seq = AnimCache.FindOrAdd(Key);
	if (!Seq)
	{
		Seq = LoadObject<UAnimSequence>(nullptr, *RDAssets::Object(RDAssets::Characters, Model + Anim));
	}
	if (Seq)
	{
		GetMesh()->PlayAnimation(Seq, bLoop);
		GetMesh()->SetPlayRate(Rate);
		CurrentAnim = Key;
	}
}

void ARDCharacterBase::PlaySound(const TCHAR* Name, float Volume) const
{
	if (USoundBase* Sound = LoadObject<USoundBase>(nullptr, *RDAssets::Object(RDAssets::Audio, Name)))
	{
		UGameplayStatics::PlaySoundAtLocation(this, Sound, GetActorLocation(), Volume);
	}
}
