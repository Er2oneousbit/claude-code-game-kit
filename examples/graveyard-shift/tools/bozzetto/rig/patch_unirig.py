#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# patch_unirig.py
# Purpose : Apply the four small changes UniRig needs to run with standard wheels only (no flash_attn, no Triton) and
#           to load its skin checkpoint on PyTorch 2.6+, to a UniRig checkout. Idempotent: a second run changes nothing.
# Usage   : python patch_unirig.py <UniRig checkout> [--check] [--debug]
#           --check  only report which changes are in place (exit 1 if any is missing)
# Notes   : The changes (tested on UniRig 6793c66, 2026-11-05):
#           1. src/model/unirig_skin.py: import flash_attn's MHA if it is there, else mha_sdpa.MHA (PyTorch SDPA, same
#              parameter names, so the checkpoint loads unchanged; outputs match to about 1e-8).
#           2. configs/model/unirig_ar_350m_1024_81920_float32.yaml: the skeleton model asks transformers for "sdpa"
#              instead of "flash_attention_2".
#           3. configs/model/unirig_skin.yaml: PTv3 (the skin model's point encoder) uses its own attention
#              (enable_flash: False). Without flash_attn it would refuse to start; with flash_attn on a Blackwell GPU
#              its head_dim-16 kernels returned wrong values (all-NaN skin weights).
#           4. run.py: allowlist python-box's Box for torch.load, which loads weights only since PyTorch 2.6. This keeps
#              weights_only=True instead of the unsafe weights_only=False the error message suggests.
#           Exit 0 ok, 1 --check found a missing change or a file no longer matches (UniRig changed: look by hand),
#           2 usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   for each change: read the file -> already patched? skip : the expected original text there? replace : report
#   copy mha_sdpa.py next to unirig_skin.py
import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = "kit patch (#199)"
CHANGES = [  # (file, original text, patched text)
    ("src/model/unirig_skin.py",
     "from flash_attn.modules.mha import MHA\n",
     "try:\n    from flash_attn.modules.mha import MHA\nexcept ImportError:  # " + MARK + ": PyTorch SDPA stand-in, same weights\n"
     "    from .mha_sdpa import MHA\n"),
    ("configs/model/unirig_ar_350m_1024_81920_float32.yaml",
     "_attn_implementation: flash_attention_2",
     "_attn_implementation: sdpa  # " + MARK + ", was flash_attention_2"),
    ("configs/model/unirig_skin.yaml",
     "  upcast_attention: False\n",
     "  enable_flash: False  # " + MARK + ": flash_attn optional; wrong at head_dim 16 on Blackwell\n"
     "  upcast_attention: False\n"),
    ("run.py",
     "import argparse\n",
     "# " + MARK + ": the skin checkpoint pickles a python-box Box; allowlist only that class so torch.load keeps\n"
     "# weights_only=True (the PyTorch 2.6+ default) instead of the unsafe weights_only=False.\n"
     "import torch as _t, box as _box\n_t.serialization.add_safe_globals([_box.box.Box])\nimport argparse\n"),
]


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Patch a UniRig checkout to run with standard wheels (see the header).")
    ap.add_argument("unirig", help="the UniRig checkout (has run.py and src/)")
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if a change is missing")
    ap.add_argument("--debug", action="store_true", help="show tracebacks")
    a = ap.parse_args()
    root = Path(a.unirig)
    if not (root / "run.py").is_file() or not (root / "src" / "model").is_dir():
        print(f"[error] not a UniRig checkout: {root}")
        return 2
    missing = 0
    try:
        for rel, old, new in CHANGES:
            p = root / rel
            text = p.read_text(encoding="utf-8")
            if MARK in text:
                print(f"[ OK ] {rel}: already patched")
            elif text.count(old) != 1:
                print(f"[FAIL] {rel}: the expected line is not there (UniRig changed?): {old.strip()!r}")
                missing += 1
            elif a.check:
                print(f"[MISS] {rel}: not patched")
                missing += 1
            else:
                # write_bytes: Path.write_text has no newline= before Python 3.10 (the kit supports 3.8)
                p.write_bytes(text.replace(old, new).encode("utf-8"))
                print(f"[ OK ] {rel}: patched")
        dst = root / "src" / "model" / "mha_sdpa.py"
        if dst.is_file() and dst.read_bytes() == (HERE / "mha_sdpa.py").read_bytes():
            print("[ OK ] src/model/mha_sdpa.py: in place")
        elif a.check:
            print("[MISS] src/model/mha_sdpa.py: not copied")
            missing += 1
        else:
            shutil.copyfile(HERE / "mha_sdpa.py", dst)
            print("[ OK ] src/model/mha_sdpa.py: copied")
    except OSError as e:
        if a.debug:
            raise
        print(f"[error] {e}")
        return 2
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
