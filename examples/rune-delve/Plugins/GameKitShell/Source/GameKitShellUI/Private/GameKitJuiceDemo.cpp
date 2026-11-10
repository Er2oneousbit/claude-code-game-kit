// ---------------------------------------------------------------------------
// GameKitJuiceDemo.cpp
// Purpose : The juice demo's rules behind GameKitJuiceDemo.h (the LÖVE demo's juice_demo.lua, line for line).
// Usage   : compiled into the GameKitShellUI module; FGameKitShellModel runs it on the "juice_demo" screen.
// Notes   : The timing windows (input buffer, coyote time) are rebuilt when access.timing_scale changes, since the
//           primitives take their window in the constructor.
//
// Pseudocode:
//   Update(real dt): real time and the flash fade on real dt -> dt = hitstop.ScaledDt(real dt) * game_speed
//     -> move (held move_* else the stick's x) -> gravity, floor -> timing windows from timing_scale
//     -> auto-repeat a held attack -> coyote, buffer -> a buffered jump with coyote time jumps
//     -> guard (held interact, or the toggle) -> camera follow, shake, spring, the hit ring
//   Hit: in reach -> trauma, hitstop, squash, ring; a flash if the limiter allows it (else one more refused)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitJuiceDemo.h"

#include "GameKitSettings.h"
#include "GameKitShellModel.h"

namespace
{
	const TCHAR* GuideSpeaker = TEXT("Guide");
	const TCHAR* ObjectiveKey = TEXT("juice.objective");
	const FName JumpAction(TEXT("jump"));
}

FGameKitJuiceDemo::FGameKitJuiceDemo()
	: Shake(ShakeOffset, ShakeAngle)
	, Cam(CamDeadzoneW, CamDeadzoneH, CamLookahead, CamSmoothing, StartX, FloorY - 80.0)
	, Coyote(CoyoteS)
	, Spring(SpringFrequency, SpringDamping)
{
}

void FGameKitJuiceDemo::Enter(FGameKitShellModel& M)
{
	M.SetObjective(M.T(ObjectiveKey));   // what "What now?" on the pause menu says (#167)
	M.Say(GuideSpeaker, M.T(ObjectiveKey));
}

bool FGameKitJuiceDemo::Action(const FString& Name, FGameKitShellModel& M)
{
	if (Name == TEXT("jump"))
	{
		Buffer.Press(JumpAction);
		return true;
	}
	if (Name == TEXT("attack"))
	{
		Hit(M);
		return true;
	}
	if (Name == TEXT("interact"))
	{
		if (M.Flag(TEXT("access"), TEXT("hold_to_toggle")))
		{
			bGuard = !bGuard;
		}
		return true;
	}
	return false;
}

void FGameKitJuiceDemo::Hit(FGameKitShellModel& M)
{
	if (FMath::Abs((PX + PlayerSize / 2) - (TargetX + TargetSize / 2)) > HitRange)
	{
		return;
	}
	++Hits;
	Shake.AddTrauma(HitTrauma);
	Hitstop.Hit(HitStopS);
	Spring.X = HitSquash;
	Pop = PopS;
	if (Limiter.Request(RealTime))   // real time: always rate-limited
	{
		Flash = FlashS;
		FlashPeak = M.Flag(TEXT("access"), TEXT("flash_limit")) ? FlashGentle : FlashFull;
	}
	else
	{
		++Refused;
	}
}

FString FGameKitJuiceDemo::Stats(const FGameKitShellModel& M) const
{
	FGameKitTrArgs A;
	A.Add(TEXT("hits"), FString::FromInt(Hits));
	A.Add(TEXT("trauma"), FString::Printf(TEXT("%.2f"), Shake.GetTrauma()));
	A.Add(TEXT("shake"), FString::Printf(TEXT("%.2f"), GameKit::EffectiveShake(*M.Settings)));
	A.Add(TEXT("refused"), FString::FromInt(Refused));
	A.Add(TEXT("speed"), FString::FromInt(FMath::RoundToInt(M.Num(TEXT("access"), TEXT("game_speed")) * 100.0)));
	return M.T(TEXT("juice.stats"), A);
}

void FGameKitJuiceDemo::Update(double RealDt, FGameKitShellModel& M)
{
	RealTime += RealDt;
	Flash = FMath::Max(0.0, Flash - RealDt);
	const double Dt = Hitstop.ScaledDt(RealDt) * FMath::Max(0.0, M.Num(TEXT("access"), TEXT("game_speed")));   // game time
	// move: the held move_* actions, else the stick (#274)
	double Dir = (M.IsHeld(TEXT("move_right")) ? 1.0 : 0.0) - (M.IsHeld(TEXT("move_left")) ? 1.0 : 0.0);
	if (Dir == 0.0)
	{
		Dir = M.Stick().X;
	}
	VX = Dir * Speed;
	PX = FMath::Clamp(PX + VX * Dt, 0.0, WorldW - PlayerSize);
	VY += Gravity * Dt;
	PY += VY * Dt;
	// on the floor only when not rising: a jump made during a hitstop (game dt 0) keeps its speed
	bOnFloor = PY >= FloorY - PlayerSize && VY >= 0.0;
	if (bOnFloor)
	{
		PY = FloorY - PlayerSize;
		VY = 0.0;
	}
	// access.timing_scale (#166): every timing window, longer by the player's factor
	const double K = FMath::Max(1.0, M.Num(TEXT("access"), TEXT("timing_scale")));
	if (K != TimingScale)
	{
		TimingScale = K;
		Buffer = FGameKitInputBuffer(GameKit::InputBufferWindow * K);
		Coyote = FGameKitCoyoteTimer(CoyoteS * K);
	}
	if (M.Flag(TEXT("access"), TEXT("auto_repeat")) && AttackRepeat.Update(Dt, M.IsHeld(TEXT("attack"))))
	{
		Hit(M);
	}
	Coyote.Update(Dt, bOnFloor);
	Buffer.Update(Dt);
	if (Coyote.CanJump() && Buffer.Consume(JumpAction))
	{
		VY = -JumpSpeed;
		Coyote.Consume();
		++Jumps;
	}
	if (!M.Flag(TEXT("access"), TEXT("hold_to_toggle")))
	{
		bGuard = M.IsHeld(TEXT("interact"));
	}
	Cam.Update(Dt, PX + PlayerSize / 2, PY, VX, 0.0);
	Offset = Shake.Update(Dt, GameKit::EffectiveShake(*M.Settings));
	Spring.Update(Dt);
	Pop = FMath::Max(0.0, Pop - Dt);
}
