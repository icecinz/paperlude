#!/usr/bin/env python3
"""Fetch the separately hosted, content-verified giraffe demo bundle."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_members(bundle):
    """Reject paths and file types that could escape the demo directory."""
    seen = set()
    files = set()
    for member in bundle.infolist():
        name = member.filename
        path = PurePosixPath(name)
        if (not name or '\\' in name or '\x00' in name or path.is_absolute()
                or '..' in path.parts or ':' in name
                or str(path) != name.rstrip('/')):
            raise ValueError(f'Unsafe ZIP path: {name!r}')
        if name in seen:
            raise ValueError(f'Duplicate ZIP path: {name!r}')
        seen.add(name)
        if stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError(f'ZIP links are not accepted: {name!r}')
        allowed = (name == 'examples/giraffe/source.mov'
                   or name.startswith('examples/giraffe/baseline/')
                   or name.rstrip('/') in {'examples', 'examples/giraffe', 'examples/giraffe/baseline'})
        if not allowed:
            raise ValueError(f'Unexpected bundle member: {name!r}')
        if not member.is_dir():
            files.add(name)
    if 'examples/giraffe/source.mov' not in files or not any(n.startswith('examples/giraffe/baseline/') for n in files):
        raise ValueError('Bundle is missing its source video or baseline')


def extract_archive(archive, destination, expected_sha256):
    archive, destination = Path(archive), Path(destination)
    if sha(archive) != expected_sha256:
        raise ValueError('Demo ZIP SHA-256 mismatch')
    case = destination / 'examples/giraffe'
    if (case / 'source.mov').exists() or (case / 'baseline').exists():
        raise ValueError('Demo input already exists; refusing to overwrite it')
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        validate_members(bundle)
        with tempfile.TemporaryDirectory(prefix='.paperlude-extract-', dir=destination) as folder:
            staging = Path(folder)
            bundle.extractall(staging)
            case.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / 'examples/giraffe/source.mov'), case / 'source.mov')
            shutil.move(str(staging / 'examples/giraffe/baseline'), case / 'baseline')


def main():
    parser = argparse.ArgumentParser(description='Fetch the verified Paperlude giraffe demo')
    parser.add_argument('--archive', type=Path, help='Use an already downloaded ZIP instead of the network')
    parser.add_argument('--destination', type=Path, default=ROOT, help='Extraction root; defaults to this repository')
    args = parser.parse_args()
    settings = json.loads((ROOT / 'config/demo-release.json').read_text())
    expected = settings['sha256']
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Release metadata does not contain a SHA-256 yet')
    if args.archive:
        extract_archive(args.archive, args.destination, expected)
    else:
        with tempfile.TemporaryDirectory(prefix='paperlude-download-') as folder:
            archive = Path(folder) / 'demo.zip'
            urllib.request.urlretrieve(settings['url'], archive)
            extract_archive(archive, args.destination, expected)
    print(f'Demo verified and extracted into {args.destination / "examples/giraffe"}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f'Stopped: {exc}', file=sys.stderr)
        sys.exit(1)
