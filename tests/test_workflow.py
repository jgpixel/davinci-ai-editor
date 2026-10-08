from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import read_json, write_json
from otio_io import export_plan, inspect_otio
from planning import build_plan, fingerprint, validate_snapshot
from resolve_api import Session
from timing import file_to_timeline, fps, snap
from tests.fixtures import Resolve, decisions, snapshot


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / 'source.mov'
        self.media.write_bytes(b'fixture identity only; never decoded')
        self.snap = snapshot(self.media)
    def tearDown(self): self.temp.cleanup()
    def plan(self, ranges=None): return build_plan(self.snap, decisions(self.snap, ranges))

    def test_reordered_repeated_trimmed_source_mapping(self):
        plan = self.plan()
        self.assertEqual([s['source_start_frame'] for s in plan['segments']], [30, 10])
        self.assertEqual([s['output_start_frame'] for s in plan['segments']], [0, 50])
        self.assertEqual(plan['duration_frames'], 100)
        self.assertEqual(plan['start_timecode'], '01:00:00:00')

    def test_file_speech_time_maps_per_occurrence(self):
        self.assertEqual(file_to_timeline(self.snap['clips'][0], '2', '25'), '8/5')
        self.assertEqual(file_to_timeline(self.snap['clips'][1], '2', '25'), '44/5')

    def test_preserve_explicit_gap_when_range_crosses_clips(self):
        plan = self.plan([{'start': 2, 'end': 10}])
        self.assertEqual([s['kind'] for s in plan['segments']], ['clip', 'gap', 'clip'])
        self.assertEqual([s['duration_frames'] for s in plan['segments']], [50, 100, 50])
        self.assertEqual(plan['duration_frames'], 200)

    def test_two_versions_stay_isolated_and_back_to_back(self):
        data = decisions(self.snap)
        data.pop('ranges')
        data['versions'] = [{'name': 'First', 'allowed_clip_ids': ['v1'], 'ranges': [{'start': 1, 'end': 3}]},
                            {'name': 'Second', 'allowed_clip_ids': ['v2'], 'ranges': [{'start': 8, 'end': 10}]}]
        plan = build_plan(self.snap, data)
        self.assertEqual([s['clip_id'] for s in plan['segments']], ['v1', 'v2'])
        self.assertEqual([v['start_frame'] for v in plan['versions']], [0, 50])
        data['versions'][1]['ranges'] = [{'start': 0, 'end': 2}]
        with self.assertRaisesRegex(ValueError, 'disallowed'): build_plan(self.snap, data)

    def test_versions_require_source_restrictions(self):
        data = decisions(self.snap)
        data.pop('ranges')
        data['versions'] = [{'name': 'A', 'ranges': [{'start': 0, 'end': 2}]}]
        with self.assertRaisesRegex(ValueError, 'allowed_clip_ids'): build_plan(self.snap, data)

    def test_frames_exact_at_ntsc_rate(self):
        self.assertEqual(fps('29.97 DF'), Fraction(30000, 1001))
        self.assertEqual(fps('23.976'), Fraction(24000, 1001))
        self.assertEqual(snap('1001/24000', '23.976'), 1)
        self.assertEqual(snap('1/50', '25'), 1)  # ties upward
        self.assertEqual(fps('29.970'), Fraction(30000, 1001))

    def test_ntsc_otio_double_rate_restores_exact_frame_grid(self):
        for rate in ('23.976', '29.97', '59.94'):
            snap = deepcopy(self.snap)
            snap['fps'] = str(fps(rate))
            for clip in snap['clips']:
                clip['source_fps'] = snap['fps']
            snap['fingerprint'] = fingerprint(snap)
            data = decisions(snap, [{'start': '0', 'end': str(Fraction(50) / fps(rate))}])
            plan = build_plan(snap, data)
            exported = export_plan(plan, snap, self.root / (rate + '.otio'), 'Fractional rate')
            self.assertEqual(inspect_otio(exported, rate)['duration_frames'], 50)

    def test_acceptance_helper_creates_exact_isolated_versions(self):
        from tests.make_studio_fixture import make_decisions
        snap = deepcopy(self.snap)
        snap['duration_frames'] = 325
        snap['clips'][0].update(start_frame=0, end_frame=100, source_start_frame=50)
        snap['clips'][1].update(start_frame=125, end_frame=225, source_start_frame=150)
        last = deepcopy(snap['clips'][0])
        last.update(clip_id='v3', media_id='media2', start_frame=225, end_frame=325, source_start_frame=25)
        snap['clips'].append(last)
        snap['fingerprint'] = fingerprint(snap)
        plan = build_plan(snap, make_decisions(snap))
        self.assertEqual(plan['duration_frames'], 150)
        self.assertEqual([s['source_start_frame'] for s in plan['segments']], [163, 63, 38])
        self.assertEqual([s['media_id'] for s in plan['segments']], ['media1', 'media1', 'media2'])
        snap['clips'][1]['start_frame'] += 1
        snap['fingerprint'] = fingerprint(snap)
        with self.assertRaisesRegex(ValueError, 'trims/placement'): make_decisions(snap)

    def test_manual_fallback_retains_trailing_gap(self):
        plan = self.plan([{'start': 0, 'end': 6}])
        data = export_plan(plan, self.snap, self.root / 'trailing.otio', 'Trailing gap')
        self.assertEqual(inspect_otio(data, '25')['duration_frames'], 150)
        try:
            import opentimelineio as otio
        except ImportError:
            self.skipTest('Optional OTIO library is not installed')
        self.assertEqual(otio.adapters.read_from_file(str(self.root / 'trailing.otio')).duration().value, 150)

    def test_invalid_ranges_and_tiny_fragments(self):
        for row in ({'start': -1, 'end': 1}, {'start': 0, 'end': 13}, {'start': 2, 'end': 1},
                    {'start': 0, 'end': '1/1000'}, {'start': 0, 'end': '1/25'},
                    {'start': True, 'end': 1}, {'start': 'NaN', 'end': 1}):
            with self.subTest(row=row), self.assertRaises(ValueError): self.plan([row])

    def test_tiny_fragment_can_be_explicitly_authorized(self):
        data = decisions(self.snap, [{'start': 0, 'end': '1/25'}])
        data['minimum_clip_frames'] = 1
        self.assertEqual(build_plan(self.snap, data)['duration_frames'], 1)

    def test_stale_decisions_and_tampered_snapshot_fail(self):
        data = decisions(self.snap)
        data['snapshot_fingerprint'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'reference'): build_plan(self.snap, data)
        self.snap['clips'][0]['source_start_frame'] = 50
        with self.assertRaisesRegex(ValueError, 'fingerprint'): validate_snapshot(self.snap)

    def test_mixed_rates_rejected_explicitly(self):
        self.snap['clips'][0]['source_fps'] = '24'
        self.snap['fingerprint'] = fingerprint(self.snap)
        with self.assertRaisesRegex(ValueError, 'Mixed'): self.plan()

    def test_overlap_and_source_bounds_rejected(self):
        for key, value in [('start_frame', 50), ('source_start_frame', 999)]:
            snap = deepcopy(self.snap)
            snap['clips'][1][key] = value
            snap['fingerprint'] = fingerprint(snap)
            with self.assertRaises(ValueError): validate_snapshot(snap)

    def test_human_plain_timeline_check_required(self):
        data = decisions(self.snap)
        data.pop('plain_source_rebuild_confirmed')
        with self.assertRaisesRegex(ValueError, 'human'): build_plan(self.snap, data)

    def test_gap_only_version_fails(self):
        with self.assertRaisesRegex(ValueError, 'no media'): self.plan([{'start': 4, 'end': 6}])

    def test_duplicate_version_names_fail(self):
        data = decisions(self.snap)
        data.pop('ranges')
        row = {'name': 'A', 'allowed_clip_ids': ['v1'], 'ranges': [{'start': 0, 'end': 2}]}
        data['versions'] = [row, row]
        with self.assertRaisesRegex(ValueError, 'unique'): build_plan(self.snap, data)

    def test_outputs_never_overwritten(self):
        target = self.root / 'old.json'
        write_json(target, {'old': True})
        with self.assertRaises(FileExistsError): write_json(target, {})
        self.assertEqual(read_json(target), {'old': True})

    def test_otio_nonzero_media_timecode_and_gap_roundtrip(self):
        plan = self.plan([{'start': 2, 'end': 10}])
        path = self.root / 'edit.otio'
        data = export_plan(plan, self.snap, path, 'Cut')
        rows = inspect_otio(data, '25')
        self.assertEqual(rows['duration_frames'], 200)
        self.assertEqual([r['source_start_frame'] for r in rows['Video']], [60, 30])
        self.assertEqual(rows['Video'][0]['source_origin_seconds'], '7200')
        self.assertEqual(len(rows['Audio']), 2)
        try:
            import opentimelineio as otio
        except ImportError:
            self.skipTest('Optional OTIO library is not installed')
        loaded = otio.adapters.read_from_file(str(path))
        self.assertEqual(loaded.duration().value, 200)
        self.assertEqual(loaded.tracks[0][0].source_range.start_time.value, 180060)

    def test_otio_rejects_transitions_effects_and_nesting(self):
        data = export_plan(self.plan(), self.snap, self.root / 'a.otio', 'Cut')
        for typ in ('Transition.1', 'Stack.1'):
            bad = deepcopy(data)
            bad['tracks']['children'][0]['children'][0]['OTIO_SCHEMA'] = typ
            with self.assertRaisesRegex(ValueError, 'Unsupported'): inspect_otio(bad, '25')
        bad = deepcopy(data)
        bad['tracks']['children'][0]['children'][0]['effects'] = [{'OTIO_SCHEMA': 'LinearTimeWarp.1'}]
        with self.assertRaisesRegex(ValueError, 'effects'): inspect_otio(bad, '25')

    def test_offline_cli_plan_and_map(self):
        write_json(self.root / 'snapshot.json', self.snap)
        write_json(self.root / 'decisions.json', decisions(self.snap))
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'resolve_editor.py')]
        result = subprocess.run(command + ['plan', '--snapshot', str(self.root / 'snapshot.json'),
            '--decisions', str(self.root / 'decisions.json'), '--output', str(self.root / 'plan.json')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_json(self.root / 'plan.json')['duration_frames'], 100)
        result = subprocess.run(command + ['map', '--snapshot', str(self.root / 'snapshot.json'),
            '--clip-id', 'v2', '--file-start', '2', '--file-end', '3'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['start'], '44/5')


class AdapterTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    tearDown = WorkflowTests.tearDown
    def session(self):
        resolve = Resolve(self.media)
        return Session(resolve, 'doc'), resolve.project

    def test_fake_inspection_calibration_apply_readback(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        self.assertEqual(snap['limitations'], [])
        contract = session.calibrate(snap, media, self.root / 'contract.json')
        self.assertEqual(contract['status'], 'passed')
        self.assertIs(project.current, project.original)
        self.assertFalse(project.original.deleted)
        plan = build_plan(snap, decisions(snap))
        result = session.apply(snap, plan, media, contract, self.root / 'apply', 'Cut')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['duration_frames'], 100)
        self.assertFalse(project.original.deleted)
        self.assertEqual([i.source for i in project.current.video], [30, 10])
        self.assertEqual([len(i.links) for i in project.current.video], [1, 1])
        self.assertEqual(len(project.timelines), 3)  # original + retained probe + new cut

    def test_failed_append_preserves_original_and_failed_output(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        contract = session.calibrate(snap, media, self.root / 'contract.json')
        project.bad_append = True
        with self.assertRaisesRegex(RuntimeError, 'Append failed'):
            session.apply(snap, build_plan(snap, decisions(snap)), media, contract, self.root / 'apply', 'Cut')
        self.assertFalse(project.original.deleted)
        self.assertIs(project.current, project.original)
        self.assertEqual(read_json(self.root / 'apply/result.json')['status'], 'failed')
        self.assertEqual(len(project.timelines), 3)

    def test_calibration_failure_does_not_certify_conventions(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        project.bad_append = True
        with self.assertRaisesRegex(RuntimeError, 'Probe append'):
            session.calibrate(snap, media, self.root / 'contract.json')
        self.assertEqual(read_json(self.root / 'contract.json')['status'], 'failed')
        self.assertIs(project.current, project.original)
        self.assertFalse(project.original.deleted)

    def test_duplicate_returning_original_never_deletes(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        project.bad_duplicate = True
        with self.assertRaisesRegex(RuntimeError, 'existing timeline'):
            session.calibrate(snap, media, self.root / 'contract.json')
        self.assertFalse(project.original.deleted)

    def test_stale_contract_does_not_create_output(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        contract = {'status': 'passed', 'environment': {'version': 'old'}}
        with self.assertRaisesRegex(ValueError, 'stale'):
            session.apply(snap, build_plan(snap, decisions(snap)), media, contract, self.root / 'apply', 'Cut')
        self.assertEqual(len(project.timelines), 1)

    def test_detect_unsupported_structures_before_edit(self):
        for key, value, expected in [('fusion', 1, 'Fusion'), ('nodes', 2, 'color nodes'),
                                     ('properties', {'ZoomX': 2}, 'ZoomX')]:
            session, project = self.session()
            setattr(project.original.video[0], key, value)
            snap, _ = session.inspect(self.root / (key + '.otio'))
            self.assertTrue(any(expected in e for e in snap['limitations']), snap['limitations'])
            self.assertFalse(project.original.deleted)
        session, project = self.session()
        project.original.extra_video = True
        snap, _ = session.inspect(self.root / 'tracks.otio')
        self.assertTrue(any('V1' in e for e in snap['limitations']))

    def test_unlinked_audio_detected_before_edit(self):
        session, project = self.session()
        project.original.video[0].links = []
        snap, _ = session.inspect(self.root / 'unlinked.otio')
        self.assertTrue(any('unlinked' in e for e in snap['limitations']))

    def test_readback_mismatch_rejected(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        contract = session.calibrate(snap, media, self.root / 'contract.json')
        plan = build_plan(snap, decisions(snap))
        session.apply(snap, plan, media, contract, self.root / 'apply', 'Cut')
        project.current.video[0].source += 1
        with self.assertRaisesRegex(RuntimeError, 'mismatch'): session.verify(project.current, snap, plan, contract)

    def test_trailing_gap_direct_path_fails_before_mutation(self):
        session, project = self.session()
        snap, media = session.inspect(self.root / 'inspection.otio')
        contract = session.calibrate(snap, media, self.root / 'contract.json')
        plan = build_plan(snap, decisions(snap, [{'start': 0, 'end': 6}]))
        with self.assertRaisesRegex(ValueError, 'trailing'):
            session.apply(snap, plan, media, contract, self.root / 'apply', 'Cut')
        self.assertEqual(len(project.timelines), 2)


if __name__ == '__main__': unittest.main()
