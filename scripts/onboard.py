"""One-command setup for new users: fetch, configure, install, check, add a menu entry."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from common import LOCK, ROOT, digest, load, owned, release, versions
from exports import default_dir
import fetch
import gpuinfo

UDEV_RULE = ROOT/'config/70-creality-pika.rules'


def data_home():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')


def downloads_dir():
    try:
        out = subprocess.run(['xdg-user-dir', 'DOWNLOAD'], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ''
    return Path(out) if out and Path(out).is_absolute() else Path.home()/'Downloads'


def installer_candidates():
    """CrealityScan*.exe files in Downloads, then home, newest name first."""
    found = []
    for folder in (downloads_dir(), Path.home()):
        try:
            found += sorted((p for p in folder.iterdir() if p.suffix.lower() == '.exe'
                             and 'crealityscan' in p.name.lower() and p.is_file()), reverse=True)
        except OSError:
            continue
    return found


def find_installer():
    """A pinned CrealityScan installer in Downloads or home, matched by checksum.
    Each release is tried in lock order, so the first listed (newest) wins."""
    candidates = [(p, release(p)) for p in installer_candidates()]
    for pinned in LOCK['crealityscan']:
        for p, r in candidates:
            if r is pinned:
                return p
    return None


def detect_gpu():
    """Detect with the system interpreter: its libraries match what the app uses
    (another Python's bundled libdrm can report a generic AMD board name)."""
    system = Path('/usr/bin/python3')
    if not system.exists():
        return gpuinfo.detect()
    out = subprocess.run([str(system), '-I', str(ROOT/'scripts/gpuinfo.py')], capture_output=True, text=True, timeout=60)
    return out.stdout.strip() or None


def desktop_quote(arg):
    """Quote one Exec argument per the Desktop Entry specification."""
    arg = str(arg).replace('%', '%%')
    if not any(ch in arg for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    inner = ''.join('\\'+ch if ch in '"`$\\' else ch for ch in arg)
    return '"' + inner.replace('\\', '\\\\') + '"'


def desktop_entry(config, folder=None):
    folder = Path(folder or data_home()/'applications'); folder.mkdir(parents=True, exist_ok=True)
    path = folder/'crealityscan-linux.desktop'
    python = '/usr/bin/python3' if Path('/usr/bin/python3').exists() else sys.executable
    command = [python, ROOT/'scripts/creality.py', '--config', Path(config).resolve(), 'launch', '--mode', 'usb']
    path.write_text('\n'.join([
        '[Desktop Entry]', 'Type=Application', 'Name=CrealityScan',
        'Comment=CrealityScan for the Creality Pika (Linux compatibility launcher)',
        'Exec=' + ' '.join(desktop_quote(a) for a in command),
        'Icon=scanner', 'Terminal=false', 'StartupNotify=true', 'StartupWMClass=crealityscan.exe',
        'Categories=Graphics;3DGraphics;', '']))
    return path


def udev_rule_installed():
    for folder in (Path('/etc/udev/rules.d'), Path('/usr/lib/udev/rules.d'), Path('/lib/udev/rules.d')):
        try:
            if any('2bc5' in p.read_text(errors='replace') and '0c0b' in p.read_text(errors='replace')
                   for p in folder.glob('*.rules')):
                return True
        except OSError:
            continue
    return False


# GStreamer plugins Wine can decode H.264 with. The app plays H.264 tutorial
# videos (the first launch shows one) and closes when decoding fails.
H264_PLUGINS = ('libgstlibav.so', 'libgstopenh264.so')
GSTREAMER_DIRS = tuple(Path(p) for p in ('/usr/lib/x86_64-linux-gnu/gstreamer-1.0', '/usr/lib64/gstreamer-1.0',
                                         '/usr/lib/gstreamer-1.0'))
H264_HINT = ('Install an H.264 video decoder for GStreamer, or CrealityScan closes when it plays its tutorial\n'
             'video (shown on first launch):\n'
             '  Ubuntu/Debian: sudo apt install gstreamer1.0-libav\n'
             '  Arch/CachyOS:  sudo pacman -S --needed gst-libav\n'
             '  Fedora:        sudo dnf install gstreamer1-plugin-openh264')


def h264_decoder_installed(dirs=GSTREAMER_DIRS):
    """True when the host GStreamer (used by Wine inside the sandbox's /usr) can decode H.264."""
    return any((d/name).is_file() for d in dirs for name in H264_PLUGINS)


def other_gpu_present(drm=Path('/sys/class/drm')):
    """True when an Intel or AMD GPU is also present, e.g. a hybrid laptop."""
    for card in drm.glob('card*'):
        try:
            if card.name[4:].isdigit() and (card/'device/vendor').read_text().strip() in ('0x8086', '0x1002'):
                return True
        except OSError:
            continue
    return False


def write_config(path, gpu_name, installer):
    base = data_home()/'crealityscan-linux'
    runtime = base/'runtime'
    c = json.loads((ROOT/'config/config.example.json').read_text())
    c.update(runner=str(fetch.runner(runtime)), dxvk_dir=str(fetch.dxvk(runtime)),
             installer=str(installer), data_dir=str(base/'data'), exports_dir=str(default_dir()),
             gpu_name=gpu_name)
    if 'nvidia' in gpu_name.lower() and other_gpu_present():
        # On hybrid laptops apps render on the Intel/AMD GPU unless PRIME render
        # offload is requested for the NVIDIA one.
        c['environment'] = {'__NV_PRIME_RENDER_OFFLOAD': '1', '__GLX_VENDOR_LIBRARY_NAME': 'nvidia'}
    with open(path, 'x') as f:
        json.dump(c, f, indent=2); f.write('\n')
    print('Created', path, flush=True)


def prepare(config, installer=None, gpu_name=None):
    """Return a loaded config, creating it (and downloading pinned inputs) if needed."""
    if Path(config).exists():
        print('Using existing config', config, flush=True)
        return load(config)
    installer = Path(installer).expanduser().resolve() if installer else find_installer()
    if not installer:
        others = installer_candidates()
        if others:
            raise RuntimeError(f'{others[0]} is not a tested CrealityScan installer (its SHA-256 matches none of '
                               f'{versions()}). Download a supported version for Windows from Creality, or '
                               'see docs/SETUP.md for adding a new version')
        raise RuntimeError(f'No CrealityScan installer found in Downloads. Download CrealityScan {versions()} '
                           'for Windows from Creality, then rerun setup (or pass --installer PATH)')
    pinned = release(installer)
    if not pinned:
        raise RuntimeError(f'{installer} is not a tested CrealityScan installer ({versions()})')
    gpu_name = gpu_name or detect_gpu()
    if not gpu_name:
        raise RuntimeError('No OpenCL GPU found. Install your GPU OpenCL driver (docs/SETUP.md), '
                           'or pass --gpu-name with your GPU model')
    print('GPU:', gpu_name, f'| CrealityScan {pinned["version"]} installer:', installer, flush=True)
    write_config(config, gpu_name, installer)
    return load(config)


def set_aside_incomplete(c):
    """Move aside an install setup cannot use: a populated prefix with no saved
    baseline (a failed earlier attempt, or one made from another copy of this
    project). Only folders carrying this project's ownership marker are moved;
    nothing is deleted. Scans and projects live in the exports folder."""
    from integrity import installation_path
    data, prefix = c['data_dir'], c['prefix']
    if installation_path(c).exists() or not (data/'community-owner.json').is_file() \
            or prefix.is_symlink() or not prefix.is_dir() or not any(prefix.iterdir()):
        return None
    lock = owned(c)  # refuses while another session holds this install
    try:
        aside = data.with_name(f'{data.name}.previous-{datetime.datetime.now():%Y%m%d-%H%M%S}')
        os.rename(data, aside)
    finally:
        lock.close()
    print(f'An earlier install that setup could not verify (unfinished, or made from another copy of\n'
          f'this project) was moved aside to {aside}.\n'
          f'Your scans in {c["exports_dir"]} are not affected. Delete it once setup has finished.', flush=True)
    return aside


def helpers(c, build):
    """Use built or prebuilt helpers already in build/, else fetch pinned ones, else build."""
    manifest = ROOT/'build/manifest.json'
    if manifest.exists() and all(digest(ROOT/'build'/n) == h for n, h in json.loads(manifest.read_text()).items()):
        return
    if LOCK.get('helpers'):
        fetch.helpers(data_home()/'crealityscan-linux/runtime')
    else:
        print('No prebuilt helpers are pinned yet; building from source', flush=True)
        build(c)


def finish(config):
    entry = desktop_entry(config)
    print('Menu entry:', entry, flush=True)
    if not udev_rule_installed():
        print('\nOne step needs your password: let your user access the scanner, then replug it:\n'
              f'  sudo cp {UDEV_RULE} /etc/udev/rules.d/ && sudo udevadm control --reload', flush=True)
    if not h264_decoder_installed():
        print('\n' + H264_HINT, flush=True)
    print('\nDone. Open "CrealityScan" from your app menu with the scanner connected.', flush=True)
