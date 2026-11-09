"""Fix XaeroSeed's block-state NBT ID field for newer Xaero map saves.

Upstream's src/xaero_format.py expects the old 'Name' tag, but newer Xaero
region.xaero files store the block-state identifier in 'id'. Supports both.
GPL-3.0; patch to be applied against original XaeroSeed source code.
"""
from pathlib import Path
import argparse


def patch(file: Path):
    if not file.is_file():
        raise SystemExit(f"Parser not found: {file}")
    original = file.read_text(encoding="utf-8")
    old = 'nbt.get("Name")'
    new = '(nbt.get("Name") or nbt.get("id"))'
    n = original.count(old)
    if n == 2:
        updated = original.replace(old, new)
        file.write_text(updated, encoding="utf-8")
        print(f"PATCHED: {file}; corrected both block name lookups")
    elif original.count(new) == 2 and n == 0:
        print(f"Already patched: {file}")
    else:
        raise SystemExit(
            f"Unexpected XaeroSeed parser version ({n} old lookups). "
            "No changes made; please check upstream changes."
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file", nargs="?", default="engine/src/xaero_format.py", type=Path)
    args = p.parse_args()
    patch(args.file)
