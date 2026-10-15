"""Disposable qualification using the unchanged upstream test suite and installed wheel."""
import hashlib
import importlib.metadata
import json
import os
import sys
import sysconfig
import zipfile
from pathlib import Path

import pytest
import watchfiles
from watchfiles import _rust_notify

requested, checkout, evidence_dir = sys.argv[1:]
checkout = Path(checkout).resolve()
evidence = Path(evidence_dir).resolve()
assert sys.version_info[:2] == tuple(map(int, requested.rstrip('t').split('.')))
assert watchfiles.__version__ == '1.3.0'
metadata = importlib.metadata.distribution('watchfiles').read_text('WHEEL')
expected = {'3.10': 'cp310-abi3-', '3.14t': 'cp314-cp314t-', '3.15': 'cp315-abi3-', '3.15t': 'cp315-abi3t-'}[requested]
assert expected in metadata, metadata
matching_wheels = []
for wheel in sorted((checkout / 'wheel-artifacts').rglob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        wheel_entry = next(n for n in archive.namelist() if n.endswith('.dist-info/WHEEL'))
        if archive.read(wheel_entry).decode() == metadata:
            matching_wheels.append(wheel)
assert len(matching_wheels) == 1, matching_wheels
selected_wheel = matching_wheels[0]
package_parent = Path(watchfiles.__file__).resolve().parent.parent

def check_mode():
    if requested.endswith('t'):
        assert sysconfig.get_config_var('Py_GIL_DISABLED') == 1
        assert not sys._is_gil_enabled()
    elif requested == '3.15':
        assert sysconfig.get_config_var('Py_GIL_DISABLED') != 1
        assert sys._is_gil_enabled()

def package_provenance():
    result = {}
    for name, module in sorted(sys.modules.copy().items()):
        if name == 'watchfiles' or name.startswith('watchfiles.'):
            path = Path(module.__file__).resolve()
            assert not path.is_relative_to(checkout), (name, str(path))
            assert path.is_relative_to(Path(sys.prefix).resolve()), (name, str(path))
            with zipfile.ZipFile(selected_wheel) as archive:
                payload = archive.read(path.relative_to(package_parent).as_posix())
            assert path.read_bytes() == payload, (name, str(path), str(selected_wheel))
            result[name] = {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return result

def suite_hashes():
    paths = [checkout / 'pyproject.toml'] + sorted((checkout / 'tests').rglob('*'))
    return {str(p.relative_to(checkout)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts}

check_mode()
before = package_provenance()
suite_before = suite_hashes()
artifacts = {str(p.relative_to(checkout)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((checkout / 'wheel-artifacts').rglob('*.whl'))}
print(json.dumps({'python': sys.version, 'wheel_metadata': metadata,
                  'artifact_sha256': artifacts, 'selected_wheel': str(selected_wheel), 'before_package': before,
                  'suite_before_sha256': suite_before}, indent=2), flush=True)
assert Path.cwd().resolve() != checkout
# Import and cache the installed package first; importlib mode does not add source
# directories to sys.path. All original tests, config, timeouts and skips are retained.
result = pytest.main(['--import-mode=importlib', '-c', str(checkout / 'pyproject.toml'),
                      '-vv', '--junitxml', str(evidence / 'junit.xml'), str(checkout / 'tests')])
after = package_provenance()
check_mode()
for name, data in before.items():
    assert after[name] == data, (name, after[name], data)
report = {'pytest_exit': result, 'before_package': before, 'after_package': after,
          'suite_before_sha256': suite_before, 'suite_after_sha256': suite_hashes(),
          'wheel_metadata': metadata, 'selected_wheel': str(selected_wheel), 'artifact_sha256': artifacts}
(evidence / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'pytest_exit': result, 'after_package': after}, indent=2), flush=True)
raise SystemExit(result)
