// ---------------------------------------------------------------------------
// GameKitAnalog.h
// Purpose : Analog input shaping (#274): the left stick and the triggers as the game reads them, after the player's
//           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is
//           in. The same rules as the Bevy shell's logic/analog.rs.
// Usage   : const FVector2D Move = GameKit::AnalogStick(RawX, RawY, Deadzone, bInvertY);   // up is +Y
//           const double Gas = GameKit::AnalogTrigger(RawR2);                               // 0..1
// Notes   : No engine types beyond FVector2D. The stick deadzone is radial (the length of the vector, not each axis),
//           and what is left is rescaled to 0..1, so a stick just past the deadzone gives a small value instead of
//           jumping to the deadzone's size; the direction never changes. Up is +Y (Unreal's Gamepad_LeftY);
//           invert_y flips it. Triggers have their own small fixed deadzone: input.deadzone is the "Stick deadzone"
//           setting, and a trigger that rests at 0.1 would otherwise lose a fifth of its travel. NaN and infinities
//           (a broken driver) count as 0.
//
// Pseudocode:
//   AnalogStick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
//     -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
//   AnalogTrigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr double TriggerDeadzone = 0.05;   // trigger travel ignored at rest (0 to 1)
	inline constexpr double MaxDeadzone = 0.95;       // the largest deadzone accepted; keeps the rescale finite

	/** V, or 0 when it is NaN or infinite. */
	inline double AnalogFinite(double V)
	{
		return FMath::IsFinite(V) ? V : 0.0;
	}

	/** The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1. */
	inline FVector2D AnalogStick(double X, double Y, double Deadzone, bool bInvertY)
	{
		X = AnalogFinite(X);
		Y = AnalogFinite(Y);
		if (bInvertY)
		{
			Y = -Y;
		}
		const double Dz = FMath::Clamp(AnalogFinite(Deadzone), 0.0, MaxDeadzone);
		const double Len = FMath::Sqrt(X * X + Y * Y);
		if (Len <= Dz || Len == 0.0)
		{
			return FVector2D::ZeroVector;
		}
		const double Scale = FMath::Min((Len - Dz) / (1.0 - Dz), 1.0) / Len;
		return FVector2D(X * Scale, Y * Scale);
	}

	/** A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1. */
	inline double AnalogTrigger(double Value, double Deadzone = TriggerDeadzone)
	{
		const double V = FMath::Clamp(AnalogFinite(Value), 0.0, 1.0);
		const double Dz = FMath::Clamp(AnalogFinite(Deadzone), 0.0, MaxDeadzone);
		return V <= Dz ? 0.0 : (V - Dz) / (1.0 - Dz);
	}
}
