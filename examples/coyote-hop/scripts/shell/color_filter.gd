# ---------------------------------------------------------------------------
# color_filter.gd
# Purpose : The colour-blind option: a full-screen filter that shifts the colours a protanope, deuteranope or
#           tritanope cannot tell apart into ones they can (daltonization), over the game and the menus.
# Usage   : Shell owns one: Shell settings access.colorblind = "none" | "protanopia" | "deuteranopia" | "tritanopia"
# Notes   : It helps; it does not replace good design. Never carry meaning by colour alone: add shapes, icons or
#           text. The matrices are the widely used LMS daltonization ones (Fidaner, Lin, Ozguven); the filter runs
#           on the 640x360 base image. Mouse clicks pass through it.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-06: the shader is the kit's colorblind recipe (shaders/kit/colorblind.gdshader), same maths
# ---------------------------------------------------------------------------
class_name ColorFilter
extends CanvasLayer

const LAYER: int = 120 # above the menus (10) and HUDs
const MODES: Dictionary = {"none": 0, "protanopia": 1, "deuteranopia": 2, "tritanopia": 3}
# The kit's colorblind recipe (tools/shaders/ksl/colorblind.ksl, checked against its golden image by dev.py check and
# smoke --shaders): the same daltonization this filter always ran, now one shader for the game and the kit
const SHADER_PATH: String = "res://shaders/kit/colorblind.gdshader"

var _rect: ColorRect
var _material: ShaderMaterial


func _init() -> void:
	layer = LAYER
	name = "ColorFilter"
	_material = ShaderMaterial.new()
	_material.shader = load(SHADER_PATH)
	_rect = ColorRect.new()
	_rect.material = _material
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_rect)
	visible = false


func set_mode(mode_name: String) -> void:
	var mode: int = int(MODES.get(mode_name, 0))
	_material.set_shader_parameter("u_mode", float(mode))
	visible = mode != 0
