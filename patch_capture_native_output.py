#!/usr/bin/env python3
"""Patch upstream XaeroSeed's native subprocess execution for Windows GUI builds.

Windows windowed/GUI launches can leave inherited native stdout/stderr unbound.
Capture output explicitly, relay it, and fail if native claims success without a seed.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('engine/xaeroseed.py')
s = p.read_text(encoding='utf-8')
old = '''        status = subprocess.call([
            CRACKER, "--constraints", path, "--biomes", biome_file,
            "--threads", str(args.threads), "--accept", str(args.accept)])'''
new = '''        # Capture the native EXE's output explicitly. Windowed PyInstaller apps
        # may have no valid inherited console handles, hiding an actual result.
        completed = subprocess.run(
            [CRACKER, "--constraints", path, "--biomes", biome_file,
             "--threads", str(args.threads), "--accept", str(args.accept)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace")
        if completed.stdout:
            say(completed.stdout.rstrip())
        else:
            say(f"  ERROR: Native engine produced no output (exit code {completed.returncode}).")
        status = completed.returncode
        if status == 0 and not re.search(r"(?m)^\\s*seed\\s+-?\\d+\\s*$", completed.stdout or ""):
            say("  ERROR: Native engine returned success, but no world seed was printed.")
            status = 7'''
if old not in s:
    raise SystemExit('Patch NOT applied: upstream subprocess block has changed; inspect xaeroseed.py')
if 'import re\n' not in s:
    s = s.replace('import random\n', 'import random\nimport re\n', 1)
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('Patched native output handling in', p)
