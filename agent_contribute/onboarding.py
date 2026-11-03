"""Offline maintainer templates and bounded validation; no policy authority."""
import hashlib
import json
import os
from pathlib import Path
import stat

from . import core, tipjar


def template(status):
    """Return valid, editable source text for an explicitly chosen state."""
    if status not in ('welcome', 'closed'):
        raise core.ProtocolError('usage', 'Choose an explicit welcome or closed status')
    manifest = {
        'schema_version': '0.1',
        'status': status,
        'wanted': (['EDIT before publishing: name a small documentation improvement or bug fix you want']
                   if status == 'welcome' else ['No agent contributions requested while this jar is closed']),
        'boundaries': [
            'Read CONTRIBUTING.md and applicable repository policies before choosing work',
            'Agree the specific issue and scope with a maintainer before starting',
            'Obtain separate human authorization for local execution and publication',
        ],
    }
    text = json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    tipjar.parse_manifest(text.encode('utf-8'))
    return text


def init_report(path, text):
    """Describe the exact template bytes written through CLI exclusive creation."""
    data = text.encode('utf-8')
    manifest = tipjar.parse_manifest(data)
    return {'output': str(path), 'state': manifest['status'], 'sha256': hashlib.sha256(data).hexdigest(),
            'notice': tipjar.NOTICE,
            'next_steps': [
                'Edit wanted and boundaries to match your actual contribution policy; remove placeholder text',
                'Run tipjar jar-check on the edited file before reviewing it for publication',
                'If adopting, place the reviewed file at the repository root as .tipjar.json',
                'State restrictions in CONTRIBUTING.md too; older clients do not enforce jars',
            ]}


def jar_check(path):
    """Check one bounded regular local file; never return its untrusted contents."""
    try:
        # Nonblocking open avoids hanging on a FIFO; fstat checks the opened object.
        if Path(path).is_symlink():
            raise OSError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError
            data = handle.read(tipjar.MAX_BYTES + 1)
    except OSError:
        raise core.ProtocolError('file_error', 'Cannot read a regular local Tipjar file') from None
    manifest = tipjar.parse_manifest(data)
    return {'path': str(path), 'state': manifest['status'], 'sha256': hashlib.sha256(data).hexdigest(),
            'valid': True, 'notice': tipjar.NOTICE}
