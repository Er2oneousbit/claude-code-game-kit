// ---------------------------------------------------------------------------
// RDMage.cpp
// Purpose : See RDMage.h.
//
// Pseudocode (each tick):
//   dash in progress -> slide along DashVelocity (swept) for min(dt, time left), nothing else moves us;
//                       the dodge tag lasts exactly as long as the slide
//   bot -> snapshot from the game mode -> RDBot::Decide -> path towards MoveTo, aim, cast
//   player -> aim from the mouse (or the right stick), move from WASD (or the left stick)
//   face the aim point; the ward light shows while State.Warded is on
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes: the dash slides exactly DashDistance at any frame rate and dodges for the
//           whole slide (State.Dashing follows DashLeft); the mage ignores its own bolts when moving, so a dash
//           behind a fresh bolt is not blocked by it; SetAimForTest for the regression tests
// ---------------------------------------------------------------------------
#include "Game/RDMage.h"

#include "AbilitySystemComponent.h"
#include "Abilities/RDAbilities.h"
#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "Camera/CameraComponent.h"
#include "Components/PointLightComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Game/RDBolt.h"
#include "Game/RDCommon.h"
#include "Game/RDGameMode.h"
#include "Game/RDTuning.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "NavigationPath.h"
#include "NavigationSystem.h"
#include "Perception/AISense_Hearing.h"

ARDMage::ARDMage()
{
	SetupBody(TEXT("character-human"));
	bUseControllerRotationYaw = false;
	GetCharacterMovement()->bOrientRotationToMovement = false;
	GetCharacterMovement()->MaxAcceleration = 4000.f;
	GetCharacterMovement()->BrakingDecelerationWalking = 4000.f;

	Arm = CreateDefaultSubobject<USpringArmComponent>(TEXT("Arm"));
	Arm->SetupAttachment(RootComponent);
	Arm->SetUsingAbsoluteRotation(true);
	Arm->SetWorldRotation(FRotator(CameraPitch, 0.f, 0.f));
	Arm->TargetArmLength = CameraDistance;
	Arm->bDoCollisionTest = false;
	Arm->bEnableCameraLag = true;
	Arm->CameraLagSpeed = 8.f;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(Arm);
	Camera->SetFieldOfView(55.f);

	RuneLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("RuneLight"));
	RuneLight->SetupAttachment(RootComponent);
	RuneLight->SetRelativeLocation(FVector(40.f, 30.f, 40.f));
	RuneLight->SetLightColor(FLinearColor(0.35f, 0.55f, 1.f));
	RuneLight->SetIntensity(2500.f);
	RuneLight->SetAttenuationRadius(450.f);
	RuneLight->SetCastShadows(false);

	WardLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("WardLight"));
	WardLight->SetupAttachment(RootComponent);
	WardLight->SetRelativeLocation(FVector(0.f, 0.f, 60.f));
	WardLight->SetLightColor(FLinearColor(0.3f, 0.8f, 1.f));
	WardLight->SetIntensity(0.f);
	WardLight->SetAttenuationRadius(380.f);
	WardLight->SetCastShadows(false);
}

void ARDMage::BeginPlay()
{
	Super::BeginPlay();
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	InitStats(N.MageHealth, N.MageMana);
	GetCharacterMovement()->MaxWalkSpeed = N.MageSpeed;
	Asc->GiveAbility(FGameplayAbilitySpec(URDAbility_Bolt::StaticClass()));
	Asc->GiveAbility(FGameplayAbilitySpec(URDAbility_Ward::StaticClass()));
	Asc->GiveAbility(FGameplayAbilitySpec(URDAbility_Dash::StaticClass()));
	FGameplayEffectSpecHandle Regen = Asc->MakeOutgoingSpec(URDEffect_ManaRegen::StaticClass(), 1.f, Asc->MakeEffectContext());
	Regen.Data->SetSetByCallerMagnitude(RDTags::Data_Amount, N.ManaRegen * URDEffect_ManaRegen::PeriodSeconds);
	Asc->ApplyGameplayEffectSpecToSelf(*Regen.Data);
	Bot = FRDLaunchOptions::Get().Bot;
	Aim = Ground() + FVector2D(500.f, 0.f);
	PlayAnim(TEXT("idle"), true);
}

bool ARDMage::IsGod() const
{
	return FRDLaunchOptions::Get().bGod;
}

bool ARDMage::CastSpell(TSubclassOf<URDAbility> Ability)
{
	return IsAlive() && Asc->TryActivateAbilityByClass(Ability);
}

void ARDMage::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	WardLight->SetIntensity(HasTag(RDTags::State_Warded) ? 30000.f : 0.f);
	if (!IsAlive())
	{
		return;
	}
	if (DashLeft > 0.f)
	{
		// Never step past the end of the slide: a whole frame's step at the end overshot by up to a frame at low fps
		const float Step = FMath::Min(DeltaSeconds, DashLeft);
		AddActorWorldOffset(DashVelocity * Step, true);
		DashLeft -= Step;
		if (DashLeft <= 0.f)
		{
			DashLeft = 0.f;
			Asc->SetLooseGameplayTagCount(RDTags::State_Dashing, 0);
		}
		return;
	}
	if (Bot != ERDBotMode::None)
	{
		DriveBot(DeltaSeconds);
	}
	else
	{
		UpdatePlayerAim();
		AddMovementInput(FVector(MoveInput.Y, MoveInput.X, 0.f));
	}
	const FVector2D Face = Aim - Ground();
	if (!Face.IsNearlyZero())
	{
		SetActorRotation(FRotator(0.f, FMath::RadiansToDegrees(FMath::Atan2(Face.Y, Face.X)), 0.f));
	}
	if (CurrentAnim != FName(TEXT("holding-right-shoot")) || !GetMesh()->IsPlaying())
	{
		const float Speed = GetVelocity().Size2D();
		PlayAnim(Speed > 20.f ? TEXT("walk") : TEXT("idle"), true, Speed > 20.f ? Speed / 300.f : 1.f);
	}
}

void ARDMage::UpdatePlayerAim()
{
	if (bTestAim)
	{
		return;
	}
	if (StickAim.SizeSquared() > 0.09f)
	{
		Aim = Ground() + FVector2D(StickAim.Y, StickAim.X).GetSafeNormal() * 600.f;
		return;
	}
	APlayerController* Pc = Cast<APlayerController>(GetController());
	FVector From, Dir;
	if (Pc && Pc->DeprojectMousePositionToWorld(From, Dir) && FMath::Abs(Dir.Z) > KINDA_SMALL_NUMBER)
	{
		const float T = (GetActorLocation().Z - From.Z) / Dir.Z;   // where the cursor ray meets the mage's height
		if (T > 0.f)
		{
			Aim = FVector2D(From + Dir * T);
		}
	}
}

void ARDMage::DriveBot(float DeltaSeconds)
{
	ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>();
	if (!Game || Game->GetOutcome() != ERDOutcome::Playing)
	{
		return;
	}
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	const FRDBotAction A = RDBot::Decide(Bot, Game->BotSnapshot(), N);
	LastReason = A.Reason;
	if (A.bAim)
	{
		Aim = A.AimAt;
	}
	else if (A.bMove)
	{
		Aim = A.MoveTo;   // nothing to shoot at: look where we walk
	}
	if (A.bMove)
	{
		MoveAlongPath(A.MoveTo, DeltaSeconds);
	}
	if (A.bWard)
	{
		CastSpell(URDAbility_Ward::StaticClass());
	}
	if (A.bBolt)
	{
		CastSpell(URDAbility_Bolt::StaticClass());
	}
	if (A.bDash)
	{
		DashDirOverride = A.DashDir;
		CastSpell(URDAbility_Dash::StaticClass());
		DashDirOverride = FVector2D::ZeroVector;
	}
}

void ARDMage::MoveAlongPath(const FVector2D& To, float DeltaSeconds)
{
	RepathTimer -= DeltaSeconds;
	if (RepathTimer <= 0.f || FVector2D::Distance(To, PathGoal) > 150.f)
	{
		RepathTimer = RepathSeconds;
		PathGoal = To;
		Path.Reset();
		const FVector Goal(To, GetActorLocation().Z);
		if (UNavigationPath* Nav = UNavigationSystemV1::FindPathToLocationSynchronously(this, GetActorLocation(), Goal, this))
		{
			Path = Nav->PathPoints;
		}
		if (Path.Num() == 0)
		{
			Path.Add(Goal);   // no NavMesh answer: walk straight, the colliders still stop us
		}
	}
	while (Path.Num() > 1 && FVector2D::Distance(Ground(), FVector2D(Path[0])) < 60.f)
	{
		Path.RemoveAt(0);
	}
	if (Path.Num() > 0)
	{
		AddMovementInput(FVector(FVector2D(Path[0]) - Ground(), 0.f).GetSafeNormal());
	}
}

void ARDMage::FireBolt(const FRDNumbers& N)
{
	const FVector2D Dir = (Aim - Ground()).GetSafeNormal();
	const FVector2D Forward = Dir.IsNearlyZero() ? FVector2D(GetActorForwardVector()) : Dir;
	const FVector Start = GetActorLocation() + FVector(Forward * 55.f, 10.f);
	FActorSpawnParameters Params;
	Params.Owner = this;
	Params.Instigator = this;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	if (ARDBolt* Bolt = GetWorld()->SpawnActor<ARDBolt>(ARDBolt::StaticClass(), Start, FVector(Forward, 0.f).Rotation(), Params))
	{
		// Both ways: the bolt already ignores us; without this our own sweep (walking, dashing) hits the bolt
		MoveIgnoreActorAdd(Bolt);
		Bolt->Launch(this, FVector(Forward, 0.f), N);
	}
	UAISense_Hearing::ReportNoiseEvent(this, GetActorLocation(), 1.f, this, N.BoltNoise);
	PlayAnim(TEXT("holding-right-shoot"), false, 1.f, true);
	PlaySound(TEXT("bolt-cast"), 0.5f);
	++BoltsCast;
}

void ARDMage::RaiseWard(const FRDNumbers& N)
{
	ApplyTimedTag(RDTags::State_Warded, N.WardSeconds);
	PlaySound(TEXT("ward-raise"), 0.6f);
	++WardsCast;
}

void ARDMage::StartDash(const FRDNumbers& N)
{
	FVector2D Dir = DashDirOverride;
	if (Dir.IsNearlyZero())
	{
		Dir = FVector2D(MoveInput.Y, MoveInput.X);
	}
	if (Dir.IsNearlyZero())
	{
		Dir = (Aim - Ground());
	}
	Dir = Dir.GetSafeNormal();
	DashVelocity = FVector(Dir * (N.DashDistance / N.DashSeconds), 0.f);
	DashLeft = N.DashSeconds;
	// A loose tag, cleared in Tick when the slide ends: a timed effect runs on world time and could end a frame
	// before or after the slide
	Asc->SetLooseGameplayTagCount(RDTags::State_Dashing, 1);
	PlaySound(TEXT("mage-dash"), 0.6f);
}

void ARDMage::OnHurt(float Damage, ARDCharacterBase* Source)
{
	DamageTaken += Damage;
	PlaySound(TEXT("mage-hurt"), 0.8f);
}

void ARDMage::OnWardBlock(ARDCharacterBase* Attacker)
{
	++WardBlocks;
	PlaySound(TEXT("ward-block"));
	RD_MARK(TEXT("WARD_BLOCK"));
}

void ARDMage::OnDodged()
{
	RD_MARK(TEXT("DODGE"));
}

void ARDMage::OnZeroHealth(ARDCharacterBase* Killer)
{
	PlayAnim(TEXT("die"), false, 1.f, true);
	GetCharacterMovement()->DisableMovement();
	if (ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>())
	{
		Game->OnMageDied();
	}
}

// ---- Input --------------------------------------------------------------------------------------
void ARDMage::BuildInput()
{
	Mapping = NewObject<UInputMappingContext>(this);
	auto Make = [this](EInputActionValueType Type) {
		UInputAction* A = NewObject<UInputAction>(this);
		A->ValueType = Type;
		return A;
	};
	MoveAction = Make(EInputActionValueType::Axis2D);
	AimAction = Make(EInputActionValueType::Axis2D);
	BoltAction = Make(EInputActionValueType::Boolean);
	WardAction = Make(EInputActionValueType::Boolean);
	DashAction = Make(EInputActionValueType::Boolean);
	RestartAction = Make(EInputActionValueType::Boolean);

	// WASD to a 2D axis: x = D/A, y = W/S (the usual swizzle and negate modifiers)
	auto Key = [this](const FKey& K, bool bSwizzle, bool bNegate) {
		FEnhancedActionKeyMapping& M = Mapping->MapKey(MoveAction, K);
		if (bSwizzle)
		{
			M.Modifiers.Add(NewObject<UInputModifierSwizzleAxis>(this));
		}
		if (bNegate)
		{
			M.Modifiers.Add(NewObject<UInputModifierNegate>(this));
		}
	};
	Key(EKeys::D, false, false);
	Key(EKeys::A, false, true);
	Key(EKeys::W, true, false);
	Key(EKeys::S, true, true);
	Mapping->MapKey(MoveAction, EKeys::Gamepad_Left2D);
	Mapping->MapKey(AimAction, EKeys::Gamepad_Right2D);
	Mapping->MapKey(BoltAction, EKeys::LeftMouseButton);
	Mapping->MapKey(BoltAction, EKeys::Gamepad_RightTrigger);
	Mapping->MapKey(WardAction, EKeys::RightMouseButton);
	Mapping->MapKey(WardAction, EKeys::Gamepad_LeftTrigger);
	Mapping->MapKey(DashAction, EKeys::SpaceBar);
	Mapping->MapKey(DashAction, EKeys::Gamepad_FaceButton_Bottom);
	Mapping->MapKey(RestartAction, EKeys::R);
	Mapping->MapKey(RestartAction, EKeys::Gamepad_Special_Right);
}

void ARDMage::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	BuildInput();
	if (APlayerController* Pc = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Sub = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(Pc->GetLocalPlayer()))
		{
			Sub->AddMappingContext(Mapping, 0);
		}
	}
	if (UEnhancedInputComponent* Input = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		Input->BindAction(MoveAction, ETriggerEvent::Triggered, this, &ARDMage::OnMove);
		Input->BindAction(MoveAction, ETriggerEvent::Completed, this, &ARDMage::OnMoveStop);
		Input->BindAction(AimAction, ETriggerEvent::Triggered, this, &ARDMage::OnStickAim);
		Input->BindAction(BoltAction, ETriggerEvent::Triggered, this, &ARDMage::OnBolt);   // hold to keep casting
		Input->BindAction(WardAction, ETriggerEvent::Started, this, &ARDMage::OnWard);
		Input->BindAction(DashAction, ETriggerEvent::Started, this, &ARDMage::OnDash);
		Input->BindAction(RestartAction, ETriggerEvent::Started, this, &ARDMage::OnRestart);
	}
	else
	{
		UE_LOG(LogRuneDelve, Error, TEXT("input component is not an EnhancedInputComponent (check Config/DefaultInput.ini)"));
	}
}

void ARDMage::OnMove(const FInputActionValue& Value)
{
	MoveInput = Value.Get<FVector2D>();
}

void ARDMage::OnBolt(const FInputActionValue& Value)
{
	if (Bot == ERDBotMode::None)
	{
		CastSpell(URDAbility_Bolt::StaticClass());
	}
}

void ARDMage::OnWard(const FInputActionValue& Value)
{
	if (Bot == ERDBotMode::None)
	{
		CastSpell(URDAbility_Ward::StaticClass());
	}
}

void ARDMage::OnDash(const FInputActionValue& Value)
{
	if (Bot == ERDBotMode::None)
	{
		CastSpell(URDAbility_Dash::StaticClass());
	}
}

void ARDMage::OnRestart(const FInputActionValue& Value)
{
	if (ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>())
	{
		Game->RestartDelve();
	}
}
