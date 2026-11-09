# XaeroSeed Windows GUI — native output fix

Your map was successfully decoded: 57 structure locations, 47 usable,
and 24 biome samples. But the Windows GUI reported `exit code 0` without
showing the native cracker's output or a seed. This is **not proof of a seed**.

## Changes
- Explicitly captures stdout and stderr from native `seedcrack.exe`.
- Displays the captured output in the GUI, including any `seed <number>` line.
- Returns an error when the engine reports success without printing a seed.
- Tests the native EXE in GitHub Actions (usage message and return code).
- Keeps the existing Xaero 26.3 NBT `id`/`Name` compatibility fix.

## Build and use
1. Replace the matching source files in your GUI GitHub repository with the
   files in this ZIP (including `.github/workflows/build-windows.yml`).
2. Commit to main.
3. In GitHub Actions run **Build XaeroSeed Windows GUI**.
4. Download the `XaeroSeed_GUI_Windows` artifact.
5. Run `XaeroSeed_GUI.exe` and select the same Xaero map ZIP.

If the seed was previously found but hidden by the Windows subprocess setup,
this build should show it. If no seed matches, it should show the native
cracking diagnostics. An engine that returns 0 without output is flagged as an
error instead of silently being accepted.

**Validation:** Python patches and ZIP structure tested locally. The full
Windows native engine must still be tested on a GitHub Actions build and PC.
