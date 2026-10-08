from copy import deepcopy
import json
from pathlib import Path
import uuid

from common import file_identity
from otio_io import export_plan
from planning import fingerprint


MAPPING = {'embedded_audio_channels': 2, 'linked_audio': {},
           'track_mapping': {'1': {'channel_idx': [1, 2], 'mute': False, 'type': 'Stereo'}}}


def snapshot(path):
    clips = []
    for occurrence, start, source_start in [('v1', 0, 10), ('v2', 200, 30)]:
        clips.append({'clip_id': occurrence, 'name': 'Repeated source', 'media_id': 'media1',
                      'source_path': str(path), 'source_identity': file_identity(path),
                      'source_fps': '25', 'source_frames': 1000, 'source_timecode': '02:00:00:00',
                      'source_origin_seconds': '7200', 'source_start_frame': source_start,
                      'source_end_frame_raw': source_start + 99, 'start_frame': start,
                      'end_frame': start + 100, 'has_audio': True, 'audio_mapping': deepcopy(MAPPING),
                      'properties': {}, 'audio_properties': {}})
    result = {'schema_version': 1, 'environment': {'product': 'DaVinci Resolve Studio',
              'version': '20.2', 'documentation_sha256': 'doc', 'project_id': 'project1', 'fps': '25'},
              'project_id': 'project1', 'project_name': 'Test', 'timeline_id': 'original',
              'timeline_name': 'Original', 'fps': '25', 'start_frame': 90000, 'end_frame_raw': 90300,
              'start_timecode': '01:00:00:00', 'duration_frames': 300,
              'project_settings': {'timelineFrameRate': '25'}, 'timeline_settings': {'timelineFrameRate': '25'},
              'tracks': [{'kind': k, 'index': 1, 'name': k + ' 1',
                          'subtype': 'stereo' if k == 'audio' else '', 'enabled': True, 'locked': False}
                         for k in ('video', 'audio')], 'clips': clips, 'limitations': [],
              'requires_human_plain_timeline_check': True,
              'audit_note': 'API/OTIO cannot prove absence of all grades, OFX, transitions omitted '
                            'by export, dynamic zoom, keyframes or Fairlight processing. Confirm in Studio.'}
    result['fingerprint'] = fingerprint(result)
    return result


def decisions(snap, ranges=None):
    return {'schema_version': 1, 'coordinate_space': 'timeline_seconds',
            'snapshot_fingerprint': snap['fingerprint'], 'plain_source_rebuild_confirmed': True,
            'ranges': ranges or [{'start': 8, 'end': 10}, {'start': 0, 'end': 2}]}


class Media:
    def __init__(self, path):
        self.path = path
    def GetUniqueId(self): return 'media1'
    def GetClipProperty(self):
        return {'File Path': str(self.path), 'FPS': '25', 'Frames': '1000',
                'Start TC': '02:00:00:00', 'Video Codec': 'h264', 'Type': 'Video + Audio'}
    def GetAudioMapping(self): return json.dumps(MAPPING)


class Item:
    def __init__(self, media, ident, start, source, length, kind='video', source_bias=-1):
        self.media, self.id, self.start, self.source, self.length = media, ident, start, source, length
        self.kind, self.links, self.source_bias = kind, [], source_bias
        self.properties, self.fusion, self.nodes, self.voice = {}, 0, 1, False
    def GetUniqueId(self): return self.id
    def GetMediaPoolItem(self): return self.media
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.length
    def GetDuration(self): return self.length
    def GetSourceStartFrame(self): return self.source
    def GetSourceEndFrame(self): return self.source + self.length + self.source_bias
    def GetName(self): return 'Repeated source'
    def GetClipEnabled(self): return True
    def GetFusionCompCount(self): return self.fusion
    def GetTakesCount(self): return 0
    def GetMarkers(self): return {}
    def GetNodeGraph(self): return self
    def GetNumNodes(self): return self.nodes
    def GetColorGroup(self): return None
    def GetProperty(self): return self.properties
    def GetVoiceIsolationState(self): return {'isEnabled': self.voice}
    def GetLinkedItems(self): return self.links
    def GetSourceAudioChannelMapping(self): return json.dumps(MAPPING)


class Timeline:
    def __init__(self, project, snap, ident='original', name='Original'):
        self.project, self.snap, self.id, self.name = project, snap, ident, name
        self.video, self.audio, self.deleted = [], [], False
        self.extra_video = False
        self.start = snap['start_frame']
        self.settings = deepcopy(snap['timeline_settings'])
        for row in snap['clips']:
            v = Item(project.media, row['clip_id'], self.start + row['start_frame'],
                     row['source_start_frame'], row['end_frame'] - row['start_frame'])
            a = Item(project.media, 'a' + row['clip_id'], v.start, v.source, v.length, 'audio')
            v.links, a.links = [a], [v]
            self.video.append(v)
            self.audio.append(a)
    def GetUniqueId(self): return self.id
    def GetName(self): return self.name
    def GetStartFrame(self): return self.start
    def GetEndFrame(self): return max((i.GetEnd() for i in self.video + self.audio), default=self.start)
    def GetStartTimecode(self): return self.snap['start_timecode']
    def GetSetting(self, key=None): return self.settings.get(key) if key else deepcopy(self.settings)
    def GetTrackCount(self, kind): return 2 if kind == 'video' and self.extra_video else (0 if kind == 'subtitle' else 1)
    def GetTrackName(self, kind, index): return kind + ' 1'
    def GetTrackSubType(self, kind, index): return 'stereo' if kind == 'audio' else ''
    def GetIsTrackEnabled(self, kind, index): return True
    def GetIsTrackLocked(self, kind, index): return False
    def GetVoiceIsolationState(self, index): return {'isEnabled': False}
    def GetMarkers(self): return {}
    def GetItemListInTrack(self, kind, index):
        if index > 1: return []
        return self.video if kind == 'video' else self.audio
    def DuplicateTimeline(self, name):
        if self.project.bad_duplicate: return self
        clone = Timeline(self.project, self.snap, uuid.uuid4().hex, name)
        self.project.timelines.append(clone)
        return clone
    def DeleteClips(self, clips, ripple):
        self.deleted = True
        self.video = [i for i in self.video if i not in clips]
        self.audio = [i for i in self.audio if i not in clips]
        return True
    def SetClipsLinked(self, clips, linked):
        for item in clips:
            item.links = [i for i in clips if i is not item] if linked else []
        return True
    def Export(self, path, kind):
        snap = deepcopy(self.snap)
        rows = []
        for video in sorted(self.video, key=lambda i: i.start):
            row = deepcopy(snap['clips'][0])
            row.update(clip_id=video.id, start_frame=video.start - self.start,
                       end_frame=video.GetEnd() - self.start, source_start_frame=video.source,
                       has_audio=bool(video.links))
            rows.append(row)
        snap['clips'] = rows
        segments, cursor = [], 0
        for row in rows:
            if row['start_frame'] > cursor:
                segments.append({'kind': 'gap', 'duration_frames': row['start_frame'] - cursor})
            segments.append({'kind': 'clip', 'clip_id': row['clip_id'],
                             'duration_frames': row['end_frame'] - row['start_frame'],
                             'source_start_frame': row['source_start_frame'],
                             'source_path': row['source_path'], 'has_audio': row['has_audio']})
            cursor = row['end_frame']
        export_plan({'fps': '25', 'segments': segments}, snap, path, self.name)
        return True


class Project:
    def __init__(self, path):
        self.media, self.timelines = Media(path), []
        self.bad_append, self.bad_duplicate = False, False
        self.original = Timeline(self, snapshot(path))
        self.timelines.append(self.original)
        self.current = self.original
    def GetUniqueId(self): return 'project1'
    def GetName(self): return 'Test'
    def GetCurrentTimeline(self): return self.current
    def GetCurrentProject(self): return self
    def GetMediaPool(self): return self
    def GetSetting(self): return {'timelineFrameRate': '25'}
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, i): return self.timelines[i - 1]
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def AppendToTimeline(self, rows):
        if self.bad_append: return []
        result = []
        for row in rows:
            kind = 'video' if row['mediaType'] == 1 else 'audio'
            item = Item(row['mediaPoolItem'], uuid.uuid4().hex, row['recordFrame'],
                        row['startFrame'], row['endFrame'] - row['startFrame'] + 1, kind)
            (self.current.video if kind == 'video' else self.current.audio).append(item)
            result.append(item)
        return result


class Resolve:
    EXPORT_OTIO = 'OTIO'
    def __init__(self, path): self.project = Project(path)
    def GetProjectManager(self): return self.project
    def GetProductName(self): return 'DaVinci Resolve Studio'
    def GetVersionString(self): return '20.2'
