// ---------------------------------------------------------------------------
// character.rs
// Purpose : Rigged glTF characters (#290): spawns a character .glb's first scene and keeps one of its named
//           animations playing on a loop. The clip is a field: change it and the character switches clips.
// Usage   : app.add_plugins(CharacterPlugin);   (DefaultPlugins has the glTF, scene and animation plugins it needs)
//           In a system:  let hero = spawn_character(&mut commands, &asset_server, "models/hero.glb", "idle");
//           Switch clips: characters.get_mut(hero)?.clip = "walk".into();   (the same name again changes nothing)
//           Play it again from the start: commands.entity(hero).insert(RestartClip);
//           Move the Character entity (its Transform): the clips are in place, nothing moves it for you.
// Notes   : Kit code: nothing here imports the game (src/game). The scene spawns as a child of the Character entity,
//           turned by GLTF_TO_BEVY_YAW so the model's front (glTF +Z) looks along the entity's Transform::forward()
//           (Bevy -Z). Once the scene's AnimationPlayer exists and the Gltf asset has loaded, an AnimationGraph is
//           built from the file's named animations (one node per clip, sorted by name) and CharacterAnimator on the
//           player entity maps each name to its node. An unknown clip name logs one WARN and stops the animation.
//           The kit's rule in every engine (#296): asking for the clip that is already playing changes nothing (it
//           keeps its time), so setting `clip` every frame is fine; a restart is explicit (RestartClip).
//           Units are the file's: glTF is metres, 1 Bevy unit = 1 m. Headless works: tests/character.rs runs it with
//           no window or GPU.
//
// Pseudocode:
//   spawn_character: Character { gltf, clip } entity -> child WorldAssetRoot(file#Scene0) turned 180 degrees about Y
//   Update, chained: attach (an AnimationPlayer without CharacterAnimator, under a Character whose Gltf loaded ->
//   graph from named_animations -> AnimationGraphHandle + CharacterAnimator) -> play (the Character's clip differs
//   from the one playing, or RestartClip is on the Character -> stop all, play its node from 0, repeat; remove
//   RestartClip)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): RestartClip, the explicit restart (#296)
// ---------------------------------------------------------------------------
use std::collections::HashMap;
use std::f32::consts::PI;

use bevy::gltf::{Gltf, GltfAssetLabel};
use bevy::prelude::*;

// ---- Tunables ------------------------------------------------------------------
/// Yaw of the scene under its Character entity: glTF's front is +Z, Bevy's forward is -Z, so half a turn.
pub const GLTF_TO_BEVY_YAW: f32 = PI;

/// Plays the clips of every Character. Needs AssetPlugin and the glTF, world-asset (scene) and animation plugins.
pub struct CharacterPlugin;

impl Plugin for CharacterPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Update, (attach_animator, play_clip).chain());
    }
}

/// A rigged glTF character. Its scene is a child entity; this entity is the one the game moves.
#[derive(Component, Debug, Clone)]
#[require(Transform, Visibility)]
pub struct Character {
    /// The whole file: its named_animations become the clips.
    pub gltf: Handle<Gltf>,
    /// The clip playing on a loop, a name from the file's animations ("idle", "walk"). Set it to switch.
    pub clip: String,
}

/// Insert on a Character entity to play its clip again from the start. Setting `clip` to the name already playing
/// changes nothing (#296: the same rule in every engine's character helper); this is the explicit restart. It is
/// removed once the clip restarted.
#[derive(Component, Debug, Clone, Copy, Default)]
pub struct RestartClip;

/// On the scene's AnimationPlayer entity once the character's clips are set up.
#[derive(Component, Debug, Clone)]
pub struct CharacterAnimator {
    /// The Character entity this player belongs to.
    pub character: Entity,
    /// Every named animation in the file and its node in the player's AnimationGraph.
    pub clips: HashMap<String, AnimationNodeIndex>,
    /// The clip the player was last told to play (None before the first one).
    pub playing: Option<String>,
}

/// Spawns a character from a .glb under `assets/` playing `clip` on a loop, facing the entity's forward (-Z).
/// Returns the Character entity (move and turn that one).
pub fn spawn_character(commands: &mut Commands, server: &AssetServer, path: &str, clip: &str) -> Entity {
    let character = commands
        .spawn(Character {
            gltf: server.load(path.to_owned()),
            clip: clip.into(),
        })
        .id();
    commands.spawn((
        WorldAssetRoot(server.load(GltfAssetLabel::Scene(0).from_asset(path.to_owned()))),
        Transform::from_rotation(Quat::from_rotation_y(GLTF_TO_BEVY_YAW)),
        ChildOf(character),
    ));
    character
}

/// The clip names of a loaded glTF file, sorted.
pub fn clip_names(gltf: &Gltf) -> Vec<String> {
    let mut names: Vec<String> = gltf.named_animations.keys().map(|k| k.to_string()).collect();
    names.sort();
    names
}

fn attach_animator(
    mut commands: Commands,
    players: Query<Entity, (With<AnimationPlayer>, Without<CharacterAnimator>)>,
    parents: Query<&ChildOf>,
    characters: Query<&Character>,
    gltfs: Res<Assets<Gltf>>,
    mut graphs: ResMut<Assets<AnimationGraph>>,
) {
    for player in &players {
        let Some((owner, character)) = parents
            .iter_ancestors(player)
            .find_map(|e| characters.get(e).ok().map(|c| (e, c)))
        else {
            continue; // an AnimationPlayer that is not a Character's
        };
        let Some(gltf) = gltfs.get(&character.gltf) else {
            continue; // the file is still loading: try again next frame
        };
        let names = clip_names(gltf);
        let (graph, nodes) =
            AnimationGraph::from_clips(names.iter().map(|n| gltf.named_animations[n.as_str()].clone()));
        commands.entity(player).insert((
            AnimationGraphHandle(graphs.add(graph)),
            CharacterAnimator {
                character: owner,
                clips: names.into_iter().zip(nodes).collect(),
                playing: None,
            },
        ));
    }
}

fn play_clip(
    mut commands: Commands,
    mut players: Query<(&mut AnimationPlayer, &mut CharacterAnimator)>,
    characters: Query<(&Character, Has<RestartClip>)>,
) {
    for (mut player, mut animator) in &mut players {
        let Ok((character, restart)) = characters.get(animator.character) else {
            continue;
        };
        if restart {
            commands.entity(animator.character).remove::<RestartClip>();
        } else if animator.playing.as_deref() == Some(character.clip.as_str()) {
            continue; // the clip asked for is the one playing: keep its time (#296)
        }
        player.stop_all();
        match animator.clips.get(&character.clip) {
            Some(&node) => {
                player.play(node).repeat();
            }
            None => warn!(
                "character clip '{}' not found; the file has {:?}",
                character.clip,
                animator.clips.keys().collect::<Vec<_>>()
            ),
        }
        animator.playing = Some(character.clip.clone());
    }
}

// {{FOOTER}}
