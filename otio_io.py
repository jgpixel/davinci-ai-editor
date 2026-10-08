"""Conservative OTIO safety inspection and a portable rough-cut fallback."""
from fractions import Fraction
from pathlib import Path
import json
from timing import fps, integer, number


def schema(node):
    return str(node.get('OTIO_SCHEMA', '')).split('.')[0]


def rt(value):
    rate = fps(value['rate'])
    if rate <= 0:
        raise ValueError('Invalid OTIO rate.')
    return number(value['value']) / rate


def inspect_otio(data, rate):
    """Return ordinary clips in track time. Reject structures the builder loses."""
    if schema(data) != 'Timeline' or schema(data.get('tracks', {})) != 'Stack':
        raise ValueError('Expected an OTIO timeline with a tracks stack.')
    stack = data['tracks']
    if stack.get('effects') or stack.get('markers') or stack.get('source_range'):
        raise ValueError('OTIO stack effects, markers or trimmed stacks are unsupported.')
    rows = {'Video': [], 'Audio': []}
    duration_frames = 0
    seen = set()
    for track in stack.get('children', []):
        kind = track.get('kind')
        if schema(track) != 'Track' or kind not in rows:
            raise ValueError('Nested, subtitle or unknown OTIO tracks are unsupported.')
        if kind in seen:
            raise ValueError('Multiple tracks of one kind are unsupported, including empty tracks.')
        seen.add(kind)
        if track.get('effects') or track.get('markers') or track.get('source_range'):
            raise ValueError('Track effects, markers or trims are unsupported.')
        cursor = Fraction(0)
        for child in track.get('children', []):
            typ = schema(child)
            if typ not in ('Clip', 'Gap'):
                raise ValueError(f'Unsupported OTIO structure: {typ} (transitions/nesting cannot be rebuilt).')
            if child.get('effects') or child.get('markers'):
                raise ValueError('Clip effects, retiming or markers are unsupported.')
            source_range = child.get('source_range')
            if not source_range:
                raise ValueError('Missing explicit OTIO source range.')
            duration = rt(source_range['duration'])
            start_frame = integer(cursor * fps(rate))
            end_frame = integer((cursor + duration) * fps(rate))
            if duration <= 0:
                raise ValueError('Nonpositive OTIO duration.')
            if typ == 'Clip':
                reference = child.get('media_reference')
                if reference is None:
                    reference = child.get('media_references', {}).get(child.get('active_media_reference_key'))
                if not reference or schema(reference) != 'ExternalReference':
                    raise ValueError('Offline, generated, compound or multicam media is unsupported.')
                available = reference.get('available_range')
                if not available:
                    raise ValueError('OTIO media has no available source bounds.')
                origin = rt(available['start_time'])
                offset = rt(source_range['start_time']) - origin
                source_rate = fps(source_range['start_time']['rate'])
                if source_rate != fps(rate):
                    raise ValueError('Mixed source/project frame rates are unsupported.')
                if offset < 0 or offset + duration > rt(available['duration']):
                    raise ValueError('OTIO source range lies outside available media.')
                rows[kind].append({'start_frame': start_frame, 'end_frame': end_frame,
                                   'source_start_frame': integer(offset * source_rate),
                                   'source_frames': integer(rt(available['duration']) * source_rate),
                                   'source_origin_seconds': str(origin),
                                   'target_url': reference.get('target_url', '')})
            cursor += duration
        duration_frames = max(duration_frames, integer(cursor * fps(rate)))
    rows['duration_frames'] = duration_frames
    return rows


def rational(value, rate):
    return {'OTIO_SCHEMA': 'RationalTime.1', 'value': float(value), 'rate': float(fps(rate))}


def time_range(start, duration, rate):
    return {'OTIO_SCHEMA': 'TimeRange.1', 'start_time': rational(start, rate),
            'duration': rational(duration, rate)}


def export_plan(plan, snapshot, path, name):
    """Write standard OTIO JSON. Preserve source timecode origins, never clip effects."""
    tracks = []
    clips = {c['clip_id']: c for c in snapshot['clips']}
    for kind in ('Video', 'Audio'):
        children = []
        for segment in plan['segments']:
            length = segment['duration_frames']
            if segment['kind'] == 'gap' or (kind == 'Audio' and not segment['has_audio']):
                children.append({'OTIO_SCHEMA': 'Gap.1', 'name': '', 'metadata': {}, 'effects': [],
                                 'markers': [], 'source_range': time_range(0, length, plan['fps'])})
                continue
            clip = clips[segment['clip_id']]
            origin = number(clip['source_origin_seconds']) * fps(plan['fps'])
            reference = {'OTIO_SCHEMA': 'ExternalReference.1', 'name': '', 'metadata': {},
                         'target_url': Path(segment['source_path']).as_uri(),
                         'available_range': time_range(origin, clip['source_frames'], plan['fps'])}
            children.append({'OTIO_SCHEMA': 'Clip.2', 'name': clip['name'],
                             'metadata': {}, 'effects': [], 'markers': [],
                             'source_range': time_range(origin + segment['source_start_frame'], length, plan['fps']),
                             'media_references': {'DEFAULT_MEDIA': reference},
                             'active_media_reference_key': 'DEFAULT_MEDIA'})
        if kind == 'Audio' and not any(s.get('has_audio') for s in plan['segments']):
            continue
        tracks.append({'OTIO_SCHEMA': 'Track.1', 'name': kind + ' 1', 'kind': kind,
                       'metadata': {}, 'effects': [], 'markers': [], 'source_range': None, 'children': children})
    timeline = {'OTIO_SCHEMA': 'Timeline.1', 'name': name, 'metadata': {},
                'global_start_time': rational(snapshot['start_frame'], plan['fps']),
                'tracks': {'OTIO_SCHEMA': 'Stack.1', 'name': 'tracks', 'metadata': {},
                           'effects': [], 'markers': [], 'source_range': None, 'children': tracks}}
    # Check the same safety/timing parser before writing a delivery artifact.
    inspect_otio(timeline, plan['fps'])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(timeline, handle, indent=2, allow_nan=False)
        handle.write('\n')
    return timeline
