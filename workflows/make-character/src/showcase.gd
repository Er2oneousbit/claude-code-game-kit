# ---------------------------------------------------------------------------
# showcase.gd
# Purpose : The make-character showcase scene: the made-up map-maker (Bozzetto reference, make, rig make, rig chain)
#           walks across a small yard through KitCharacter, stops, waves and idles, scarf swinging. Built in code so
#           the scene file stays one line and the whole set-up reads top to bottom.
# Usage   : attach to the root Node3D of scenes/showcase.tscn; make that the main scene; then
#           python tools/dev.py smoke --frames 420 --record captures/frames   (and tools/art/frames_to_gif.py)
# Notes   : The character is Bozzetto output (glTF, metres, +Y up, front +Z, pivot at the feet) with clips idle, walk
#           and wave from rig_finish.py and the scarf's sway keyed by rig_chain.py. KitCharacter loops the clips
#           (glTF clips import without looping) and crossfades between them. Facing: look_at(target, UP, true) turns
#           the model's +Z front toward the target. Timings are seconds of game time.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
extends Node3D

const HERO := "res://assets/models/npc_mapmaker_rigged.glb"   # bozzetto.py rig make + rig chain npc_mapmaker
const WALK_SPEED := 0.9       # m/s, matched by eye to the walk clip's stride
const WALK_FROM := Vector3(-2.6, 0, -0.6)
const WALK_TO := Vector3(0.4, 0, 0.3)
const WAVE_TIME := 2.2        # seconds of waving after arriving, then idle

var hero: Node3D
var phase := "walk"
var phase_t := 0.0


func _ready() -> void:
	_build_world()
	hero = KitCharacter.load_scene(HERO)
	hero.position = WALK_FROM
	add_child(hero)
	hero.look_at(WALK_TO, Vector3.UP, true)   # true: the model's +Z front faces the target
	KitCharacter.play(hero, "walk")
	Log.info("core", "BOOT_OK showcase")   # dev.py smoke waits for this marker (as scripts/game/main.gd prints it)


func _process(delta: float) -> void:
	phase_t += delta
	match phase:
		"walk":
			hero.position = hero.position.move_toward(WALK_TO, WALK_SPEED * delta)
			if hero.position.distance_to(WALK_TO) < 0.01:
				hero.rotation = Vector3.ZERO      # face the camera side again
				_go("wave")
		"wave":
			if phase_t > WAVE_TIME:
				_go("idle")


func _go(next: String) -> void:
	phase = next
	phase_t = 0.0
	KitCharacter.play(hero, next)


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
	sun.rotation_degrees = Vector3(-45, -30, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(20, 20)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.55, 0.5, 0.4)
	plane.material = mat
	ground.mesh = plane
	add_child(ground)
	var cam := Camera3D.new()
	cam.position = Vector3(1.2, 1.5, 3.6)
	cam.fov = 45.0
	add_child(cam)
	cam.look_at(Vector3(-0.6, 0.9, 0.0))
