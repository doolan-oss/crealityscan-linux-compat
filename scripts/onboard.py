"""One-command setup for new users: fetch, configure, install, check, add a menu entry."""
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from common import LOCK, ROOT, digest, load, owned
from exports import default_dir
import fetch
import gpuinfo

UDEV_RULE = ROOT/'config/70-creality-pika.rules'
RULE_FOLDERS = (Path('/etc/udev/rules.d'), Path('/run/udev/rules.d'), Path('/usr/lib/udev/rules.d'), Path('/lib/udev/rules.d'))


def data_home():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')


def downloads_dir():
    try:
        out = subprocess.run(['xdg-user-dir', 'DOWNLOAD'], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ''
    return Path(out) if out and Path(out).is_absolute() else Path.home()/'Downloads'


def find_installer():
    """The pinned CrealityScan installer in Downloads or home, matched by checksum."""
    for folder in (downloads_dir(), Path.home()):
        try:
            candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() == '.exe'
                                and 'crealityscan' in p.name.lower() and p.is_file())
        except OSError:
            continue
        for p in candidates:
            if digest(p) == LOCK['installer_sha256']:
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
        'Comment=CrealityScan 4.3.2 for the Creality Pika (Linux compatibility launcher)',
        'Exec=' + ' '.join(desktop_quote(a) for a in command),
        'Icon=scanner', 'Terminal=false', 'StartupNotify=true', 'StartupWMClass=crealityscan.exe',
        'Categories=Graphics;3DGraphics;', '']))
    return path


def udev_rule_installed(pid='0c0b', folders=RULE_FOLDERS):
    """Whether an installed udev rule line matches this scanner's USB ID: vendor 2bc5
    and this product (the Pika's by default) on the same, uncommented line."""
    vendor = re.compile(r'ATTRS?\{idVendor\}=="2bc5"', re.I)
    product = re.compile(r'ATTRS?\{idProduct\}=="%s"' % re.escape(pid), re.I)
    for folder in folders:
        try:
            for rules in folder.glob('*.rules'):
                for line in rules.read_text(errors='replace').splitlines():
                    if not line.lstrip().startswith('#') and vendor.search(line) and product.search(line):
                        return True
        except OSError:
            continue
    return False


def access_command():
    """The one-time command that installs this project's scanner udev rule."""
    return f'sudo cp {shlex.quote(str(UDEV_RULE))} /etc/udev/rules.d/ && sudo udevadm control --reload'


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
        raise RuntimeError('CrealityScan_win_4.3.2.exe not found in Downloads. Download CrealityScan '
                           '4.3.2 for Windows from Creality, then rerun setup (or pass --installer PATH)')
    if digest(installer) != LOCK['installer_sha256']:
        raise RuntimeError(f'{installer} is not the tested CrealityScan 4.3.2 installer')
    gpu_name = gpu_name or detect_gpu()
    if not gpu_name:
        raise RuntimeError('No OpenCL GPU found. Install your GPU OpenCL driver (docs/SETUP.md), '
                           'or pass --gpu-name with your GPU model')
    print('GPU:', gpu_name, '| Installer:', installer, flush=True)
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


def set_aside_outdated(c):
    """Move aside a finished install made with other helper programs than those
    now in build/ (an earlier release), with its baseline, so setup installs
    afresh: launches only accept installed code matching the current helpers."""
    from integrity import installation_path
    data, baseline = c['data_dir'], installation_path(c)
    try:
        if json.loads(baseline.read_text()).get('build') == json.loads((ROOT/'build/manifest.json').read_text()):
            return None
    except (OSError, ValueError):
        return None
    lock = owned(c)  # refuses while another session holds this install
    try:
        aside = data.with_name(f'{data.name}.previous-{datetime.datetime.now():%Y%m%d-%H%M%S}')
        os.rename(data, aside)
        moved = installation_path({'data_dir': aside})
        moved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.move(baseline, moved)
    finally:
        lock.close()
    print(f'CrealityScan was installed with earlier helper programs, so setup installs it again.\n'
          f'The earlier install was moved aside to {aside}.\n'
          f'Your scans in {c["exports_dir"]} are not affected. Delete it once the new install works.', flush=True)
    return aside


def helpers(c, build):
    """Use built or prebuilt helpers already in build/, else fetch pinned ones, else build.
    Prebuilt helpers from an earlier pinned release are replaced by the current one."""
    manifest = ROOT/'build/manifest.json'
    superseded = (LOCK.get('helpers') or {}).get('supersedes', [])
    if manifest.exists() and digest(manifest) not in superseded and \
            all(digest(ROOT/'build'/n) == h for n, h in json.loads(manifest.read_text()).items()):
        return
    if LOCK.get('helpers'):
        fetch.helpers(data_home()/'crealityscan-linux/runtime')
    else:
        print('No prebuilt helpers are pinned yet; building from source', flush=True)
        build(c)


def finish(config):
    import usb
    entry = desktop_entry(config)
    print('Menu entry:', entry, flush=True)
    # Check real access for connected scanners; otherwise whether the rule is installed.
    problems = usb.access_problems()
    blocked = [node for _, nodes in problems for node in nodes]
    if blocked and all(udev_rule_installed(model.pid) for model, _ in problems):
        print(f'\nThe scanner rule is installed, but {", ".join(blocked)} is still not accessible. Unplug and replug\n'
              f'the scanner. If that does not help, install the rule again:\n  {access_command()}', flush=True)
    elif blocked or (not usb.connected() and not udev_rule_installed()):
        where = f' ({", ".join(blocked)})' if blocked else ''
        print(f'\nOne step needs your password: let your user access the scanner{where}, then unplug and\n'
              f'replug it:\n  {access_command()}', flush=True)
    print('\nDone. Open "CrealityScan" from your app menu with the scanner connected.', flush=True)
