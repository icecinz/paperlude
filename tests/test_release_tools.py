"""Checks that protect the demo's input binding and extraction boundary."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = load('paperlude_entry', 'paperlude.py')
fetch = load('paperlude_fetch', 'fetch_demo.py')


class SegmentTests(unittest.TestCase):
    def test_continuous_plan_and_keyframe_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'segments.json').write_text(json.dumps([
                {'start': 0, 'end': 2, 'key': 1},
                {'start': 2, 'end': 5, 'key': 3}]))
            self.assertEqual(entry.check_segments(path, 5)['keys'], [1, 3])
            (path / 'segments.json').write_text(json.dumps([
                {'start': 0, 'end': 2, 'key': 2}]))
            with self.assertRaises(ValueError):
                entry.check_segments(path, 2)

    def test_gap_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'segments.json').write_text(json.dumps([
                {'start': 0, 'end': 2, 'key': 1},
                {'start': 3, 'end': 5, 'key': 3}]))
            with self.assertRaises(ValueError):
                entry.check_segments(path, 5)

    def test_changed_engine_fingerprint_is_detectable(self):
        fp = entry.read(ROOT / 'config/giraffe.fingerprints.json')
        for filename, expected in fp['engine_files'].items():
            self.assertEqual(entry.sha(ROOT / 'tools/core' / filename), expected)


class BundleTests(unittest.TestCase):
    @staticmethod
    def bundle(extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as bundle:
            bundle.writestr('examples/giraffe/source.mov', b'video')
            bundle.writestr('examples/giraffe/baseline/segments.json', '[]')
            if extra:
                bundle.writestr(*extra)
        stream.seek(0)
        return stream

    def test_traversal_is_rejected_before_extraction(self):
        with zipfile.ZipFile(self.bundle(('../escape', 'bad'))) as bundle:
            with self.assertRaises(ValueError):
                fetch.validate_members(bundle)

    def test_symlink_is_rejected(self):
        link = zipfile.ZipInfo('examples/giraffe/baseline/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.bundle((link, '../../outside'))) as bundle:
            with self.assertRaises(ValueError):
                fetch.validate_members(bundle)

    def test_hash_mismatch_and_existing_input_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            archive = path / 'demo.zip'
            archive.write_bytes(self.bundle().read())
            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            destination = path / 'result'
            with self.assertRaises(ValueError):
                fetch.extract_archive(archive, destination, '0' * 64)
            self.assertFalse(destination.exists())
            fetch.extract_archive(archive, destination, expected)
            self.assertEqual((destination / 'examples/giraffe/source.mov').read_bytes(), b'video')
            with self.assertRaises(ValueError):
                fetch.extract_archive(archive, destination, expected)


if __name__ == '__main__':
    unittest.main()
