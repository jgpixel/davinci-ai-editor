"""Filesystem helpers shared by the command line tools (no Resolve imports)."""
import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data, *, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w' if overwrite else 'x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write('\n')


def token():
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]


def file_identity(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'Expected a local media file: {path}')
    stat = path.stat()
    return {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'ctime_ns': stat.st_ctime_ns}
