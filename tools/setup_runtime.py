#!/usr/bin/env python3
"""Install the pinned external runtime; never bundle third-party model weights."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description='Set up the pinned Paperlude demo runtime')
    parser.add_argument('--python', default=sys.executable, help='Python 3.10+ interpreter; tested on 3.12.13')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan without installing or downloading')
    args = parser.parse_args()
    settings = json.loads((ROOT / 'config/runtime.json').read_text())
    runtime = ROOT / '.runtime'
    if runtime.is_symlink():
        raise ValueError('.runtime is a symlink; refusing to alter a shared/local environment')
    python = runtime / '.venv/bin/python'
    sam = runtime / 'vendor/sam2'
    model = runtime / 'models' / settings['model_filename']
    plan = {
        'interpreter': args.python,
        'venv': str(runtime / '.venv'),
        'dependencies': 'requirements.txt',
        'sam2_repository': settings['sam2_repository'],
        'sam2_commit': settings['sam2_commit'],
        'model_url': settings['model_url'],
        'model_sha256': settings['model_sha256'],
        'cuda_extension': False,
        'note': 'Network access is required. FFmpeg and ffprobe must be installed separately. Fresh installs are platform-dependent.'
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    if not shutil.which('git'):
        raise ValueError('git is required')
    version = json.loads(subprocess.check_output([args.python, '-c', 'import sys,json;print(json.dumps(list(sys.version_info[:3])))'], text=True))
    if tuple(version[:2]) < (3, 10):
        raise ValueError('Python 3.10+ is required; use python3.12 tools/setup_runtime.py or --python python3.12')
    runtime.mkdir(exist_ok=True)
    if not python.exists():
        subprocess.run([args.python, '-m', 'venv', str(runtime / '.venv')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    sam.parent.mkdir(exist_ok=True)
    if not sam.exists():
        subprocess.run(['git', 'clone', '--no-checkout', settings['sam2_repository'], str(sam)], check=True)
        subprocess.run(['git', '-C', str(sam), 'checkout', settings['sam2_commit']], check=True)
    commit = subprocess.check_output(['git', '-C', str(sam), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != settings['sam2_commit']:
        raise ValueError('Existing SAM2 checkout is at a different commit; keep it or move it aside explicitly before retrying')
    env = os.environ.copy()
    env['SAM2_BUILD_CUDA'] = '0'
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-build-isolation', '--no-deps', '-e', str(sam)], env=env, check=True)
    model.parent.mkdir(exist_ok=True)
    if model.exists():
        if sha(model) != settings['model_sha256']:
            raise ValueError('Existing model has the wrong SHA-256; not overwriting it')
    else:
        partial = model.with_suffix('.download')
        try:
            urllib.request.urlretrieve(settings['model_url'], partial)
            if sha(partial) != settings['model_sha256']:
                raise ValueError('Downloaded model SHA-256 mismatch')
            partial.replace(model)
        finally:
            partial.unlink(missing_ok=True)
    print('Runtime ready. Run: python3 tools/paperlude.py doctor')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'Stopped: {exc}', file=sys.stderr)
        sys.exit(1)
