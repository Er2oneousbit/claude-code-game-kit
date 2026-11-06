# ---------------------------------------------------------------------------
# shader_check.gd
# Purpose : Renders every kit shader recipe (shaders/kit/<name>.gdshader) on its test inputs into a 64x64 image
#           (build/shader_check/<name>.png), so tools/shaders/shader_ref.py can compare it with the golden image.
# Usage   : python tools/dev.py check              (compiles them: a shader error fails check)
#           python tools/dev.py smoke --shaders    (renders and compares)
#           Direct: godot --path . -s res://tools/shader_check.gd -- <output folder>
# Notes   : Needs a renderer, so it runs in a small window (headless Godot has none). Sprite and surface recipes
#           draw their main input on a TextureRect filling a SubViewport, nearest filtering, with the recipe's
#           material; post recipes draw the scene, then a ColorRect whose material reads the screen. The second
#           input goes in the kit_aux uniform. Prints SHADER_OK <name> per image and SHADER_CHECK_DONE at the end.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends SceneTree

const RECIPES := "res://tools/shaders/recipes.json"
const SHADER_DIR := "res://shaders/kit"
const SETTLE_FRAMES := 3                # frames to draw before reading a viewport back


func _init() -> void:
	_run.call_deferred()


func _texture(rel: String) -> ImageTexture:
	var img := Image.load_from_file(ProjectSettings.globalize_path("res://" + rel))
	if img == null or img.is_empty():
		push_error("shader_check: cannot read %s" % rel)
		return null
	return ImageTexture.create_from_image(img)


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var out_dir: String = args[0] if args.size() > 0 else ProjectSettings.globalize_path("res://build/shader_check")
	DirAccess.make_dir_recursive_absolute(out_dir)
	var text := FileAccess.get_file_as_string(RECIPES)
	var data: Variant = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		push_error("shader_check: cannot read %s" % RECIPES)
		quit(2)
		return
	var size := Vector2i(int(data["canvas"][0]), int(data["canvas"][1]))
	var failed := 0
	for name: String in data["recipes"]:
		var recipe: Dictionary = data["recipes"][name]
		var shader: Shader = load("%s/%s.gdshader" % [SHADER_DIR, name])
		if shader == null:
			push_error("shader_check: no %s/%s.gdshader (python tools/shaders/shader_gen.py writes it)" % [SHADER_DIR, name])
			failed += 1
			continue
		var inputs: Array = recipe["inputs"]
		var main_tex := _texture(data["inputs"][inputs[0]])
		var material := ShaderMaterial.new()
		material.shader = shader
		if inputs.size() > 1:
			material.set_shader_parameter("kit_aux", _texture(data["inputs"][inputs[1]]))
		var vp := SubViewport.new()
		vp.size = size
		vp.transparent_bg = true
		vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		vp.canvas_item_default_texture_filter = Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST
		root.add_child(vp)
		var picture := TextureRect.new()
		picture.texture = main_tex
		picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		picture.stretch_mode = TextureRect.STRETCH_SCALE
		picture.size = Vector2(size)
		picture.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		vp.add_child(picture)
		if recipe["group"] == "post":
			var over := ColorRect.new()
			over.size = Vector2(size)
			over.material = material
			vp.add_child(over)
		else:
			picture.material = material
		for i in SETTLE_FRAMES:
			await process_frame
		await RenderingServer.frame_post_draw
		var img := vp.get_texture().get_image()
		img.convert(Image.FORMAT_RGBA8)
		var err := img.save_png(out_dir.path_join(name + ".png"))
		if err != OK:
			push_error("shader_check: cannot write %s.png (%s)" % [name, error_string(err)])
			failed += 1
		else:
			print("SHADER_OK %s" % name)
		vp.queue_free()
	print("SHADER_CHECK_DONE failed=%d" % failed)
	quit(1 if failed else 0)
