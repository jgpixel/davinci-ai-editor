"""Generate small synthetic test media, or decisions for the documented Studio fixture."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import read_json, write_json
from planning import validate_snapshot


def make_decisions(snapshot):
    validate_snapshot(snapshot)
    clips = snapshot['clips']
    if snapshot['fps'] != '25' or len(clips) != 3:
        raise ValueError('Use the three-clip 25fps timeline from STUDIO_TEST_PLAN.md.')
    expected = [(0, 100, 50), (125, 225, 150), (225, 325, 25)]
    if [(c['start_frame'], c['end_frame'], c['source_start_frame']) for c in clips] != expected:
        raise ValueError('Fixture timeline trims/placement differ from STUDIO_TEST_PLAN.md.')
    if clips[0]['media_id'] != clips[1]['media_id'] or clips[0]['media_id'] == clips[2]['media_id']:
        raise ValueError('First two clips must use A, third must use B.')
    if not all(c['has_audio'] for c in clips):
        raise ValueError('Keep embedded stereo audio linked to each fixture clip.')
    return {'schema_version': 1, 'coordinate_space': 'timeline_seconds',
            'snapshot_fingerprint': snapshot['fingerprint'],
            'plain_source_rebuild_confirmed': True,
            'versions': [
                {'name': 'A reordered', 'allowed_clip_ids': [clips[0]['clip_id'], clips[1]['clip_id']],
                 'ranges': [{'start': '5.5', 'end': '7.5', 'reason': 'Later A excerpt first'},
                            {'start': '.5', 'end': '2.5', 'reason': 'Earlier A excerpt second'}]},
                {'name': 'B isolated', 'allowed_clip_ids': [clips[2]['clip_id']],
                 'ranges': [{'start': '9.5', 'end': '11.5', 'reason': 'B-only version'}]}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    media = sub.add_parser('media')
    media.add_argument('--output-dir', required=True, type=Path)
    decisions = sub.add_parser('decisions')
    decisions.add_argument('--snapshot', required=True, type=Path)
    decisions.add_argument('--output', required=True, type=Path)
    decisions.add_argument('--confirm-plain', action='store_true', required=True,
                           help='Operator confirms the synthetic timeline has no effects, grades or other processing')
    args = parser.parse_args()
    try:
        if args.command == 'decisions':
            write_json(args.output, make_decisions(read_json(args.snapshot)))
        else:
            import imageio_ffmpeg
            args.output_dir.mkdir(parents=True, exist_ok=True)
            if any((args.output_dir / (name + '.mov')).exists() for name in ('A', 'B')):
                raise ValueError('Fixture files already exist; choose a new output directory.')
            for name, frequency, tc in [('A', 440, '02:00:00:00'), ('B', 880, '03:00:00:00')]:
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-n',
                    '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25:duration=12',
                    '-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000:duration=12',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'pcm_s16le', '-ac', '2',
                    '-timecode', tc, str(args.output_dir / (name + '.mov'))], check=True, capture_output=True)
        print(args.output.resolve() if args.command == 'decisions' else args.output_dir.resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__': main()
