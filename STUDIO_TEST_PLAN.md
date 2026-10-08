# Acceptance test on the machine with Resolve Studio

This is the remaining live acceptance check. Development-machine tests did not
connect to or launch Resolve. Use a disposable local test project and synthetic
media so real editing work is not involved. Keep the generated output and evidence.
No renders/screenshots are necessary; one short playback of the test cut is enough.

## 1. Install and check the connection

Transfer this folder's tools/docs; recreate `.venv` on that machine. Install from
`requirements.txt`; optionally install `opentimelineio==0.18.1` for the independent
offline interoperability test. Run:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python resolve_editor.py doctor
```

On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe` throughout.
Use Studio with compatible 64-bit Python/architecture. Read that installation's
`Developer/Scripting/README.txt`; set path overrides if `doctor` cannot find it.
Record Studio version, OS, Python version, architecture and the doctor's
documentation hash. Enable **Preferences → System → General → External Scripting
Using → Local**, save/restart as requested, then open the disposable project.
Do not enable network scripting for this workflow.

## 2. Create the representative input

Generate small 12-second, 25fps, stereo test-pattern MOVs, with embedded source
timecodes A = `02:00:00:00` and B = `03:00:00:00`:

```sh
.venv/bin/python tests/make_studio_fixture.py media --output-dir inputs/studio-test
```

Alternatively transfer the already generated `inputs/studio-test/A.mov` and
`B.mov`. Do not overwrite existing fixture files when generating another set.

Import A and B into the disposable Studio project. Make a new **25fps** timeline,
start timecode **01:00:00:00**, exactly **V1 and stereo A1**. Construct these linked
video/audio occurrences using original-speed footage and unchanged channel mapping:

| Occurrence | Source file interval (exclusive end) | Relative timeline interval | Absolute timeline start |
| --- | --- | --- | --- |
| A first | A frames 50–150 (2–6 seconds) | frames 0–100 (0–4 seconds) | 01:00:00:00 |
| Gap | 25 empty frames on V1/A1 | frames 100–125 (4–5 seconds) | 01:00:04:00 |
| A repeated | A frames 150–250 (6–10 seconds) | frames 125–225 (5–9 seconds) | 01:00:05:00 |
| B | B frames 25–125 (1–5 seconds) | frames 225–325 (9–13 seconds) | 01:00:09:00 |

When choosing in/out in Resolve's viewer, its out mark may be inclusive: 50–149
selects 100 frames, for example. Set positions/durations exactly rather than
dragging approximately. Embedded A's displayed source timecodes should reflect
the two-hour origin, and B's the three-hour origin. Timeline duration is 325 frames.
No grades, transforms, effects, transitions, titles, markers, Fusion, dynamic zoom,
retiming, keyframes or Fairlight processing; keep A/V linked. Only this known-plain
fixture is eligible for the confirmation flag below.

## 3. Inspect and calibrate

Select that original timeline, then run:

```sh
.venv/bin/python resolve_editor.py calibrate --job jobs/studio-acceptance/calibration-01
```

The command first reads the current project/timeline and automatically exports
OTIO for safety inspection. It then creates a separate API probe. Expected:

- Snapshot shows 25fps, 325 frames, three video occurrences and matching embedded
  audio, no limitations, file source starts 50, 150, 25, and source timecode metadata.
- Probe contains one video and one audio clip at original start + 7 frames, from
  file-relative source frames 11–35 exclusive, duration **24 frames**.
- Source numbering, inclusive API append end, absolute record placement,
  source/timeline end biases, audio duration and links all pass live readback.
- `contract.json` says `status: passed` and `tested_audio: true`.
- Original timeline is selected again and still has its original three clips/gap.

The separately named probe remains available. If any check fails, stop, retain
the failed job/probe, and use its exact error to update the adapter for that API.
Do not manually invent a passing contract. A Studio version with missing documented
features is unsupported until the adapter is updated and retested.

## 4. Create and apply the test edit

The helper requires the exact fixture timing above. It obtains actual occurrence
IDs from the live snapshot and generates two restricted versions: repeated A first,
earlier A second, then B alone. The flag confirms the human-created fixture is plain.

```sh
.venv/bin/python tests/make_studio_fixture.py decisions \
  --snapshot jobs/studio-acceptance/calibration-01/snapshot.json \
  --output jobs/studio-acceptance/decisions-01.json --confirm-plain
.venv/bin/python resolve_editor.py plan \
  --snapshot jobs/studio-acceptance/calibration-01/snapshot.json \
  --decisions jobs/studio-acceptance/decisions-01.json \
  --output jobs/studio-acceptance/plan-01.json
.venv/bin/python resolve_editor.py apply \
  --snapshot jobs/studio-acceptance/calibration-01/snapshot.json \
  --decisions jobs/studio-acceptance/decisions-01.json \
  --contract jobs/studio-acceptance/calibration-01/contract.json \
  --job jobs/studio-acceptance/revision-01 --name "Studio acceptance cut"
```

Half-second boundaries deliberately exercise rounding at 25fps: 12.5 frames
rounds to 13, and 62.5 to 63. Exact expected readback:

| Output | Relative output frames | Media | File source frames, exclusive end |
| --- | --- | --- | --- |
| A later passage | 0–50 | A | 163–213 |
| A earlier passage | 50–100 | A | 63–113 |
| B isolated version | 100–150 | B | 38–88 |

The resulting timeline should be **150 frames / 6 seconds**, with three V1 clips,
three linked A1 clips, no output gaps, and the original **01:00:00:00** start
timecode. A's version occupies frames 0–100; B's frames 100–150. Project/timeline
settings and track names/subtypes should match the input. `result.json` must say
`status: passed`; inspect its readback validation, not just the fact a timeline exists.

While the output is selected, independently reread it:

```sh
.venv/bin/python resolve_editor.py verify \
  --snapshot jobs/studio-acceptance/calibration-01/snapshot.json \
  --result jobs/studio-acceptance/revision-01/result.json \
  --contract jobs/studio-acceptance/calibration-01/contract.json
```

Briefly play this small output in Studio. Check linked A/V trims, audible A tone
then B tone, no unintended gap/drift, and correct media. This is a focused live
acceptance check; do not expand it into a routine visual review of every edit.

Select the original again. Confirm the three original occurrences, gap, source
ranges, duration and settings remain intact. Run `apply` again with the same decisions
to **revision-02**; it must create a differently named timeline and leave revision-01
untouched. Reusing revision-01's job folder must fail rather than overwrite artifacts.

## 5. Exercise important refusals and gaps

Use new job/revision names for each check:

- Change a decision version to select an occurrence outside `allowed_clip_ids`.
  Offline `plan` must reject it before any Resolve changes.
- Move one original clip after inspection. `apply` must reject the stale snapshot;
  undo the movement, or inspect again and update the decisions.
- Make a duplicate test input with a transition, Fusion composition, compound or
  multicam clip, a second video/music track, or retiming. `inspect` must report
  detected unsupported structure; `plan`/`apply` must refuse it.
- Test a 24fps source in a 25fps timeline: explicit mixed-rate refusal is expected.
- Restore the plain original and choose one retained range **0–9 seconds** instead
  of the two versions. A new cut must contain A frames 50–150 at output 0–100,
  a **25-frame gap**, then A frames 150–250 at output 125–225, total **225 frames**.
  Read back and verify both video/audio placement on either side of the gap.
- For a retained range **0–5 seconds**, direct apply must refuse a trailing gap
  before creating an output. Use `export-otio` to a new path, then import as a new
  timeline in the disposable project. Confirm duration **125 frames**, linked
  first A excerpt, the trailing 25-frame gap, source timecode interpretation and
  settings. Record this separately as fallback acceptance; it is not yet proven.
- For 23.976/29.97 and drop-frame jobs, create matching-rate test inputs, calibrate
  afresh and repeat a small cut. Confirm rational timing and displayed timecodes.
  Do not infer fractional/drop-frame Studio support solely from offline tests.

## Evidence and completion

Save Studio/OS/Python versions, `doctor` output, snapshots, automatic OTIO exports,
contract, decisions, plans, results and the `verify` output under the acceptance
job. Record whether playback and preservation checks passed. Update `TESTING.md`
with **actual** results, explicitly identifying skipped/failed cases. Never claim
live acceptance merely because fake-adapter tests passed.

After the main fixture passes, the ordinary same-rate rough-cut workflow can be
used on that Studio installation. Keep mixed-rate/complex structures unsupported
until a preservation-capable implementation and corresponding live tests exist.
