# ADR 0001: The Gameplay Ability System, all in C++

- Status: accepted
- Date: 2026-10-22

## Context
Pillar 1 (timing beats spam) needs spells with mana costs, cooldowns, a timed ward and a stagger that changes damage.
That is what Unreal's Gameplay Ability System (GAS) is for. The kit's rule for Unreal (docs/ENGINE.md, "the big rule") is
that Claude edits C++ and text, not Blueprint graphs or binary assets, and this example is built without the editor UI.

## Options considered
1. **GAS, everything in C++**: abilities, effects and the attribute set as C++ classes, native gameplay tags, numbers
   passed as SetByCaller magnitudes from the ini tunables. No Blueprint, no effect assets.
2. **GAS the usual way**: C++ base classes, Blueprint abilities and Gameplay Effect assets made in the editor.
3. **No GAS**: plain C++ components for mana, cooldowns and status timers.

## Decision
Option 1. GAS 5.8 can be driven entirely from code: effect components (`UTargetTagsGameplayEffectComponent`), spec
`DynamicGrantedTags` and SetByCaller were all checked in the engine source before writing. One `URDEffect_Timed` with a
dynamic tag serves every cooldown, the ward, the stagger and the dash.

## Consequences
- Good: the whole combat model is reviewable text; costs and cooldowns come from `Config/DefaultGame.ini` at the moment
  of use, so a tuning change needs no asset edit; the hit rules are a plain function with unit tests (`RDRules`).
- Bad / costs: designers cannot tweak a spell in the editor; cost and cooldown are overridden (`CheckCost`, `ApplyCost`,
  `ApplyCooldown`) instead of using GAS's asset-based defaults.
- What we would need to see to revisit this: a designer who wants to own the spells (then Blueprint children of these
  C++ abilities, with the numbers still read from the ini).
