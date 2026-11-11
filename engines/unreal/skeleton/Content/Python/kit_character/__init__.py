# Rigged glTF characters for Unreal (#290): character_spec (plain Python: glTF names, clip matching, angles),
# character (import_character through Interchange; needs the editor) and the check test_character_golden.py.
# See docs/ENGINE.md "Rigged characters". The import is not done here so the plain half loads without `unreal`.


def import_character(*args, **kwargs):
    """kit_character.character.import_character (imported on first use)."""
    from kit_character.character import import_character as run
    return run(*args, **kwargs)
