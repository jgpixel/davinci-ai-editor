# DaVinci Editor

The project lives directly in `davinci-ai-editor`; run the commands from this folder.

An agent-operated rough-cut workflow for **DaVinci Resolve Studio**. Select a
timeline, tell your agent what to change, and receive a uniquely named edited
timeline in the same project. Normal use needs no manual timeline export/import.
The agent chooses the cuts; Python tools inspect, transcribe locally, apply
explicit choices, and read back the result.

Built in this separate folder. The Final Cut reference project was left untouched.
No commits, pushes or publication were made.

## Setup on the Studio machine

1. Copy this folder's tools/docs to that machine. Exclude `.venv`, `.cache`, and
   `jobs` unless deliberately transferring analysis; create a new environment.
2. Install 64-bit Python 3.11 with the same architecture as Resolve. In this folder:

   ```sh
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python resolve_editor.py doctor
   ```

   On Windows use `py -3.11 -m venv .venv` and `.venv\Scripts\python.exe`.
   `doctor` only reads installed scripting files. Default paths support macOS,
   Windows and Linux; custom installations can set `RESOLVE_SCRIPT_API` and
   `RESOLVE_SCRIPT_LIB` using the installed scripting README.
3. Start **Studio**. Set **Preferences → System → General → External Scripting
   Using → Local**, save, and restart if Resolve asks. Open a project and select
   its ordinary source-footage timeline.
4. Run the small acceptance check in [STUDIO_TEST_PLAN.md](STUDIO_TEST_PLAN.md).
   Calibration creates a separate probe timeline, verifies API timing conventions,
   and restores the original selection. Repeat it after changing Resolve versions,
   scripting documentation, project or timeline frame rate. It requires a source
   with at least 60 frames; use linked embedded audio when the intended edit has audio.

## Normal use

Open this folder with your agent and have it follow [AGENTS.md](AGENTS.md). Select
the original timeline in Studio and describe the edit. For example:

> Remove dead space and repeated takes. Keep the last complete take of each line.

> Put the conclusion first, then the demonstration. Keep the pauses as they are.

> Make one version from clip A and another from clip B. Keep them isolated and
> put the two versions back to back.

The agent inspects the selected timeline, analyzes only the media needed, writes
ordered decisions in a new job folder, and runs `plan` then `apply`. Studio stays
open. On success the new timeline is selected and its exact name and duration are
reported. The original timeline, source files and older jobs remain available.
Review and finish the rough cut yourself in Studio.

Local speech analysis defaults to `large-v3-turbo` with word timestamps. The first
model download needs `--allow-model-download`; footage is never uploaded.
An existing local model directory can be supplied with `--model /path/to/model`.
Unchanged source analysis is reused from `.cache/analysis`; `.cache/models` is
shared across jobs. A separate transcription setup/download is unnecessary for
edits that already specify exact times.

## Scope and verification

The first implementation handles one video track, optional linked embedded
mono/stereo audio, trims, repeated source occurrences, reordering, separate
versions, and gaps. Source and timeline frame rates must match. Nonzero source
and timeline timecodes are mapped independently.

This is a **source-media rebuild**, so it does not preserve clip-level finishing.
Effects, grades, Fusion, multicam/compound clips, transitions, retiming, independent
audio, extra tracks, custom channel maps and subtitles need a different editing
path. Inspection detects many of these and refuses them. Some processing is not
fully exposed by the API/OTIO export; a human must check that the input is plain
footage before confirming the decision file. Never bypass a detected limitation.
Timeline/project settings and the supported A/V relationships are checked after
construction. A trailing empty gap requires the manual OTIO fallback.

**Resolve was not launched or tested on the development machine.** Offline timing,
simulated API tests, real local transcription/cache reuse and OpenTimelineIO
parsing were tested. Studio connection, actual API output and playback remain for
the other machine. See [TESTING.md](TESTING.md) for the exact evidence and
[STUDIO_TEST_PLAN.md](STUDIO_TEST_PLAN.md) for that acceptance procedure.
