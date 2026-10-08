"""Apply explicit editorial choices without an editor, media decode, or AI model."""
from common import digest
from timing import fps, integer, number, snap


def fingerprint(snapshot):
    return digest({k: v for k, v in snapshot.items() if k not in ('fingerprint', 'export_path')})


def validate_snapshot(snapshot):
    if snapshot.get('schema_version') != 1:
        raise ValueError('Unsupported snapshot schema.')
    if snapshot.get('fingerprint') != fingerprint(snapshot):
        raise ValueError('Snapshot fingerprint mismatch.')
    if snapshot.get('limitations'):
        raise ValueError('Unsupported timeline: ' + '; '.join(snapshot['limitations']))
    rate = fps(snapshot['fps'])
    if rate <= 0 or snapshot['duration_frames'] <= 0:
        raise ValueError('Timeline frame rate and duration must be positive.')
    cursor = 0
    ids = set()
    for clip in snapshot['clips']:
        start, end = integer(clip['start_frame']), integer(clip['end_frame'])
        if start < cursor or start < 0 or end <= start or end > snapshot['duration_frames']:
            raise ValueError('Invalid or overlapping timeline clip bounds.')
        if clip['clip_id'] in ids:
            raise ValueError('Duplicate occurrence ID.')
        ids.add(clip['clip_id'])
        if fps(clip['source_fps']) != rate:
            raise ValueError(f'Mixed frame rates unsupported for {clip["clip_id"]}: '
                             f'{clip["source_fps"]} versus {snapshot["fps"]}.')
        source = integer(clip['source_start_frame'])
        if source < 0 or source + end - start > integer(clip['source_frames']):
            raise ValueError('Selected source extends beyond media bounds.')
        cursor = end
    if not ids:
        raise ValueError('No ordinary video clips in timeline.')


def build_plan(snapshot, decisions):
    validate_snapshot(snapshot)
    if decisions.get('schema_version') != 1 or decisions.get('coordinate_space') != 'timeline_seconds':
        raise ValueError('Use schema_version: 1 and coordinate_space: timeline_seconds.')
    if decisions.get('snapshot_fingerprint') != snapshot['fingerprint']:
        raise ValueError('Decisions must reference this snapshot_fingerprint.')
    # Read-only APIs cannot establish absence of every grade, OFX or Fairlight effect.
    if decisions.get('plain_source_rebuild_confirmed') is not True:
        raise ValueError('A human must confirm plain_source_rebuild_confirmed after checking the timeline. '
                         'Rebuilding does not preserve clip-level grades/effects.')
    versions = decisions.get('versions')
    if versions is not None and 'allowed_clip_ids' in decisions:
        raise ValueError('Put source restrictions inside each version; top-level restrictions are ambiguous with versions.')
    if versions is None:
        versions = [{'name': 'Edit', 'ranges': decisions.get('ranges'),
                     'allowed_clip_ids': decisions.get('allowed_clip_ids')}]
    if not isinstance(versions, list) or not versions or ('ranges' in decisions and 'versions' in decisions):
        raise ValueError('Specify nonempty versions OR ranges, not both.')
    rate = fps(snapshot['fps'])
    minimum = integer(decisions.get('minimum_clip_frames', 3))
    if minimum < 1:
        raise ValueError('minimum_clip_frames must be positive.')
    all_ids = {c['clip_id'] for c in snapshot['clips']}
    cursor, segments, version_rows, aligned = 0, [], [], []
    names = set()
    for version in versions:
        if not isinstance(version, dict) or not isinstance(version.get('name'), str) or not version['name'].strip():
            raise ValueError('Every version needs a nonempty name.')
        name = version['name']
        if name in names:
            raise ValueError('Version names must be unique.')
        names.add(name)
        allowed = version.get('allowed_clip_ids')
        if allowed is None and decisions.get('versions') is not None:
            raise ValueError('Each separate version must specify allowed_clip_ids to isolate original clips.')
        if allowed is not None and (not isinstance(allowed, list) or not allowed or not set(allowed) <= all_ids):
            raise ValueError('allowed_clip_ids must contain known occurrence IDs.')
        ranges = version.get('ranges')
        if not isinstance(ranges, list) or not ranges:
            raise ValueError('Each version needs nonempty ordered ranges.')
        version_start = cursor
        for row in ranges:
            if not isinstance(row, dict) or 'start' not in row or 'end' not in row:
                raise ValueError('Each retained range needs start and end.')
            a, b = number(row['start']), number(row['end'])
            if not 0 <= a < b <= snapshot['duration_frames'] / rate:
                raise ValueError(f'Empty or out-of-bounds range: {row}')
            start, end = snap(a, rate), snap(b, rate)
            if end <= start:
                raise ValueError('Range becomes empty after frame alignment.')
            aligned.append({'version': name, 'requested_start': str(a), 'requested_end': str(b),
                            'start_frame': start, 'end_frame': end, 'reason': row.get('reason', '')})
            boundaries = {start, end}
            for clip in snapshot['clips']:
                if clip['end_frame'] > start and clip['start_frame'] < end:
                    boundaries.update((max(start, clip['start_frame']), min(end, clip['end_frame'])))
            boundaries = sorted(boundaries)
            for left, right in zip(boundaries, boundaries[1:]):
                clip = next((c for c in snapshot['clips'] if c['start_frame'] <= left < c['end_frame']), None)
                length = right - left
                segment = {'kind': 'gap' if clip is None else 'clip', 'version': name,
                           'output_start_frame': cursor, 'duration_frames': length,
                           'original_start_frame': left, 'reason': row.get('reason', '')}
                if clip:
                    if allowed is not None and clip['clip_id'] not in allowed:
                        raise ValueError(f'Version {name} selects disallowed occurrence {clip["clip_id"]}.')
                    if length < minimum:
                        raise ValueError(f'Tiny fragment ({length} frames); change decisions or explicitly lower minimum_clip_frames.')
                    source_start = clip['source_start_frame'] + left - clip['start_frame']
                    if source_start + length > clip['source_frames']:
                        raise ValueError('Retained range exceeds source bounds.')
                    segment.update(clip_id=clip['clip_id'], media_id=clip['media_id'],
                                   source_path=clip['source_path'], source_fps=clip['source_fps'],
                                   source_start_frame=source_start, source_end_frame=source_start + length,
                                   source_timecode=clip['source_timecode'], has_audio=clip['has_audio'])
                segments.append(segment)
                cursor += length
        if not any(s['kind'] == 'clip' and s['version'] == name for s in segments):
            raise ValueError(f'Version {name} retains no media.')
        version_rows.append({'name': name, 'start_frame': version_start, 'end_frame': cursor,
                             'allowed_clip_ids': allowed})
    plan = {'schema_version': 1, 'snapshot_fingerprint': snapshot['fingerprint'],
            'project_id': snapshot['project_id'], 'timeline_id': snapshot['timeline_id'],
            'fps': snapshot['fps'], 'start_timecode': snapshot['start_timecode'],
            'duration_frames': cursor, 'duration_seconds': str(cursor / rate),
            'ranges': aligned, 'versions': version_rows, 'segments': segments,
            'plain_source_rebuild_confirmed': True}
    plan['fingerprint'] = digest(plan)
    return plan
