"""Pinned downloads. Each archive's SHA-256 is checked before it is unpacked."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
from build import NAMES as BUILD_NAMES
from common import LOCK, ROOT, digest
from integrity import tree_digest


def download(url, sha256, folder):
    """Download into folder (reusing a verified earlier download) and return its path."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    target = folder/url.rsplit('/', 1)[-1]
    if target.is_file() and digest(target) == sha256:
        return target
    print('Downloading', url, flush=True)
    h = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=folder, prefix='.download-', delete=False) as tmp:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                while chunk := response.read(1 << 20):
                    h.update(chunk); tmp.write(chunk)
            if h.hexdigest() != sha256:
                raise RuntimeError(f'Checksum mismatch for {url}; nothing was unpacked')
            os.replace(tmp.name, target)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
    return target


def unpack(archive, folder, top):
    """Unpack archive's single top-level directory `top` to folder/top.
    tarfile's data filter refuses absolute paths, '..' and links leaving the tree."""
    folder = Path(folder); dest = folder/top
    staging = Path(tempfile.mkdtemp(dir=folder, prefix='.unpack-'))
    try:
        with tarfile.open(archive) as t:
            t.extractall(staging, filter='data')
        if sorted(p.name for p in staging.iterdir()) != [top]:
            raise RuntimeError(f'Unexpected layout in {archive.name}')
        os.rename(staging/top, dest)
    finally:
        shutil.rmtree(staging)
    return dest


def runner(folder):
    """The pinned Wine runner, downloaded and fingerprinted if not already present."""
    url = LOCK['runner_archive_url']; top = url.rsplit('/', 1)[-1].removesuffix('.tar.xz')
    dest = Path(folder)/top
    if not dest.exists():
        unpack(download(url, LOCK['runner_archive_sha256'], Path(folder)/'downloads'), folder, top)
    if tree_digest(dest) != LOCK['runner_tree_sha256']:
        raise RuntimeError(f'{dest} does not match the pinned runner; move it aside and rerun')
    return dest


def dxvk(folder):
    """The pinned DXVK release's 64-bit DLL folder."""
    url = LOCK['dxvk_archive_url']; top = url.rsplit('/', 1)[-1].removesuffix('.tar.gz')
    dest = Path(folder)/top
    if not dest.exists():
        unpack(download(url, LOCK['dxvk_archive_sha256'], Path(folder)/'downloads'), folder, top)
    for name, h in LOCK['dxvk'].items():
        if digest(dest/'x64'/name) != h:
            raise RuntimeError(f'{dest} does not match the pinned DXVK; move it aside and rerun')
    return dest/'x64'


def helpers(folder, build=ROOT/'build'):
    """Install the pinned prebuilt helpers into build/ after checking every file."""
    pin = LOCK.get('helpers')
    if not pin:
        raise RuntimeError('No prebuilt helpers are pinned in this version; run build instead')
    archive = download(pin['url'], pin['sha256'], Path(folder)/'downloads')
    # Stage beside build/ so the final moves stay on one filesystem.
    staging = Path(tempfile.mkdtemp(dir=build.parent, prefix='.helpers-'))
    try:
        with tarfile.open(archive) as t:
            names = [m.name for m in t.getmembers()]
            licenses = [n for n in names if n.startswith('licenses/') and n.count('/') == 1]
            if sorted(set(names)-set(licenses)) != sorted(['manifest.json', *BUILD_NAMES]) or \
                    len(set(names)) != len(names) or not all(m.isfile() for m in t.getmembers()):
                raise RuntimeError('Unexpected files in the prebuilt helper archive')
            t.extractall(staging, filter='data')
        manifest = json.loads((staging/'manifest.json').read_text())
        if sorted(manifest) != sorted(BUILD_NAMES) or any(digest(staging/n) != h for n, h in manifest.items()):
            raise RuntimeError('Prebuilt helper files do not match their manifest')
        (build/'licenses').mkdir(parents=True, exist_ok=True)
        for name in [*BUILD_NAMES, 'manifest.json', *licenses]:
            os.replace(staging/name, build/name)
    finally:
        shutil.rmtree(staging)
    print('Prebuilt helpers', pin['version'], 'installed in', build, flush=True)
