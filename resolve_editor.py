#!/usr/bin/env python3
"""Inspect and construct Resolve Studio rough cuts from explicit ordered decisions."""
import argparse
import json
from pathlib import Path
import sys

from common import read_json, write_json
from otio_io import export_plan
from planning import build_plan, validate_snapshot
from resolve_api import connect, doctor
from timing import file_to_timeline, fps, number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Inspect local scripting files without importing or launching Resolve')
    inspect = sub.add_parser('inspect', help='Read selected live timeline, including automatic OTIO safety inspection')
    inspect.add_argument('--job', required=True, type=Path)
    calibrate = sub.add_parser('calibrate', help='Create an isolated API probe, read it back, restore selected original')
    calibrate.add_argument('--job', required=True, type=Path)
    verify = sub.add_parser('verify', help='Read back the selected delivered timeline again without changing it')
    verify.add_argument('--snapshot', required=True, type=Path)
    verify.add_argument('--result', required=True, type=Path)
    verify.add_argument('--contract', required=True, type=Path)
    mapping = sub.add_parser('map', help='Map a file speech interval to a specific saved clip occurrence')
    mapping.add_argument('--snapshot', required=True, type=Path)
    mapping.add_argument('--clip-id', required=True)
    mapping.add_argument('--file-start', required=True)
    mapping.add_argument('--file-end', required=True)
    for command in ('plan', 'apply', 'export-otio'):
        command_parser = sub.add_parser(command)
        command_parser.add_argument('--snapshot', required=True, type=Path)
        command_parser.add_argument('--decisions', required=True, type=Path)
        if command == 'apply':
            command_parser.add_argument('--contract', required=True, type=Path)
            command_parser.add_argument('--job', required=True, type=Path)
        else:
            command_parser.add_argument('--output', required=True, type=Path)
        if command in ('apply', 'export-otio'):
            command_parser.add_argument('--name')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            result = doctor()
        elif args.command in ('inspect', 'calibrate'):
            args.job.mkdir(parents=True, exist_ok=True)
            targets = [args.job / 'snapshot.json', args.job / 'inspection.otio']
            if args.command == 'calibrate':
                targets.append(args.job / 'contract.json')
            if any(p.exists() for p in targets):
                raise ValueError('Job contains inspection/calibration outputs; use a new job folder.')
            session = connect()
            snapshot, media = session.inspect(args.job / 'inspection.otio')
            write_json(args.job / 'snapshot.json', snapshot)
            result = {'snapshot': str((args.job / 'snapshot.json').resolve()),
                      'project': snapshot['project_name'], 'timeline': snapshot['timeline_name'],
                      'duration_frames': snapshot['duration_frames'], 'fps': snapshot['fps'],
                      'limitations': snapshot['limitations'], 'clips': snapshot['clips'],
                      'audit_note': snapshot['audit_note']}
            if args.command == 'calibrate':
                result['calibration'] = session.calibrate(snapshot, media, args.job / 'contract.json')
                result['contract'] = str((args.job / 'contract.json').resolve())
        else:
            snapshot = read_json(args.snapshot)
            if args.command == 'verify':
                validate_snapshot(snapshot)
                delivered, contract = read_json(args.result), read_json(args.contract)
                session = connect()
                if contract.get('status') != 'passed' or contract.get('environment') != session.environment():
                    raise ValueError('Missing/stale calibration contract.')
                if session.timeline.GetUniqueId() != delivered['timeline_id']:
                    raise ValueError('Select the delivered output timeline in Studio before verifying.')
                plan = delivered['plan']
                if plan['snapshot_fingerprint'] != snapshot['fingerprint']:
                    raise ValueError('Result refers to another input snapshot.')
                result = {'timeline_name': session.timeline.GetName(),
                          'validation': session.verify(session.timeline, snapshot, plan, contract),
                          'duration_frames': plan['duration_frames'], 'fps': plan['fps']}
            elif args.command == 'map':
                validate_snapshot(snapshot)
                clip = next((c for c in snapshot['clips'] if c['clip_id'] == args.clip_id), None)
                if clip is None:
                    raise ValueError('Unknown clip occurrence ID.')
                rate = fps(clip['source_fps'])
                source_start = clip['source_start_frame'] / rate
                source_end = source_start + (clip['end_frame'] - clip['start_frame']) / rate
                if not source_start <= number(args.file_start) < number(args.file_end) <= source_end:
                    raise ValueError('File interval is outside this trimmed clip occurrence.')
                result = {'coordinate_space': 'timeline_seconds', 'clip_id': args.clip_id,
                          'start': file_to_timeline(clip, args.file_start, snapshot['fps']),
                          'end': file_to_timeline(clip, args.file_end, snapshot['fps'])}
            else:
                decisions = read_json(args.decisions)
                plan = build_plan(snapshot, decisions)
                if args.command == 'plan':
                    write_json(args.output, plan)
                    result = {'plan': str(args.output.resolve()), 'duration_seconds': plan['duration_seconds'],
                              'duration_frames': plan['duration_frames'], 'segments': len(plan['segments']),
                              'versions': plan['versions'], 'validation': 'offline timing/structure/source restrictions passed'}
                elif args.command == 'export-otio':
                    if args.output.exists() or args.output.with_suffix('.manifest.json').exists():
                        raise ValueError('Fallback output exists; use a new path.')
                    export_plan(plan, snapshot, args.output, args.name or snapshot['timeline_name'] + ' - Rough cut')
                    write_json(args.output.with_suffix('.manifest.json'), plan)
                    result = {'output': str(args.output.resolve()), 'duration_seconds': plan['duration_seconds'],
                              'validation': 'offline OTIO structure/timing only; import and settings unverified',
                              'note': 'Manual fallback only. Import into Studio as a NEW timeline, then check source ranges/settings.'}
                else:
                    if args.job.exists() and any(args.job.iterdir()):
                        raise ValueError('Apply job must be new/empty; previous revisions are preserved.')
                    args.job.mkdir(parents=True, exist_ok=True)
                    contract = read_json(args.contract)
                    session = connect()
                    live, media = session.inspect(args.job / 'before.otio')
                    write_json(args.job / 'before.json', live)
                    if live['fingerprint'] != snapshot['fingerprint']:
                        raise ValueError('Selected project/timeline or sources changed since inspection. '
                                         'Select the original, inspect again, and update decisions.')
                    write_json(args.job / 'decisions.json', decisions)
                    write_json(args.job / 'plan.json', plan)
                    result = session.apply(live, plan, media, contract, args.job, args.name)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
