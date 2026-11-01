# ---------------------------------------------------------------------------
# color_filter.gd
# Purpose : The colour-blind option: a full-screen filter that shifts the colours a protanope, deuteranope or
#           tritanope cannot tell apart into ones they can (daltonization), over the game and the menus.
# Usage   : Shell owns one: Shell settings access.colorblind = "none" | "protanopia" | "deuteranopia" | "tritanopia"
# Notes   : It helps; it does not replace good design. Never carry meaning by colour alone: add shapes, icons or
#           text. The matrices are the widely used LMS daltonization ones (Fidaner, Lin, Ozguven); the filter runs
#           on the 640x360 base image. Mouse clicks pass through it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name ColorFilter
extends CanvasLayer

const LAYER: int = 120 # above the menus (10) and HUDs
const MODES: Dictionary = {"none": 0, "protanopia": 1, "deuteranopia": 2, "tritanopia": 3}
const SHADER_CODE: String = """shader_type canvas_item;

uniform sampler2D screen_tex : hint_screen_texture, filter_nearest;
uniform int mode = 0;

const mat3 RGB_TO_LMS = mat3(vec3(17.8824, 3.45565, 0.0299566), vec3(43.5161, 27.1554, 0.184309),
		vec3(4.11935, 3.86714, 1.46709));
const mat3 LMS_TO_RGB = mat3(vec3(0.0809444479, -0.0102485335, -0.000365296938),
		vec3(-0.130504409, 0.0540193266, -0.00412161469), vec3(0.116721066, -0.113614708, 0.693511405));

void fragment() {
	vec3 c = texture(screen_tex, SCREEN_UV).rgb;
	vec3 lms = RGB_TO_LMS * c;
	vec3 sim = lms;
	if (mode == 1) { sim.x = 2.02344 * lms.y - 2.52581 * lms.z; }
	else if (mode == 2) { sim.y = 0.494207 * lms.x + 1.24827 * lms.z; }
	else if (mode == 3) { sim.z = -0.395913 * lms.x + 0.801109 * lms.y; }
	vec3 err = c - LMS_TO_RGB * sim;
	vec3 shift = vec3(0.0, 0.7 * err.r + err.g, 0.7 * err.r + err.b);
	COLOR = vec4(clamp(c + shift, 0.0, 1.0), 1.0);
}
"""

var _rect: ColorRect
var _material: ShaderMaterial


func _init() -> void:
	layer = LAYER
	name = "ColorFilter"
	var shader: Shader = Shader.new()
	shader.code = SHADER_CODE
	_material = ShaderMaterial.new()
	_material.shader = shader
	_rect = ColorRect.new()
	_rect.material = _material
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_rect)
	visible = false


func set_mode(mode_name: String) -> void:
	var mode: int = int(MODES.get(mode_name, 0))
	_material.set_shader_parameter("mode", mode)
	visible = mode != 0

# {{FOOTER}}
