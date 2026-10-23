"""Ensure added private files cannot silently enter a verified distribution."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verify_hosted import verify


class IntegrationManifestTests(unittest.TestCase):
    def test_unlisted_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'app.py').write_bytes(b'# fixture\n')
            metadata = {'scope': 'test fixture', 'files': {'app.py': {
                'bytes': 10, 'sha256': hashlib.sha256(b'# fixture\n').hexdigest()}}}
            (root / 'INTEGRATION_MANIFEST.json').write_text(json.dumps(metadata))
            (root / 'INTEGRATION_MANIFEST.sha256').write_text(hashlib.sha256((root / 'INTEGRATION_MANIFEST.json').read_bytes()).hexdigest())
            self.assertEqual(verify(root)['verified_files'], 1)
            (root / '.env').write_text('SYNTHETIC_PRIVATE_FIXTURE=do-not-ship')
            with self.assertRaises(ValueError):
                verify(root)

    def test_modified_declared_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'app.py').write_bytes(b'# fixture\n')
            metadata = {'scope': 'test fixture', 'files': {'app.py': {
                'bytes': 10, 'sha256': hashlib.sha256(b'# fixture\n').hexdigest()}}}
            (root / 'INTEGRATION_MANIFEST.json').write_text(json.dumps(metadata))
            (root / 'INTEGRATION_MANIFEST.sha256').write_text(hashlib.sha256((root / 'INTEGRATION_MANIFEST.json').read_bytes()).hexdigest())
            (root / 'app.py').write_bytes(b'# changed\n')
            with self.assertRaises(ValueError):
                verify(root)


if __name__ == '__main__':
    unittest.main()
