// ---------------------------------------------------------------------------
// GameKitFollowCamera.h
// Purpose : Camera follow logic: a deadzone box around the camera, look-ahead along the target's velocity,
//           and frame-rate independent exponential smoothing. Two axes, no world: feed it positions.
// Usage   : FGameKitFollowCamera Follow(64.0, 48.0, 0.25, 8.0, Start.X, Start.Y);
//           each Tick: const FVector2D Cam = Follow.Update(DeltaSeconds, Target.X, Target.Y, Vel.X, Vel.Y);
//                      put the camera (or a spring arm's target) at Cam on the two axes your game uses
// Notes   : The target moves freely inside the deadzone; at its edge the camera is pushed along. Look-ahead
//           (seconds of velocity) shows more of where the player is heading. Smoothing is a rate: the same
//           motion at 30 and 144 fps, and 0 snaps. Matches tools/golden_vectors.py (Follow), checked against
//           data/golden/juice.json.
//
// Pseudocode:
//   per axis: desired = camera, or pushed so the target sits on the deadzone edge; desired += velocity * lookahead
//   k = 1 - exp(-smoothing * dt) (1 when smoothing is 0) ; camera += (desired - camera) * k
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double FollowDeadzoneWidth = 64.0;    // units the target may move sideways before the camera follows
	inline constexpr double FollowDeadzoneHeight = 48.0;
	inline constexpr double FollowLookahead = 0.25;        // seconds of target velocity to lead by
	inline constexpr double FollowSmoothing = 8.0;         // 1/s; higher catches up faster, 0 snaps
}

class FGameKitFollowCamera
{
public:
	explicit FGameKitFollowCamera(double InDeadzoneWidth = GameKit::FollowDeadzoneWidth,
	                              double InDeadzoneHeight = GameKit::FollowDeadzoneHeight,
	                              double InLookahead = GameKit::FollowLookahead, double InSmoothing = GameKit::FollowSmoothing,
	                              double StartX = 0.0, double StartY = 0.0)
		: DeadzoneWidth(InDeadzoneWidth), DeadzoneHeight(InDeadzoneHeight), Lookahead(InLookahead), Smoothing(InSmoothing),
		  X(StartX), Y(StartY)
	{
	}

	/** Moves the camera toward the target (Tx, Ty) moving at (Vx, Vy) and returns the new camera position. */
	FVector2D Update(double Dt, double Tx, double Ty, double Vx = 0.0, double Vy = 0.0)
	{
		const double Dx = Axis(X, Tx, DeadzoneWidth / 2.0) + Vx * Lookahead;
		const double Dy = Axis(Y, Ty, DeadzoneHeight / 2.0) + Vy * Lookahead;
		const double K = Smoothing > 0.0 ? 1.0 - FMath::Exp(-Smoothing * Dt) : 1.0;
		X += (Dx - X) * K;
		Y += (Dy - Y) * K;
		return FVector2D(X, Y);
	}

	/** Jumps the camera (a respawn, a room change), with no smoothing. */
	void SnapTo(double InX, double InY)
	{
		X = InX;
		Y = InY;
	}

	double GetX() const { return X; }
	double GetY() const { return Y; }

private:
	/** Where the camera wants to be on one axis so the target stays within +-Half of it. */
	static double Axis(double Cam, double Target, double Half)
	{
		if (Target > Cam + Half)
		{
			return Target - Half;
		}
		if (Target < Cam - Half)
		{
			return Target + Half;
		}
		return Cam;
	}

	double DeadzoneWidth;
	double DeadzoneHeight;
	double Lookahead;
	double Smoothing;
	double X;
	double Y;
};

// {{FOOTER}}
