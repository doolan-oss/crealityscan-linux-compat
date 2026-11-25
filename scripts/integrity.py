"""Host-side integrity baselines, never mounted into the application sandbox."""
import hashlib
import json
import os
from pathlib import Path
import stat
from exports import EXPORTS_MOUNT

# Beside setup's data folder, never inside a data_dir, so a re-cloned or moved
# checkout still recognises its installs. Installs made before this used the
# checkout's .local-trust/, which is still read.
TRUST_ROOT = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share') / 'crealityscan-linux' / 'trust'
LEGACY_TRUST_ROOT = Path(__file__).resolve().parents[1] / '.local-trust'


def tree_manifest(root):
    """Hash every regular file and link; reject external links and special files."""
    root = Path(root).resolve()
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(parent) / name
            mode = p.lstat().st_mode
            key = p.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                if not p.resolve().is_relative_to(root):
                    raise RuntimeError(f'External dependency symlink: {key}')
                result[key] = ['link', os.readlink(p)]
            elif stat.S_ISREG(mode):
                with p.open('rb') as f:
                    result[key] = ['file', hashlib.file_digest(f, 'sha256').hexdigest()]
            elif not stat.S_ISDIR(mode):
                raise RuntimeError(f'Special file in dependency: {key}')
    return result


def tree_digest(root):
    encoded = json.dumps(tree_manifest(root), sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def installation_path(c):
    key = hashlib.sha256(str(c['data_dir']).encode()).hexdigest()
    legacy = LEGACY_TRUST_ROOT / (key + '.json')
    current = TRUST_ROOT / (key + '.json')
    return legacy if legacy.exists() and not current.exists() else current


def code_manifest(prefix):
    result = {}
    # All installed executable code, including Wine system DLLs and both SDK copies.
    # dosdevices intentionally contains Wine drive links; do not traverse it.
    root = Path(prefix) / 'drive_c'
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError('drive_c must be a real directory inside the owned prefix')
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            p = Path(parent) / name
            if p.is_symlink():
                # Wine creates user-folder links. They must remain inside the prefix,
                # except folders pointing at the sandbox-only exports mount.
                target = os.readlink(p)
                if target == EXPORTS_MOUNT or target.startswith(EXPORTS_MOUNT + '/'):
                    continue
                if not p.resolve().is_relative_to(prefix):
                    raise RuntimeError(f'External prefix directory link: {p}')
        for name in files:
            p = Path(parent) / name
            if p.suffix.lower() not in {'.exe', '.dll', '.so', '.drv', '.ocx'}:
                continue
            if p.is_symlink() or not p.is_file():
                raise RuntimeError(f'Linked/nonregular executable: {p}')
            with p.open('rb') as f:
                result[str(p.relative_to(prefix))] = hashlib.file_digest(f, 'sha256').hexdigest()
    required = 'drive_c/Program Files/CrealityScan/'
    if not all(required + n in result for n in ('CrealityScan.exe', 'pikacam.dll', 'mf.dll')):
        raise RuntimeError('Required application code missing')
    return result


def save_installation(c, build):
    p = installation_path(c)
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with p.open('x') as f:
        json.dump({'schema': 2, 'files': code_manifest(c['prefix']), 'build': build}, f, indent=2)
        f.write('\n')


def verify_installation(c, build):
    meta = json.loads(installation_path(c).read_text())
    if meta.get('schema') != 2 or meta.get('build') != build:
        raise RuntimeError('CrealityScan was installed with other helper programs than those in build/. '
                           'Run "python3 scripts/creality.py setup" to install it again; your scans are kept.')
    if not meta.get('files') or meta['files'] != code_manifest(c['prefix']):
        raise RuntimeError('Installed executable inventory or content changed')
    return meta['files']
