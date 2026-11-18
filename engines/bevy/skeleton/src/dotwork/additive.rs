// ---------------------------------------------------------------------------
// dotwork/additive.rs
// Purpose : Additive blending for Dotwork's `blend: add` clips (fire, sparks, spells; #286). Bevy 0.20's sprites
//           have no additive mode (SpriteAlphaMode is Opaque, Mask or Blend), so an additive clip is drawn as a
//           2D mesh quad instead: Bevy's own ColorMaterial (texture, tint, uv transform) extended by AdditiveBlend,
//           whose only job is to set the pipeline's colour blend to src * alpha + dst.
// Usage   : DotworkPlugin adds the material and the animate_additive system; Dotwork::spawn_clip draws an additive
//           clip this way by itself. Dotwork::additive_clip_bundle switches an additive entity's clip.
// Notes   : The quad is the frame size with the pivot on the entity's origin (the mesh moved by -anchor * size, as
//           a Sprite's Anchor does); a sheet clip shows frame i by the material's uv_transform over the sheet (uv
//           0, 0 is the image's top-left on Bevy's Rectangle mesh), a clip of loose frames by swapping the texture.
//           The alpha channel of the target is kept (dst alpha * 1), so an additive effect never makes the screen
//           more opaque. The sampler is the image's own (Dotwork's images load nearest, no mipmaps).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::material::descriptor::RenderPipelineDescriptor;
use bevy::material::specialize::SpecializedMeshPipelineError;
use bevy::math::{Affine2, URect, UVec2};
use bevy::mesh::MeshVertexBufferLayoutRef;
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, BlendComponent, BlendFactor, BlendOperation, BlendState};
use bevy::sprite_render::{AlphaMode2d, Material2dKey, Material2dPipeline, MaterialExtension2d};

use super::{DotworkAnimation, FrameImage};

// ---- Tunables ------------------------------------------------------------------
/// The blend an additive clip draws with: colour = src * src alpha + dst; the target's alpha stays as it was.
pub const ADDITIVE_BLEND: BlendState = BlendState {
    color: BlendComponent {
        src_factor: BlendFactor::SrcAlpha,
        dst_factor: BlendFactor::One,
        operation: BlendOperation::Add,
    },
    alpha: BlendComponent {
        src_factor: BlendFactor::Zero,
        dst_factor: BlendFactor::One,
        operation: BlendOperation::Add,
    },
};

/// The extension that turns ColorMaterial additive. No bindings of its own: it changes the pipeline only.
#[derive(AsBindGroup, TypePath, Debug, Clone, Default)]
pub struct AdditiveBlend {}

impl MaterialExtension2d for AdditiveBlend {
    fn alpha_mode(&self) -> Option<AlphaMode2d> {
        Some(AlphaMode2d::Blend) // drawn in the transparent pass, sorted by z like sprites
    }

    fn specialize(
        _pipeline: &Material2dPipeline,
        descriptor: &mut RenderPipelineDescriptor,
        _layout: &MeshVertexBufferLayoutRef,
        _key: Material2dKey<Self>,
    ) -> Result<(), SpecializedMeshPipelineError> {
        make_additive(descriptor);
        Ok(())
    }
}

/// The material of an additive Dotwork clip: Bevy's ColorMaterial (texture, tint, uv transform) drawn additively.
pub type DotworkAdditiveMaterial = ExtendedMaterial2d<ColorMaterial, AdditiveBlend>;

/// Sets every colour target of a pipeline to ADDITIVE_BLEND.
pub fn make_additive(descriptor: &mut RenderPipelineDescriptor) {
    if let Some(fragment) = descriptor.fragment.as_mut() {
        for target in fragment.targets.iter_mut().flatten() {
            target.blend = Some(ADDITIVE_BLEND);
        }
    }
}

/// The uv transform that shows `rect` of a `sheet`-sized image on a quad whose uvs run 0..1 (top-left first).
pub fn frame_uv(rect: URect, sheet: UVec2) -> Affine2 {
    let sheet = sheet.as_vec2().max(Vec2::ONE);
    Affine2::from_scale_angle_translation(rect.size().as_vec2() / sheet, 0.0, rect.min.as_vec2() / sheet)
}

/// Where a frame-sized quad's centre goes so that the pivot (a centre-relative, y-up anchor) sits on the origin.
pub fn pivot_offset(anchor: Vec2, size: UVec2) -> Vec2 {
    -anchor * size.as_vec2()
}

/// The frame rects of an additive clip's sheet (empty for loose frames) and the sheet's size.
#[derive(Component, Debug, Clone, Default)]
pub struct DotworkAdditive {
    pub rects: Vec<URect>,
    pub sheet: UVec2,
}

/// Advances additive clips (they have no Sprite, so `animate` does not see them) and shows the frame.
pub(super) fn animate_additive(
    time: Res<Time>,
    mut materials: ResMut<Assets<DotworkAdditiveMaterial>>,
    mut clips: Query<(
        &mut DotworkAnimation,
        &MeshMaterial2d<DotworkAdditiveMaterial>,
        &DotworkAdditive,
    )>,
) {
    for (mut anim, material, additive) in &mut clips {
        if !anim.player.advance(time.delta()) {
            continue;
        }
        let Some(mut m) = materials.get_mut(&material.0) else {
            continue;
        };
        match anim.frames.get(anim.player.frame()) {
            Some(FrameImage::Atlas(i)) => {
                if let Some(rect) = additive.rects.get(*i) {
                    m.base.uv_transform = frame_uv(*rect, additive.sheet);
                }
            }
            Some(FrameImage::Image(image)) => m.base.texture = Some(image.clone()),
            None => {}
        }
    }
}

// {{FOOTER}}
