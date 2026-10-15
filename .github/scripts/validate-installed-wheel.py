"""Disposable installed-wheel validation; excluded from the upstream candidate."""
import hashlib
import importlib.metadata
import json
import platform
import sys
import sysconfig
import os
import time
from pathlib import Path

import watchfiles
from watchfiles import _rust_notify
from watchfiles._rust_notify import RustNotify

requested, checkout, fixtures = sys.argv[1:]
assert not Path(watchfiles.__file__).resolve().is_relative_to(Path(checkout).resolve())
assert watchfiles.__version__ == '1.3.0'
assert sys.version_info[:2] == tuple(map(int, requested.rstrip('t').split('.')))
wheel_metadata = importlib.metadata.distribution('watchfiles').read_text('WHEEL')
expected_tag = {'3.10': 'cp310-abi3-', '3.15': 'cp315-abi3-', '3.14t': 'cp314-cp314t-', '3.15t': 'cp315-abi3t-'}[requested]
assert expected_tag in wheel_metadata, wheel_metadata
for artifact_dir in ('wheel-artifacts', 'baseline-dist'):
    artifacts = Path(checkout) / artifact_dir
    print(artifact_dir, json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(artifacts.glob('*.whl'))}, indent=2), flush=True)
if requested == '3.15':
    assert sysconfig.get_config_var('Py_GIL_DISABLED') != 1
    assert sys._is_gil_enabled()
if requested.endswith('t'):
    assert sysconfig.get_config_var('Py_GIL_DISABLED') == 1
    assert not sys._is_gil_enabled()
print(json.dumps({
    'python': sys.version,
    'platform': platform.platform(),
    'machine': platform.machine(),
    'package': watchfiles.__file__,
    'extension': _rust_notify.__file__,
    'wheel_metadata': wheel_metadata,
}, indent=2), flush=True)
# The original smoke incorrectly reused a newly-created file for immediate edits.
# FSEvents may preserve its Created flag; PollWatcher compares whole-second mtimes.
# Match the project's own preexisting-file modification/deletion test seam instead.
for force_polling in (False, True):
    root = (Path(fixtures) / ('polling' if force_polling else 'native')).resolve()
    created = root / 'installed-wheel-new.txt'
    modified = root / 'a.txt'
    deleted = root / 'b.txt'
    assert modified.is_file() and deleted.is_file()
    # Deliberately establish a different whole-second timestamp, not a timing retry.
    os.utime(modified, (1_600_000_000, 1_600_000_000))
    with RustNotify([str(root)], True, force_polling, 25, True, False) as watcher:
        backend = repr(watcher)
        assert backend.startswith('RustNotify(Poll(' if force_polling else 'RustNotify(Recommended('), backend
        print(backend, flush=True)
        operations = (
            (1, created, lambda: created.write_text('created')),
            (2, modified, lambda: modified.write_text('modified with different content and size')),
            (3, deleted, deleted.unlink),
        )
        for change, path, operation in operations:
            operation()
            changes = watcher.watch(200, 25, 5000, None)
            print(force_polling, change, changes, flush=True)
            assert isinstance(changes, set) and (change, str(path)) in changes, changes
if requested == '3.15':
    assert sysconfig.get_config_var('Py_GIL_DISABLED') != 1
    assert sys._is_gil_enabled()
if requested.endswith('t'):
    assert not sys._is_gil_enabled()
print('installed wheel native and polling behavior passed', flush=True)
