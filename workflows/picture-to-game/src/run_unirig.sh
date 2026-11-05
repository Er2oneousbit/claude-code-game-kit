#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_unirig.sh
# Purpose : Rig one .glb with UniRig (skeleton, skin weights, merge back onto the original mesh) by calling the four
#           Python steps UniRig's own bash launchers chain, so it also runs on Windows (Git Bash). Logs each step's
#           time and the GPU's peak VRAM. A showcase recipe for #199, not a kit tool yet.
# Usage   : UNIRIG_DIR=<UniRig checkout with its .venv> bash run_unirig.sh <input.glb> <name>
#           -> $UNIRIG_DIR/results/<name>/rigged.glb (plus skeleton.fbx, skin.fbx, run.log, vram_peak.txt)
# Notes   : Setup and the two local changes UniRig needed on a Blackwell GPU are in ../README.md ("Rigging").
#           The input should already be a Bozzetto model (decimated, metres, pivot at the bottom). Exit 0 ok,
#           1 a step failed (the last lines of run.log are shown), 2 usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
set -u
[ $# -eq 2 ] && [ -n "${UNIRIG_DIR:-}" ] || { echo "usage: UNIRIG_DIR=<dir> bash run_unirig.sh <input.glb> <name>"; exit 2; }
IN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; NAME="$2"
cd "$UNIRIG_DIR" || exit 2
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
SUF="obj,fbx,FBX,dae,glb,gltf,vrm"
OUT=results/$NAME; mkdir -p "$OUT" tmp
LOG="$OUT/run.log"; : > "$LOG"
export PYTHONIOENCODING=utf-8

# VRAM sampler: the highest whole-GPU use seen while the run lasts
( peak=0; while :; do u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' \r')
  [ "$u" -gt "$peak" ] 2>/dev/null && peak=$u && echo "$peak" > "$OUT/vram_peak.txt"; sleep 1; done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

step() {  # step <label> <command...>
  local label="$1"; shift
  local t0; t0=$(date +%s)
  echo "### $label: $*" >> "$LOG"
  "$@" >> "$LOG" 2>&1; local rc=$?
  echo "[$label] exit $rc in $(( $(date +%s) - t0 )) s" | tee -a "$LOG"
  [ $rc -eq 0 ] || { echo "FAILED at $label (see $LOG)"; tail -25 "$LOG"; exit 1; }
}

T=$(date +%Y_%m_%d_%H_%M_%S)
step extract-mesh  $PY -m src.data.extract --config=configs/data/quick_inference.yaml --require_suffix=$SUF \
  --force_override=true --num_runs=1 --id=0 --time=$T --faces_target_count=50000 --input="$IN" --output_dir=tmp
step skeleton      $PY run.py --task=configs/task/quick_inference_skeleton_articulationxl_ar_256.yaml --seed=12345 \
  --input="$IN" --output="$OUT/skeleton.fbx" --npz_dir=tmp
step extract-skel  $PY -m src.data.extract --config=configs/data/quick_inference.yaml --require_suffix=$SUF \
  --force_override=true --num_runs=1 --id=0 --time=$T --faces_target_count=50000 --input="$OUT/skeleton.fbx" --output_dir=tmp
step skin          $PY run.py --task=configs/task/quick_inference_unirig_skin.yaml --seed=12345 \
  --input="$OUT/skeleton.fbx" --output="$OUT/skin.fbx" --npz_dir=tmp --data_name=raw_data.npz
step merge         $PY -m src.inference.merge --require_suffix=$SUF --num_runs=1 --id=0 \
  --source="$OUT/skin.fbx" --target="$IN" --output="$OUT/rigged.glb"
echo "VRAM peak (whole GPU, MiB): $(cat "$OUT/vram_peak.txt" 2>/dev/null)"
