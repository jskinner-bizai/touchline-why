"""Read-only hash check of the sealed integration payload; no provider imports."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify(root):
    root = Path(root).resolve()
    manifest_path = root / 'INTEGRATION_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    declared = (root / 'INTEGRATION_MANIFEST.sha256').read_text(encoding='ascii').split()[0]
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != declared:
        raise ValueError('Integration manifest hash changed')
    expected_files = {*manifest['files'], 'INTEGRATION_MANIFEST.json', 'INTEGRATION_MANIFEST.sha256'}
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob('*')
                    if path.is_file() and path.relative_to(root).parts[0] != '.git'}
    if actual_files != expected_files:
        raise ValueError('Integration package membership changed')
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ':' in name or '\\' in name or any(part in {'', '.', '..'} for part in name.split('/')):
            raise ValueError('Unsafe integration path')
        path = root / name
        if (any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root))
                or not path.resolve().is_relative_to(root) or path.stat().st_size != expected['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']):
            raise ValueError('Integration payload changed: ' + name)
    return {'verified_files': len(manifest['files']), 'scope': manifest['scope'], 'publicly_deployed': False, 'new_model_calls': 0}


def main():
    print(json.dumps(verify(Path(__file__).resolve().parent)))


if __name__ == '__main__':
    main()
