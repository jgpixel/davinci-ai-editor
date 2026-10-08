# Verification record — 2026-10-08

Development environment: macOS 15.6.1, arm64, Python 3.11.5. Resolve app bundle
metadata reports 20.2.0; installed scripting README is dated 18 August 2025.
The application was **not launched**, its native scripting module was **not
imported**, and no Resolve project/timeline or database was accessed.

Reference workflow: `jgpixel/final-cut-editor` main commit
`7e0f164471b65a31d85674c6f37904e96f8da028`, matching the GitHub main tree at review.
Read its main AGENTS and Python tools, and its local companion README (untracked
on that checkout; GitHub main had no README). Adapted bounded-window transcription;
did not copy its XML-specific timeline editing or subtitles. Original repository
and recordings were left untouched.

## Passed locally

- **34 tests passed, no skips** in the installed environment: timing arithmetic, repeated/trimmed
  source mapping, reordering, nonzero source/timeline origins, explicit gaps,
  version isolation/restrictions, tiny fragments, frame snapping, source bounds,
  stale decisions and output overwrite prevention.
- Fake API integration: inspection/export coordinate agreement, probe calibration,
  direct construction, source in/out/placement/duration readback, embedded audio
  links/mapping, retained original/settings, refused structures, stale certificates,
  failed append recovery and protection against a duplicate returning the original.
- Generated OTIO parsed by **OpenTimelineIO 0.18.1**, including source timecode
  origins and gaps. This proves OTIO interoperability, not Resolve import.
- Real **large-v3-turbo** inference using existing local weights read from the
  reference project's model directory. Synthetic speech repeated around five
  seconds of real silence: 15.28325-second audio, two bounded recognition windows,
  30 timestamped words, detected silence, and timestamps clamped to each original
  window. No model or footage upload/download was needed for this check.
- Repeating identical analysis returned `cached: true`; analysis matched exactly
  and cache lookup took about 1ms, without running recognition again.
- Static `doctor`: installed module/library/docs exist and all required API names
  are documented. CLI help/argument handling, byte compilation and dependency
  consistency checks passed. A standalone environment was installed in `.venv`.
- Synthetic Studio acceptance fixture media generated locally: two 12-second
  25fps stereo MOVs with source timecode tags; these are test assets, not user footage.

Run the suite with `.venv/bin/python -m unittest discover -s tests -v`.
Speech smoke artifacts are in `jobs/offline-transcription`; Studio fixture media
are in `inputs/studio-test`. These and caches are excluded from version control.

## Not verified on this machine

Studio external scripting permission/connection; native API conventions;
actual append/link behavior; duplicate settings inheritance; API/OTIO agreement
on real Resolve timelines; embedded source-timecode interpretation in Resolve;
successful live output readback; actual audio/video playback; OTIO fallback import;
Windows/Linux runtime behavior; Studio fractional/drop-frame operation.

These require [STUDIO_TEST_PLAN.md](STUDIO_TEST_PLAN.md) on the other machine.
Passing automated offline tests does not certify those operations. The tool itself
requires a passing live calibration contract before a direct edit.

## Project relocation — 2026-10-08

Moved the project contents from the nested `davinci-editor` folder directly into
`davinci-ai-editor`, preserving inputs, jobs and shared caches. Recreated `.venv`
with the same installed dependency versions. Earlier transcription smoke records
retain the absolute paths used when those checks ran; create new jobs at the new
root. This relocation does not require a Resolve connection.
All 34 tests passed again at the new root; dependency and static path checks passed.
