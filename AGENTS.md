# Operating DaVinci Editor

## Intent and preservation

Follow the user's actual requested edits. Do not assume every job needs pause
removal, repeated-take removal, reordering, transcription or separate versions.
Preserve unique content and enforce source restrictions. Editorial decisions
belong to the agent; tools never claim to choose the best take automatically.
Transcripts alone cannot establish visual quality. Analyze relevant visuals only
when that is necessary for the request.

Default delivery is a base edit for the user to finish. Make one editorial pass,
then inexpensive technical validation. Do not routinely render previews, take
screenshots, create contact sheets, examine every cut, or retranscribe renders.
Additional analysis needs a concrete issue blocking the requested edit.

Never overwrite/delete source media, the original timeline, earlier revisions or
jobs. Never touch Resolve databases directly. `apply` duplicates the selected
original and clears clips **only on that new copy** before rebuilding. It retains
failed outputs for diagnosis and restores the original selection on failure.
Calibration likewise retains its separate probe. Do not delete these automatically.
Do not commit, push or publish this project without user authorization.

## Environment and commands

Run from this folder with `.venv/bin/python`; Windows uses
`.venv\Scripts\python.exe`. See `README.md` for setup. Tools themselves need only
the standard library; speech analysis needs `requirements.txt`. Offline tests use
`python -m unittest discover -s tests -v`. Optional `opentimelineio==0.18.1` lets
the tests independently check exported OTIO with its official reader.

The implementation targets the bundled Resolve 20.2 scripting documentation.
`doctor` validates required documented capabilities without loading the native
library. Live commands require Studio already running with External Scripting
Using set to Local; never launch it as an incidental step. On a new machine read
its own installed `Developer/Scripting/README.txt` before making API changes.
`RESOLVE_SCRIPT_API` and `RESOLVE_SCRIPT_LIB` override default platform locations.

Commands:

```sh
.venv/bin/python resolve_editor.py doctor
.venv/bin/python resolve_editor.py inspect --job jobs/<job>/inspect-01
.venv/bin/python resolve_editor.py calibrate --job jobs/<project>/calibration-01
.venv/bin/python analyze_recording.py --source "/path/to/media.mov"
.venv/bin/python resolve_editor.py map --snapshot jobs/<job>/inspect-01/snapshot.json \
  --clip-id "<occurrence-id>" --file-start 10 --file-end 12
.venv/bin/python resolve_editor.py plan --snapshot jobs/<job>/inspect-01/snapshot.json \
  --decisions jobs/<job>/decisions-01.json --output jobs/<job>/plan-01.json
.venv/bin/python resolve_editor.py apply --snapshot jobs/<job>/inspect-01/snapshot.json \
  --decisions jobs/<job>/decisions-01.json --contract jobs/<project>/calibration-01/contract.json \
  --job jobs/<job>/revision-01
.venv/bin/python resolve_editor.py verify --snapshot jobs/<job>/inspect-01/snapshot.json \
  --result jobs/<job>/revision-01/result.json --contract jobs/<project>/calibration-01/contract.json
```

`inspect` automatically exports OTIO to the job for structural checks and compares
its clip coordinates/source bounds with API reads. No manual export is needed.
Inspection is read-only in Resolve; export and snapshot files are local artifacts.
It reports the selected project/timeline, original timecode, settings, track
layout, source paths, source frame rates/counts/in points and occurrence IDs.

Before applying, the original must still be selected. Live inspection is repeated
and its fingerprint must equal the saved snapshot. Selecting a different timeline,
changing clip timing/settings or altering source file identity invalidates the
decisions. Reinspect and update decisions rather than bypassing the mismatch.
During apply/calibration, do not concurrently operate Resolve or run another writer.
Project/selection checks run before append operations but cannot make UI actions atomic.

## Calibrate before relying on API conventions

Run `calibrate` on a supported timeline with at least 60 frames of media. Use linked
embedded audio if the job needs audio. It duplicates the original into a uniquely
named probe, clears that copy, and requests source frames 11 through 34 at timeline
start + 7. Readback must show 24 frames, file-relative source start 11, absolute
record placement, exclusive item timeline ends and matching audio/video durations.
The source-end and timeline-end biases are measured, not assumed. Linking is
also read back. No passed contract is issued if those checks fail.

The certificate is bound to the Studio product/version, local documentation hash,
project ID and exact timeline FPS. Recalibrate when any changes. It verifies one
same-rate ordinary-source case; it does not certify mixed-rate media, every codec,
or complex timelines. Every real edit still gets full API readback validation.
If calibration fails, preserve the probe and explain the observed mismatch.
Never substitute assumed convention values or a mocked certificate.

## Supported input and incomplete API visibility

Supported: exactly V1, optionally A1, ordinary online footage, normal speed,
matching source/timeline FPS, no overlapping clips, optional explicit gaps,
and either video-only occurrences or linked embedded mono/stereo audio at exactly
the same source in/out and timeline start/end. Audio source/clip mapping must match
and use the embedded channels in order, with no linked external audio. Empty extra
tracks, locked/disabled tracks, independently edited audio and subtitle tracks are
rejected too. Repeated occurrences are separate IDs even when they share one file.

Automated checks reject OTIO transitions, effects, nested stacks, missing media,
markers, time warps, bounds mismatches and rate differences. API checks additionally
reject Fusion, take selectors, multiple color nodes, color groups, voice isolation,
disabled clips, non-default inspected transforms and unusual A/V link groups.
API/OTIO discrepancies stop editing.

Neither export nor the API proves absence of every grade, OFX effect, transition
omitted by export, dynamic zoom, keyframe, Fairlight effect or routing change.
An unmodified color node count does **not** prove absence of a grade. Before
`plain_source_rebuild_confirmed: true`, obtain actual human confirmation that the
input is plain source footage with no finishing settings to preserve, or use an
explicitly created known-plain synthetic acceptance fixture. Do not set it just
to make validation pass. The confirmation covers hidden processing, not detected
limitations; it cannot override those checks.

This project cannot preserve a finished timeline's clip settings by rebuilding
source media. Explain the specific limitation. Where authorized, use a separate
plain-source timeline for a rough cut and leave finishing on the original; otherwise
use a different supported editing method. OTIO is not a workaround for silently
discarding complex structures. Mixed-rate media is explicitly unsupported rather
than being treated as if source and project frames were interchangeable.

## Coordinates and speech cache

Decisions use **timeline-relative seconds**, with zero at the original timeline's
start; `01:00:00:00` does not add an hour to decision coordinates. Start/end can be
decimal numbers, decimal strings or exact rational strings like `1001/24000`.
Ends are exclusive. Cuts snap to the nearest timeline frame, ties upward, and the
plan records requested and applied boundaries. Tiny media fragments default to a
minimum of three frames; lower `minimum_clip_frames` only for an intentional edit.

API record positions are absolute timeline frames, calculated as
`GetStartFrame() + output_start_frame`. API append `endFrame` is inclusive under
the calibrated contract, so tools pass exclusive source end minus one.
Normalized `source_start_frame` values are **file-relative frames**, verified
against OTIO's source range minus its available-range origin. Source timecode is
metadata; do not add it to file-relative transcription seconds or API source frames.

For one matching-rate occurrence:

`timeline seconds = occurrence start_frame / FPS + file seconds - source_start_frame / FPS`

The `map` command enforces that the file interval is inside the selected trimmed
occurrence. A transcript passage outside that occurrence cannot be used there.
Map each repeated source occurrence independently. Use exact rational FPS for
23.976/29.97/59.94 rates; decimal labels normalize to their /1001 rates.

Transcription defaults to local `large-v3-turbo`, English, int8 CPU, word timestamps,
Silero VAD, 650ms minimum pause, 400ms boundary padding, 14s speech passages,
up to 22s recognition windows and batch size four. Nearby padded passages share
context only when the gap is at most 1.25s. Real silence stays inside each original
window; distant speech is never spliced together for recognition. This is one
recognition pass, without a cloud service or another alignment model.

Analyze each distinct required file once. Results are file-relative seconds in
`.cache/analysis`, keyed by resolved path, size, mtime/ctime, model and settings,
stream selection and package versions. Unchanged media reuses analysis. Temporary
mono 16k audio is removed after decoding; no entire recording is copied into jobs.
Original recordings stay at their existing paths.

`--detect-silence` adds acoustic intervals without removing them; use it only when
silence matters. `--language auto` enables multilingual detection. `--audio-stream`
selects the zero-based embedded stream. `--allow-model-download` permits downloading
missing weights only, never uploads footage. `--model /local/model/directory` uses
existing weights. `--cache-dir` chooses a shared cache. `--refresh` intentionally
replaces matching analysis. Do not clear caches on new jobs or silently change the
ASR profile. Cache identity is stat-based, not a full media checksum.

## Ordered decisions and versions

Write each decision file to a new job path. Example schema (replace the fingerprint
and occurrence IDs from inspection; this is not an editorial preset):

```json
{
  "schema_version": 1,
  "coordinate_space": "timeline_seconds",
  "snapshot_fingerprint": "<from snapshot.json>",
  "plain_source_rebuild_confirmed": true,
  "ranges": [
    {"start": 10, "end": 15, "reason": "Requested section first"},
    {"start": 0, "end": 5, "reason": "Requested section second"}
  ]
}
```

Ranges are retained and concatenated **in list order**, allowing repeats and
reordering. A range crossing clips is split; any selected original gap is retained.
No incidental gap is inserted between consecutive retained ranges. An optional
`allowed_clip_ids` on a single-version decision enforces a source restriction.

For separate versions replace `ranges` with `versions`. Each version must have a
unique name, explicit `allowed_clip_ids` and ordered `ranges`. The version list is
concatenated back to back; any range touching a disallowed occurrence fails.
Do not combine top-level ranges/restrictions with versions. Version boundaries
are recorded in the plan and result manifest.

The agent compares repeated takes in context, follows the user's last-complete-take
preference if requested, and preserves unique information from earlier takes.
Neither silence detection nor transcript similarity alone is an editorial decision.

## Validation, delivery and fallback

`plan` runs offline structure, fingerprint, frame alignment, source bounds,
duration, fragment and source-restriction checks. It writes the exact applied
manifest without connecting to Resolve. `apply` recomputes it from decisions,
rechecks the live input and the calibration, duplicates the original, and creates
the clips directly with explicit source frames, track indices and record positions.
Project and timeline settings remain inherited from the duplicate.

Before successful delivery it reads actual output media IDs, clip counts,
positions, source in/out, per-clip and total durations, A/V link groups, audio
mapping, track layout/settings and project/timeline settings. It checks the original
snapshot again. Failures are reported in `result.json` with the incomplete output
name; never call that output verified. Successful outputs remain selected in Studio.
`verify` independently reads a selected delivered output again; it does not edit it.
Do not claim playback or live API verification from simulated tests.

An output ending in an empty gap is not representable by direct clip placement.
Use a **manual fallback**, only for otherwise supported plain-source decisions:

```sh
.venv/bin/python resolve_editor.py export-otio --snapshot jobs/<job>/inspect-01/snapshot.json \
  --decisions jobs/<job>/decisions-01.json --output outputs/<job>/revision-01.otio
```

This writes standard OTIO plus `.manifest.json`, with A/V ranges and nonzero source
origins. Import it as a **new** timeline in Studio. Manual OTIO import, linking,
and per-timeline settings must then be checked on that machine; offline validation
does not prove Resolve import. This implementation does not automatically import
the fallback or claim it preserves unsupported processing.

Deliver the exact new timeline name, project, duration, concise edit summary,
manifest/result path and material limitations. Normal successful delivery is the
timeline already inside Studio; do not send an export as if import were still needed.

## Jobs and acceptance testing

Reuse this folder and shared caches across projects. Use `jobs/<job>/inspect-01`,
`decisions-01.json`, `plan-01.json`, and fresh `revision-01`, `revision-02` folders.
Keep calibration jobs separately and retain their contracts/probes. Source files
can live anywhere; no media copying is required. Keep footage/jobs/caches/environments
out of Git. Cleanup happens only when requested for specific jobs; preserve shared
models, source media and previous work by default.

The current machine has no Studio available for this task. **Do not launch or
connect to Resolve here.** `doctor`, offline planning, simulated adapters, local
speech and OTIO parsing are allowed. Actual Studio acceptance belongs on the other
machine. Follow [STUDIO_TEST_PLAN.md](STUDIO_TEST_PLAN.md); it includes a synthetic
fixture, exact expected frames, negative tests and evidence to record. Consult
[TESTING.md](TESTING.md) to distinguish completed checks from unverified behavior.
