"""Official Resolve 20.2 API adapter. Never launch Resolve or touch its database."""
import importlib
import os
from pathlib import Path
import platform
import sys
from urllib.parse import unquote, urlparse

from common import digest, file_identity, read_json, token, write_json
from otio_io import inspect_otio
from planning import fingerprint
from timing import fps, integer, number

NEEDED_DOC = ('GetSourceStartFrame()', 'GetSourceEndFrame()', 'GetLinkedItems()',
              'DuplicateTimeline(', 'EXPORT_OTIO', 'recordFrame', 'SetClipsLinked(')


def locations():
    if sys.platform == 'darwin':
        api = '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting'
        lib = '/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so'
    elif sys.platform == 'win32':
        api = str(Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting')
        lib = 'C:/Program Files/Blackmagic Design/DaVinci Resolve/fusionscript.dll'
    else:
        api, lib = '/opt/resolve/Developer/Scripting', '/opt/resolve/libs/Fusion/fusionscript.so'
    return Path(os.environ.get('RESOLVE_SCRIPT_API', api)), Path(os.environ.get('RESOLVE_SCRIPT_LIB', lib))


def doctor():
    api, lib = locations()
    documentation = api / 'README.txt'
    text = documentation.read_text(encoding='utf-8') if documentation.is_file() else ''
    return {'os': platform.platform(), 'python': sys.version.split()[0],
            'machine': platform.machine(), 'api_path': str(api), 'library_path': str(lib),
            'module_exists': (api / 'Modules/DaVinciResolveScript.py').is_file(),
            'library_exists': lib.is_file(), 'documentation_exists': bool(text),
            'documentation_sha256': digest(text) if text else None,
            'missing_documented_features': [name for name in NEEDED_DOC if name not in text],
            'connected': False, 'note': 'Static inspection only; Resolve was not imported or launched.'}


def connect():
    info = doctor()
    if not info['module_exists'] or not info['library_exists'] or not info['documentation_exists']:
        raise RuntimeError('Install Resolve Studio and locate its Developer/Scripting files. '
                           'Set RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB for a custom install; run doctor.')
    if info['missing_documented_features']:
        raise RuntimeError('Installed API lacks required features: ' + ', '.join(info['missing_documented_features']))
    sys.path.insert(0, str(Path(info['api_path']) / 'Modules'))
    os.environ.setdefault('RESOLVE_SCRIPT_LIB', info['library_path'])
    try:
        resolve = importlib.import_module('DaVinciResolveScript').scriptapp('Resolve')
    except (ImportError, OSError) as exc:
        raise RuntimeError('Cannot load Resolve scripting library. Use compatible 64-bit Python '
                           'and architecture; check the installed scripting README.') from exc
    if resolve is None:
        raise RuntimeError('No Resolve connection. Start Studio, enable Preferences → System → '
                           'General → External Scripting Using → Local, and restart if requested.')
    if 'studio' not in str(resolve.GetProductName()).lower():
        raise RuntimeError('External scripting workflow requires DaVinci Resolve Studio.')
    return Session(resolve, info['documentation_sha256'])


def checked(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def items(timeline, kind):
    return [item for track in range(1, timeline.GetTrackCount(kind) + 1)
            for item in (timeline.GetItemListInTrack(kind, track) or [])]


def signature(item):
    media = item.GetMediaPoolItem()
    return (media.GetUniqueId() if media else None, integer(item.GetStart()),
            integer(item.GetEnd()), integer(item.GetSourceStartFrame()))


def local_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('', 'file') or parsed.netloc not in ('', 'localhost'):
        raise ValueError('Nonlocal OTIO media path is unsupported.')
    path = unquote(parsed.path) if parsed.scheme else url
    if sys.platform == 'win32' and path.startswith('/') and len(path) > 2 and path[2] == ':':
        path = path[1:]
    return str(Path(path).expanduser().resolve())


def safety(item, kind):
    errors = []
    if not item.GetClipEnabled():
        errors.append('disabled clip')
    if item.GetFusionCompCount():
        errors.append('Fusion composition')
    if item.GetTakesCount():
        errors.append('take selector')
    if item.GetMarkers():
        errors.append('clip markers')
    if kind == 'video':
        graph = item.GetNodeGraph()
        if graph and graph.GetNumNodes() > 1:
            errors.append('multiple color nodes')
        if item.GetColorGroup():
            errors.append('color group')
        defaults = {'Pan': 0, 'Tilt': 0, 'ZoomX': 1, 'ZoomY': 1, 'RotationAngle': 0,
                    'AnchorPointX': 0, 'AnchorPointY': 0, 'Pitch': 0, 'Yaw': 0,
                    'FlipX': False, 'FlipY': False, 'CropLeft': 0, 'CropRight': 0,
                    'CropTop': 0, 'CropBottom': 0, 'CropSoftness': 0, 'Opacity': 100,
                    'CompositeMode': 0, 'Distortion': 0, 'RetimeProcess': 0,
                    'MotionEstimation': 0, 'Scaling': 0}
        properties = item.GetProperty() or {}
        for key, default in defaults.items():
            if key in properties and properties[key] != default:
                errors.append(f'non-default {key}')
    voice = item.GetVoiceIsolationState() or {}
    if voice.get('isEnabled'):
        errors.append('voice isolation')
    return errors


def audio_mapping(media):
    data = media.GetAudioMapping()
    if not data:
        raise ValueError('Cannot inspect embedded audio mapping.')
    import json
    data = json.loads(data) if isinstance(data, str) else data
    mapping = data.get('track_mapping', {})
    if data.get('linked_audio') or len(mapping) != 1:
        raise ValueError('External/synced or multiple audio mappings are unsupported.')
    track = next(iter(mapping.values()))
    channels = data.get('embedded_audio_channels')
    if channels not in (1, 2) or track.get('channel_idx') != list(range(1, channels + 1)) or track.get('mute'):
        raise ValueError('Only unchanged embedded mono/stereo audio is supported.')
    return data


class Session:
    def __init__(self, resolve, documentation_hash):
        self.resolve = resolve
        self.documentation_hash = documentation_hash
        self.manager = checked(resolve.GetProjectManager(), 'No project manager.')
        self.project = checked(self.manager.GetCurrentProject(), 'Open a project in Studio.')
        self.timeline = checked(self.project.GetCurrentTimeline(), 'Select a timeline in Studio.')
        self.pool = checked(self.project.GetMediaPool(), 'No media pool.')

    def environment(self):
        return {'product': self.resolve.GetProductName(), 'version': self.resolve.GetVersionString(),
                'documentation_sha256': self.documentation_hash,
                'project_id': self.project.GetUniqueId(),
                'fps': str(fps(self.timeline.GetSetting('timelineFrameRate')))}

    def assert_current(self):
        project = checked(self.manager.GetCurrentProject(), 'Project closed during operation.')
        if project.GetUniqueId() != self.project.GetUniqueId():
            raise RuntimeError('Project changed during operation; stopped.')

    def inspect(self, export_path):
        self.assert_current()
        timeline = self.timeline
        export_path = Path(export_path).resolve()
        if export_path.exists():
            raise ValueError('Inspection export path exists; choose a new job/revision.')
        export_path.parent.mkdir(parents=True, exist_ok=True)
        checked(timeline.Export(str(export_path), self.resolve.EXPORT_OTIO), 'Automatic OTIO inspection export failed.')
        settings = timeline.GetSetting() or {}
        rate = fps(timeline.GetSetting('timelineFrameRate'))
        start = integer(timeline.GetStartFrame())
        errors = []
        counts = {k: timeline.GetTrackCount(k) for k in ('video', 'audio', 'subtitle')}
        if counts['video'] != 1 or counts['audio'] > 1 or counts['subtitle']:
            errors.append('Only V1 and optional A1 are supported; no extra or subtitle tracks.')
        track_data = []
        for kind in ('video', 'audio'):
            for index in range(1, counts[kind] + 1):
                enabled = timeline.GetIsTrackEnabled(kind, index)
                locked = timeline.GetIsTrackLocked(kind, index)
                track_data.append({'kind': kind, 'index': index, 'name': timeline.GetTrackName(kind, index),
                                   'subtype': timeline.GetTrackSubType(kind, index), 'enabled': enabled, 'locked': locked})
                if not enabled or locked:
                    errors.append('Disabled/locked tracks are unsupported.')
                if kind == 'audio':
                    voice = timeline.GetVoiceIsolationState(index) or {}
                    if voice.get('isEnabled'):
                        errors.append('Track voice isolation is unsupported.')
        if timeline.GetMarkers():
            errors.append('Timeline markers need a preservation-capable editing path.')
        try:
            otio = inspect_otio(read_json(export_path), rate)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            otio = None
        videos, audios = items(timeline, 'video'), items(timeline, 'audio')
        clips, media_map, matched_audio = [], {}, set()
        cursor = 0
        for index, item in enumerate(sorted(videos, key=lambda x: x.GetStart())):
            item_id = item.GetUniqueId()
            errors.extend(f'{item_id}: {e}' for e in safety(item, 'video'))
            media = item.GetMediaPoolItem()
            if not media:
                errors.append(f'{item_id}: generated/nested clip without ordinary media')
                continue
            properties = media.GetClipProperty() or {}
            source_path = properties.get('File Path', '')
            if not properties.get('Video Codec') or any(t in str(properties.get('Type', '')).lower() for t in ('compound', 'multicam', 'timeline', 'fusion', 'still')):
                errors.append(f'{item_id}: nonordinary video media')
            try:
                identity = file_identity(source_path)
                source_rate = fps(properties['FPS'])
                first, end = integer(item.GetStart()), integer(item.GetEnd())
                source_first, source_end = integer(item.GetSourceStartFrame()), integer(item.GetSourceEndFrame())
                duration = integer(item.GetDuration())
                if end - first != duration or first - start < cursor:
                    raise ValueError('Overlapping/subframe/invalid clip placement.')
                if source_rate != rate:
                    raise ValueError(f'Mixed rates ({source_rate} vs {rate}); rate-conform is not verified.')
                if source_end - source_first not in (duration, duration - 1):
                    raise ValueError('Source span indicates retiming or unknown source-frame conventions.')
                frame_count = integer(properties['Frames'])
                if not 0 <= source_first < source_first + duration <= frame_count:
                    raise ValueError('Source bounds invalid (subclips/changed clip interpretation are unsupported).')
                origin = '0'
                if otio:
                    row = otio['Video'][index]
                    if (row['start_frame'], row['end_frame'], row['source_start_frame']) != (first - start, end - start, source_first):
                        raise ValueError('API/OTIO source or timeline coordinates disagree.')
                    if local_url(row['target_url']) != identity['path'] or row['source_frames'] != frame_count:
                        raise ValueError('API/OTIO media identity or available source bounds disagree.')
                    origin = row['source_origin_seconds']
                paired = [a for a in audios if signature(a) == signature(item)]
                if len(paired) > 1:
                    raise ValueError('Multiple audio partners are unsupported.')
                mapping = None
                if paired:
                    audio = paired[0]
                    matched_audio.add(audio.GetUniqueId())
                    errors.extend(f'{audio.GetUniqueId()}: {e}' for e in safety(audio, 'audio'))
                    if integer(audio.GetDuration()) != duration or integer(audio.GetSourceEndFrame()) != source_end:
                        raise ValueError('Split audio/video source ranges are unsupported.')
                    links = {a.GetUniqueId() for a in item.GetLinkedItems() or []}
                    if audio.GetUniqueId() not in links:
                        raise ValueError('Audio/video pair is unlinked.')
                    if {a.GetUniqueId() for a in audio.GetLinkedItems() or []} != {item_id} or links != {audio.GetUniqueId()}:
                        raise ValueError('Nontrivial audio/video link group is unsupported.')
                    mapping = audio_mapping(media)
                    raw_mapping = audio.GetSourceAudioChannelMapping()
                    import json
                    actual_mapping = json.loads(raw_mapping) if isinstance(raw_mapping, str) else raw_mapping
                    if actual_mapping != mapping:
                        raise ValueError('Timeline/source audio channel mapping differs.')
                clips.append({'clip_id': item_id, 'name': item.GetName(), 'media_id': media.GetUniqueId(),
                              'source_path': identity['path'], 'source_identity': identity,
                              'source_fps': str(source_rate), 'source_frames': frame_count,
                              'source_timecode': properties.get('Start TC', ''), 'source_origin_seconds': origin,
                              'source_start_frame': source_first, 'source_end_frame_raw': source_end,
                              'start_frame': first - start, 'end_frame': end - start,
                              'has_audio': bool(paired), 'audio_mapping': mapping,
                              'properties': item.GetProperty() or {},
                              'audio_properties': paired[0].GetProperty() if paired else None})
                media_map[media.GetUniqueId()] = media
                cursor = end - start
            except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
                errors.append(f'{item_id}: {exc}')
        if len(matched_audio) != len(audios):
            errors.append('Independent/overlapping audio or music tracks are unsupported.')
        if otio:
            if len(otio['Video']) != len(videos) or len(otio['Audio']) != len(audios):
                errors.append('OTIO/API clip counts differ.')
            audio_rows = sorted(audios, key=lambda a: a.GetStart())
            for audio, row in zip(audio_rows, otio['Audio']):
                if (integer(audio.GetStart()) - start, integer(audio.GetEnd()) - start,
                    integer(audio.GetSourceStartFrame())) != (row['start_frame'], row['end_frame'], row['source_start_frame']):
                    errors.append('OTIO/API audio coordinates disagree.')
            duration = otio['duration_frames']
        else:
            duration = max((integer(i.GetEnd()) - start for i in videos + audios), default=0)
        raw_end = integer(timeline.GetEndFrame())
        if raw_end - start not in (duration, duration - 1):
            errors.append('Timeline end disagrees with OTIO duration.')
        snapshot = {'schema_version': 1, 'environment': self.environment(),
                    'project_id': self.project.GetUniqueId(), 'project_name': self.project.GetName(),
                    'timeline_id': timeline.GetUniqueId(), 'timeline_name': timeline.GetName(),
                    'fps': str(rate), 'start_frame': start, 'end_frame_raw': raw_end,
                    'start_timecode': timeline.GetStartTimecode(), 'duration_frames': duration,
                    'project_settings': self.project.GetSetting() or {}, 'timeline_settings': settings,
                    'tracks': track_data, 'clips': clips, 'limitations': sorted(set(errors)),
                    'requires_human_plain_timeline_check': True,
                    'audit_note': 'API/OTIO cannot prove absence of all grades, OFX, transitions omitted '
                                  'by export, dynamic zoom, keyframes or Fairlight processing. Confirm in Studio.',
                    'export_path': str(export_path)}
        snapshot['fingerprint'] = fingerprint(snapshot)
        return snapshot, media_map

    def unique_name(self, base):
        names = {self.project.GetTimelineByIndex(i).GetName()
                 for i in range(1, self.project.GetTimelineCount() + 1)}
        name = f'{base} - {token()}'
        while name in names:
            name = f'{base} - {token()}'
        return name

    def duplicate(self, name):
        existing = {self.project.GetTimelineByIndex(i).GetUniqueId()
                    for i in range(1, self.project.GetTimelineCount() + 1)}
        result = checked(self.timeline.DuplicateTimeline(name), 'Could not duplicate timeline.')
        if result.GetUniqueId() in existing:
            raise RuntimeError('Duplicate returned an existing timeline; no clips touched.')
        return result

    def assert_selected(self, timeline):
        self.assert_current()
        selected = checked(self.project.GetCurrentTimeline(), 'Timeline closed during operation.')
        if selected.GetUniqueId() != timeline.GetUniqueId():
            raise RuntimeError('Selected timeline changed during operation; stopped.')

    def calibrate(self, snapshot, media_map, output):
        """Create an isolated probe and measure API conventions; retain it for review."""
        if snapshot['limitations']:
            raise ValueError('Calibration requires an ordinary supported timeline.')
        clip = next((c for c in snapshot['clips'] if c['source_frames'] >= 60), None)
        if clip is None:
            raise ValueError('Calibration needs at least 60 source frames.')
        self.assert_current()
        original = self.timeline
        self.assert_selected(original)
        if Path(output).exists():
            raise ValueError('Calibration contract output exists; use a new path.')
        name = self.unique_name('Agent API calibration')
        probe = self.duplicate(name)
        if probe.GetUniqueId() == original.GetUniqueId():
            raise RuntimeError('Duplicate returned original timeline; no clips touched.')
        result = {'status': 'failed', 'timeline_name': name, 'timeline_id': probe.GetUniqueId(),
                  'environment': self.environment()}
        try:
            checked(self.project.SetCurrentTimeline(probe), 'Could not select probe.')
            old = items(probe, 'video') + items(probe, 'audio')
            if old:
                checked(probe.DeleteClips(old, False), 'Could not clear isolated probe.')
            if items(probe, 'video') or items(probe, 'audio'):
                raise RuntimeError('Probe did not clear completely.')
            start = integer(probe.GetStartFrame())
            expected_position = start + 7
            source_start, source_end, length = 11, 34, 24
            created = []
            kinds = (1, 2) if clip['has_audio'] else (1,)
            for kind in kinds:
                self.assert_selected(probe)
                appended = checked(self.pool.AppendToTimeline([{'mediaPoolItem': media_map[clip['media_id']],
                    'startFrame': source_start, 'endFrame': source_end, 'mediaType': kind,
                    'trackIndex': 1, 'recordFrame': expected_position}]), 'Probe append failed.')
                created.extend(appended)
            videos, audios = items(probe, 'video'), items(probe, 'audio')
            if len(videos) != 1 or len(audios) != (1 if clip['has_audio'] else 0):
                raise RuntimeError('Probe produced unexpected clip/track counts.')
            ends = set()
            for item in created:
                if (integer(item.GetStart()), integer(item.GetEnd()), integer(item.GetDuration()),
                    integer(item.GetSourceStartFrame())) != (expected_position, expected_position + length, length, source_start):
                    raise RuntimeError('API frame conventions differ from the supported inclusive append / '
                                       'exclusive timeline / file-relative source contract. Probe retained.')
                ends.add(integer(item.GetSourceEndFrame()))
            if len(ends) != 1 or next(iter(ends)) not in (source_end, source_end + 1):
                raise RuntimeError('Unrecognized source end convention.')
            if len(created) == 2:
                checked(probe.SetClipsLinked(created, True), 'Probe linking failed.')
                if {x.GetUniqueId() for x in videos[0].GetLinkedItems() or []} != {audios[0].GetUniqueId()}:
                    raise RuntimeError('Probe audio/video link readback failed.')
            end_bias = integer(probe.GetEndFrame()) - (expected_position + length)
            if end_bias not in (-1, 0):
                raise RuntimeError('Unknown timeline end convention.')
            result.update(status='passed', append_end='inclusive', record_frame='absolute_timeline',
                          source_frame='file_relative', source_end_bias=next(iter(ends)) - (source_end + 1),
                          timeline_end_bias=end_bias, tested_audio=clip['has_audio'],
                          source_media_id=clip['media_id'], source_identity=clip['source_identity'],
                          observed_duration_frames=length)
        except Exception as exc:
            result['error'] = str(exc)
            write_json(output, result)
            raise
        finally:
            checked(self.project.SetCurrentTimeline(original), 'Could not restore original selection; select it manually.')
        write_json(output, result)
        return result

    def apply(self, snapshot, plan, media_map, contract, job, name):
        if contract.get('status') != 'passed' or contract.get('environment') != self.environment():
            raise ValueError('Missing/stale Studio calibration for this project, version, documentation and FPS.')
        if any(s.get('has_audio') for s in plan['segments']) and not contract.get('tested_audio'):
            raise ValueError('Run calibration on a timeline clip with embedded audio first.')
        if plan['segments'][-1]['kind'] == 'gap':
            raise ValueError('Direct API cannot represent a trailing empty gap. Use export-otio fallback.')
        self.assert_current()
        original = self.timeline
        self.assert_selected(original)
        name = self.unique_name(name or snapshot['timeline_name'] + ' - Edit')
        output = self.duplicate(name)
        if output.GetUniqueId() == original.GetUniqueId():
            raise RuntimeError('Duplicate returned original timeline; no changes made.')
        result = {'status': 'failed', 'timeline_name': name, 'timeline_id': output.GetUniqueId(),
                  'original_timeline_id': original.GetUniqueId(), 'plan': plan,
                  'validation': 'not completed'}
        path = Path(job) / 'result.json'
        try:
            checked(self.project.SetCurrentTimeline(output), 'Could not select output timeline.')
            old = items(output, 'video') + items(output, 'audio')
            if old:
                checked(output.DeleteClips(old, False), 'Could not clear new timeline.')
            if items(output, 'video') or items(output, 'audio'):
                raise RuntimeError('Output clear did not remove all original items.')
            start = integer(output.GetStartFrame())
            if start != snapshot['start_frame'] or output.GetStartTimecode() != snapshot['start_timecode']:
                raise RuntimeError('Duplicated timeline changed start timecode.')
            for segment in plan['segments']:
                if segment['kind'] == 'gap':
                    continue
                created = []
                for kind in ((1, 2) if segment['has_audio'] else (1,)):
                    self.assert_selected(output)
                    created.extend(checked(self.pool.AppendToTimeline([{
                        'mediaPoolItem': media_map[segment['media_id']], 'mediaType': kind,
                        'startFrame': segment['source_start_frame'],
                        'endFrame': segment['source_end_frame'] - 1, 'trackIndex': 1,
                        'recordFrame': start + segment['output_start_frame']}]), 'Append failed.'))
                if segment['has_audio']:
                    checked(output.SetClipsLinked(created, True), 'Audio/video linking failed.')
            result['validation'] = self.verify(output, snapshot, plan, contract)
            # Confirm the original still matches the input after editing the isolated copy.
            self.timeline = original
            original_now, _ = self.inspect(Path(job) / 'original-after.otio')
            if original_now['fingerprint'] != snapshot['fingerprint']:
                raise RuntimeError('Original changed during apply; output retained, delivery stopped.')
            checked(self.project.SetCurrentTimeline(output), 'Could not select verified output timeline.')
            result.update(status='passed', duration_frames=plan['duration_frames'],
                          duration_seconds=plan['duration_seconds'], fps=plan['fps'])
            write_json(path, result)
            return result
        except Exception as exc:
            result['error'] = str(exc)
            if not path.exists():
                write_json(path, result)
            checked(self.project.SetCurrentTimeline(original), 'Could not restore original selection.')
            raise

    def verify(self, output, snapshot, plan, contract):
        expected = [s for s in plan['segments'] if s['kind'] == 'clip']
        videos = sorted(items(output, 'video'), key=lambda x: x.GetStart())
        audios = sorted(items(output, 'audio'), key=lambda x: x.GetStart())
        if len(videos) != len(expected) or len(audios) != sum(s['has_audio'] for s in expected):
            raise RuntimeError('Readback clip counts differ from decisions.')
        start = integer(output.GetStartFrame())
        if start != snapshot['start_frame'] or output.GetStartTimecode() != snapshot['start_timecode']:
            raise RuntimeError('Readback start timecode differs.')
        audio_index = 0
        source_clips = {c['clip_id']: c for c in snapshot['clips']}
        for video, segment in zip(videos, expected):
            pair = [video]
            if segment['has_audio']:
                pair.append(audios[audio_index])
                audio_index += 1
            for item in pair:
                observed = (item.GetMediaPoolItem().GetUniqueId(), integer(item.GetStart()) - start,
                            integer(item.GetEnd()) - start, integer(item.GetDuration()),
                            integer(item.GetSourceStartFrame()), integer(item.GetSourceEndFrame()))
                wanted = (segment['media_id'], segment['output_start_frame'],
                          segment['output_start_frame'] + segment['duration_frames'], segment['duration_frames'],
                          segment['source_start_frame'], segment['source_end_frame'] + contract['source_end_bias'])
                if observed != wanted:
                    raise RuntimeError(f'Readback timing/media mismatch: {observed} versus {wanted}.')
            if len(pair) == 2:
                for item, partner in ((pair[0], pair[1]), (pair[1], pair[0])):
                    if {i.GetUniqueId() for i in item.GetLinkedItems() or []} != {partner.GetUniqueId()}:
                        raise RuntimeError('Readback audio/video link mismatch.')
                import json
                mapping = pair[1].GetSourceAudioChannelMapping()
                mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
                if mapping != source_clips[segment['clip_id']]['audio_mapping']:
                    raise RuntimeError('Readback audio channel mapping mismatch.')
        if integer(output.GetEndFrame()) - start != plan['duration_frames'] + contract['timeline_end_bias']:
            raise RuntimeError('Readback total duration differs.')
        if output.GetSetting() != snapshot['timeline_settings'] or self.project.GetSetting() != snapshot['project_settings']:
            raise RuntimeError('Timeline/project settings changed.')
        tracks = [{'kind': kind, 'index': i, 'name': output.GetTrackName(kind, i),
                   'subtype': output.GetTrackSubType(kind, i), 'enabled': output.GetIsTrackEnabled(kind, i),
                   'locked': output.GetIsTrackLocked(kind, i)} for kind in ('video', 'audio')
                  for i in range(1, output.GetTrackCount(kind) + 1)]
        if tracks != snapshot['tracks'] or output.GetTrackCount('subtitle'):
            raise RuntimeError('Track layout/settings changed.')
        return 'API readback passed: media IDs, placements, source in/out, duration, A/V links, audio mapping and settings.'
