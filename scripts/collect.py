"""Bundle the latest USB session's logs into one zip file for a bug report,
with scanner serial numbers, Wi-Fi names and passwords, and your home folder
path replaced.
The app can write to its logs, so links in them are never followed."""
import datetime
import os
from pathlib import Path
import re
import stat
import zipfile
import stateio

LIMIT = 4 * 1024 * 1024  # per file; the end of a log matters most
SERIALS = [re.compile(p, re.I) for p in (
    r'\bSN(?:/ID)?\s*:\s*([A-Za-z0-9]{6,32})\b', r'"serialNumber"\s*:\s*"([A-Za-z0-9]{6,32})"',
    r'Physical serial:\s*([A-Za-z0-9]{6,32})\b', r'&([A-Za-z0-9]{6,32})&0&0&0\b',
    r'VID_2BC5&PID_[0-9A-F]{4}\\+([A-Za-z0-9]{6,32})\b', r'PikaLinuxBridge\\+([A-Za-z0-9]{6,32})\b')]
# CrealityScan logs the scanner's Wi-Fi settings, e.g. "GetDeviceWifiPassword : ..." and "wifiBridgeSsid:...".
WIFI = re.compile(r'(?i)((?:passw\w*|pwd|psk|ssid)["\']?\s*[:=]\s*["\']?)[^\s"\',}]+')
APP_LOGS = 'AppData/Local/Creality/CrealityScan/Logs'


def entries(folder):
    """(name, is_directory) of a folder's real files and directories, never via links."""
    try:
        with stateio.directory(folder) as fd:
            found = []
            for name in os.listdir(fd):
                mode = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
                if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
                    found.append((name, stat.S_ISDIR(mode)))
            return sorted(found)
    except OSError:
        return []


def read_tail(path):
    with stateio.open_file(path) as f:
        size = os.fstat(f.fileno()).st_size
        f.seek(max(0, size - LIMIT))
        data = f.read(LIMIT)
    text = data.decode('utf-8', errors='replace')
    return (f'[first {size - LIMIT} bytes left out]\n' + text) if size > LIMIT else text


def sessions(c):
    """The newest USB launch log folder and the app's newest log folder."""
    launches = [name for name, folder in entries(c['data_dir']/'logs') if folder and name.endswith('-usb')]
    apps = []
    for user, folder in entries(c['prefix']/'drive_c/users'):
        if folder:
            apps += [(name, c['prefix']/'drive_c/users'/user/APP_LOGS/name)
                     for name, sub in entries(c['prefix']/'drive_c/users'/user/APP_LOGS) if sub]
    return (c['data_dir']/'logs'/launches[-1] if launches else None,
            max(apps)[1] if apps else None)


def redact(texts, serials=()):
    found = set(serials)
    for text in texts.values():
        for pattern in SERIALS:
            # Serial numbers mix letters and digits; skip words such as "unknown".
            found.update(s for s in pattern.findall(text) if re.search(r'\d', s) and re.search(r'[A-Za-z]', s))
    home = str(Path.home())
    out = {}
    for name, text in texts.items():
        for serial in sorted(found, key=len, reverse=True):
            text = text.replace(serial, 'SERIAL')
        out[name] = WIFI.sub(r'\1REMOVED', text.replace(home, '~'))
    return out


def collect(c, serials=(), out_dir=None):
    launch, app = sessions(c)
    if not launch and not app:
        raise RuntimeError('No logs found yet. Start CrealityScan with the scanner connected first.')
    texts = {}
    for label, folder in (('launch', launch), ('app', app)):
        if folder:
            for name, is_dir in entries(folder):
                if not is_dir:
                    texts[f'{label}-{folder.name}/{name}'] = read_tail(folder/name)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    target = Path(out_dir or Path.home())/f'crealityscan-logs-{stamp}.zip'
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, text in redact(texts, serials).items():
            z.writestr(name, text)
    return target, launch, app
