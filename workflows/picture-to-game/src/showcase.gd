# ---------------------------------------------------------------------------
# showcase.gd
# Purpose : The picture-to-game showcase scene: a grove of one generated tree and one generated, auto-rigged,
#           script-animated character that walks in, stops, waves and idles. Built in code so the scene file stays
#           one line and the whole set-up reads top to bottom.
# Usage   : attach to the root Node3D of scenes/showcase.tscn; make that the main scene; then
#           python tools/dev.py smoke --record captures/frames   (and tools/art/frames_to_gif.py)
# Notes   : Models are Bozzetto output (glTF, metres, +Y up, front +Z, pivot at the bottom). The character's clips
#           (idle, wave, walk) come from bozzetto.py rig (rig_finish.py); glTF clips import without looping, so they are set to loop
#           here. Timings are in seconds of game time.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node3D

const TREE := "res://assets/models/kit_tree.glb"
const HERO := "res://assets/models/npc_beekeeper_rigged.glb"   # bozzetto.py rig make npc_beekeeper
const TREE_SPOTS := [  # x, z, turn (deg), scale
	[-3.2, -2.5, 0.0, 1.0], [3.4, -3.0, 140.0, 1.15], [-5.5, -6.0, 70.0, 0.9],
	[5.8, -7.0, 220.0, 1.25], [0.6, -8.5, 300.0, 1.1], [-1.8, -11.0, 30.0, 1.3],
]
const WALK_SPEED := 1.1       # m/s, matched by eye to the walk clip's stride
const WALK_FROM := Vector3(0, 0, -6.0)
const WALK_TO := Vector3(0, 0, 0.5)
const WAVE_TIME := 2.0        # seconds of waving after arriving

var hero: Node3D
var anim: AnimationPlayer
var phase := "walk"
var phase_t := 0.0


func _ready() -> void:
	_build_world()
	for s in TREE_SPOTS:
		var t: Node3D = load(TREE).instantiate()
		t.position = Vector3(s[0], 0, s[1])
		t.rotation_degrees.y = s[2]
		t.scale = Vector3.ONE * s[3]
		add_child(t)
	hero = load(HERO).instantiate()
	hero.position = WALK_FROM
	add_child(hero)
	_use_vertex_colours(hero)
	anim = hero.find_child("AnimationPlayer", true, false)
	for clip in anim.get_animation_list():
		anim.get_animation(clip).loop_mode = Animation.LOOP_LINEAR
	anim.play("walk")
	Log.info("core", "BOOT_OK showcase")   # dev.py smoke waits for this marker (as scripts/game/main.gd prints it)


func _process(delta: float) -> void:
	phase_t += delta
	match phase:
		"walk":
			hero.position = hero.position.move_toward(WALK_TO, WALK_SPEED * delta)
			if hero.position.distance_to(WALK_TO) < 0.01:
				_go("wave")
		"wave":
			if phase_t > WAVE_TIME:
				_go("idle")


func _go(next: String) -> void:
	phase = next
	phase_t = 0.0
	anim.play(next, 0.25)   # a short blend between clips


func _use_vertex_colours(root: Node) -> void:
	# Bozzetto --material vertex keeps the colours in COLOR_0. glTF multiplies the base colour by it, but Godot
	# 4.7's importer leaves vertex_color_use_as_albedo off, so the model renders white without this.
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		for s in mi.mesh.get_surface_count():
			var mat: Material = mi.get_active_material(s)
			if mat is StandardMaterial3D:
				mat = mat.duplicate()
				mat.vertex_color_use_as_albedo = true
				mi.set_surface_override_material(s, mat)


func _build_world() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	var sky := Sky.new()
	sky.sky_material = ProceduralSkyMaterial.new()
	e.background_mode = Environment.BG_SKY
	e.sky = sky
	e.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 35, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(40, 40)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.42, 0.58, 0.32)
	plane.material = mat
	ground.mesh = plane
	add_child(ground)
	var cam := Camera3D.new()
	cam.position = Vector3(2.6, 1.7, 4.6)
	cam.fov = 50.0
	add_child(cam)
	cam.look_at(Vector3(0, 0.9, -2.0))
