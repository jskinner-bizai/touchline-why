"""Verify exactly the shipped files before installation; stdlib only, no model."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def verify(root: Path) -> dict:
    manifest = json.loads((root / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    if manifest['mode'] not in {'recorded-only', 'recorded-default'} or manifest['newModelCalls'] != 0:
        raise ValueError('Unexpected execution mode')
    if manifest['mode'] == 'recorded-default' and manifest.get('liveProviderEnabledByDefault') is not False:
        raise ValueError('Optional live route must be disabled by default')
    files = manifest['files']
    expected = {*files, 'PACKAGE_MANIFEST.json'}
    # Source clones add Git's local bookkeeping. It is never a shipped file.
    # Every other source/runtime file still participates in exact membership.
    ignore_git = manifest.get('bundleKind') == 'source'
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not (ignore_git and p.relative_to(root).parts[0] == '.git')}
    if actual != expected:
        raise ValueError(f'Package membership changed: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    for name, expected_file in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or any(part in {'', '.', '..'} for part in name.split('/')) or '\\' in name or ':' in name:
            raise ValueError('Unsafe package path')
        path = root / name
        if any(candidate.is_symlink() for candidate in (path, *path.parents) if candidate.is_relative_to(root)) or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Unsafe package link: {name}')
        if path.stat().st_size != expected_file['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected_file['sha256']:
            raise ValueError(f'Package file changed: {name}')
    for name, expected_digest in manifest.get('historicalReceiptSha256', {}).items():
        if name not in files or files[name]['sha256'] != expected_digest:
            raise ValueError('Historical receipt identity changed')
    wheel_count = sum(name.startswith('wheelhouse/') for name in files)
    kind = manifest.get('bundleKind', 'judge')
    if manifest['mode'] == 'recorded-default' and (kind not in {'judge', 'source'} or wheel_count != (19 if kind == 'judge' else 0)):
        raise ValueError('Unexpected bundle kind or wheel count')
    return {'verifiedFiles': len(files), 'mode': manifest['mode'], 'bundleKind': kind, 'modelCalls': 0}


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    print(json.dumps(verify(root), indent=2))
