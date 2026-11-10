// ---------------------------------------------------------------------------
// GameKitJuiceDemo.h
// Purpose : The juice demo (debug builds, main menu > Juice demo), as on the LÖVE and Godot shells (#275): a box you
//           hit (attack) that shakes the camera with trauma, freezes the game for a hitstop, squashes on a spring
//           and flashes the screen through the flash limiter; a follow camera with a visible deadzone; an
//           input-buffered jump with coyote time; a held guard (interact) that honours hold_to_toggle; and the
//           accessibility settings applied live. Headless: the model steps it, SGameKitShell draws it, and
//           `dev.py smoke --drive show:juice` hits the box and proves each primitive took (DRIVE_JUICE).
// Usage   : FGameKitJuiceDemo Demo;  Demo.Enter(Model);                 // the model does this on "juice_demo"
//           Demo.Update(RealDeltaSeconds, Model);  Demo.Action(TEXT("attack"), Model);
// Notes   : Time: the hitstop and the flash limiter run on REAL time; everything else (shake, follow, spring, input
//           buffer, coyote) runs on GAME time = the hitstop-scaled dt times access.game_speed. The limiter is always
//           on (at most 3 flashes per real second); access.flash_limit only tones each flash down to FlashGentle.
//           Shake intensity is GameKit::EffectiveShake (0 with reduce motion). Movement reads the shell's analog
//           input (#274): the held move_* actions, else the left stick past its deadzone. World units are the
//           LÖVE demo's (a 640x360 view); the view scales them to the 1920x1080 design.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameKitAutoRepeat.h"
#include "GameKitCoyoteTimer.h"
#include "GameKitFlashLimiter.h"
#include "GameKitFollowCamera.h"
#include "GameKitHitstop.h"
#include "GameKitInputBuffer.h"
#include "GameKitShake.h"
#include "GameKitSpring.h"

class FGameKitShellModel;

struct GAMEKITSHELLUI_API FGameKitJuiceDemo
{
	// ---- Tunables (the LÖVE demo's, so the two feel alike) ----
	static constexpr double ViewW = 640.0;          // world units on screen
	static constexpr double ViewH = 360.0;
	static constexpr double CoyoteS = 0.1;          // coyote time before access.timing_scale
	static constexpr double WorldW = 1600.0;
	static constexpr double FloorY = 300.0;
	static constexpr double PlayerSize = 20.0;
	static constexpr double TargetSize = 40.0;
	static constexpr double TargetX = 440.0;
	static constexpr double StartX = 380.0;         // in reach of the box, so a first attack lands
	static constexpr double Speed = 160.0;
	static constexpr double Gravity = 900.0;
	static constexpr double JumpSpeed = 340.0;
	static constexpr double HitRange = 80.0;        // between centres
	static constexpr double HitTrauma = 0.55;
	static constexpr double HitStopS = 0.09;
	static constexpr double HitSquash = 0.45;       // spring displacement on a hit
	static constexpr double FlashS = 0.12;          // a flash fades out over this (real time)
	static constexpr double FlashFull = 0.85;       // peak flash opacity without access.flash_limit
	static constexpr double FlashGentle = 0.3;      // and with it
	static constexpr double PopS = 0.25;            // the hit ring eases out over this
	static constexpr double CamDeadzoneW = 96.0;    // the follow camera
	static constexpr double CamDeadzoneH = 64.0;
	static constexpr double CamLookahead = 0.2;
	static constexpr double CamSmoothing = 6.0;
	static constexpr double ShakeOffset = 10.0;     // shake at full trauma: units and radians
	static constexpr double ShakeAngle = 0.04;
	static constexpr double SpringFrequency = 4.0;  // the box's squash spring
	static constexpr double SpringDamping = 0.35;

	FGameKitJuiceDemo();

	/** Starts the demo: the goal for "What now?" and the guide's line. */
	void Enter(FGameKitShellModel& M);
	/** One frame: RealDt seconds of wall time (the hitstop scales it for everything but the flash). */
	void Update(double RealDt, FGameKitShellModel& M);
	/** jump, attack, interact (pause is the model's): true when the demo used it. */
	bool Action(const FString& Name, FGameKitShellModel& M);
	/** The box takes a hit when the player is in reach: trauma, hitstop, squash, a flash (if the limiter allows). */
	void Hit(FGameKitShellModel& M);
	/** The HUD's stats line (juice.stats): hits, trauma, the shake setting, flashes held back, game speed. */
	FString Stats(const FGameKitShellModel& M) const;

	// ---- State (the view and the drive read it) ----
	double PX = StartX, PY = FloorY - PlayerSize, VX = 0.0, VY = 0.0;
	FGameKitShake Shake;
	FGameKitHitstop Hitstop;
	FGameKitFollowCamera Cam;
	FGameKitInputBuffer Buffer;
	FGameKitCoyoteTimer Coyote;
	FGameKitAutoRepeat AttackRepeat;      // access.auto_repeat: a held attack repeats (#166)
	FGameKitSpring Spring;
	FGameKitFlashLimiter Limiter;
	FGameKitShakeOffset Offset;
	double RealTime = 0.0;
	double Flash = 0.0, FlashPeak = 0.0;
	double Pop = 0.0;
	int32 Hits = 0, Refused = 0, Jumps = 0;
	bool bGuard = false;
	bool bOnFloor = true;
	double TimingScale = 1.0;             // the access.timing_scale the windows were built for
};

// {{FOOTER}}
