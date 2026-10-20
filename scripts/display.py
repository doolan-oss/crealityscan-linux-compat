"""Display for the app sandbox: the desktop's own X server, or an isolated one."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import tempfile
import time
import stateio

X11_DIR = Path('/tmp/.X11-unix')
MODES = ('desktop', 'isolated')


@dataclass(frozen=True)
class Display:
    name: str                  # DISPLAY value inside the sandbox
    socket: Path               # host X socket bound into the sandbox
    xauthority: Path | None    # host cookie file, if the server needs one


def desktop(environ=os.environ):
    """The X server already serving this desktop session (XWayland or Xorg)."""
    m = re.fullmatch(r':([0-9]+)(?:\.[0-9]+)?', environ.get('DISPLAY', ''))
    if not m:
        raise RuntimeError('No local desktop display (DISPLAY=:N); start from your desktop session')
    sock = X11_DIR/f'X{m[1]}'
    if not sock.is_socket():
        raise RuntimeError(f'Desktop X socket {sock} not found')
    auth = Path(environ.get('XAUTHORITY') or Path.home()/'.Xauthority')
    return Display(f':{m[1]}', sock, auth if auth.is_file() else None)


def free_number(start=64):
    for n in range(start, start+512):
        if not (X11_DIR/f'X{n}').exists() and not Path(f'/tmp/.X{n}-lock').exists():
            return n
    raise RuntimeError('No free X display number for the isolated display')


@contextmanager
def isolated(log, timeout=20):
    """A private rootless XWayland server whose windows are normal desktop windows."""
    exe = shutil.which('xwayland-satellite')
    if not exe:
        raise RuntimeError('display "isolated" needs xwayland-satellite on PATH; or set "display": "desktop"')
    if not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('display "isolated" needs a Wayland desktop session')
    number = free_number()
    env = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'DISPLAY')}
    with tempfile.TemporaryDirectory(prefix='creality-display-') as tmp, \
         socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify, \
         stateio.open_file(Path(log)/'display.log', 'xb') as out:
        # xwayland-satellite reports readiness with the systemd notify protocol.
        env['NOTIFY_SOCKET'] = os.path.join(tmp, 'notify')
        notify.bind(env['NOTIFY_SOCKET'])
        proc = subprocess.Popen([exe, f':{number}'], env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+timeout
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f'xwayland-satellite exited ({proc.returncode}); see display.log')
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('xwayland-satellite did not become ready; see display.log')
                if select.select([notify], [], [], min(remaining, 0.5))[0] and \
                        b'READY=1' in notify.recv(4096).split(b'\n'):
                    break
            sock = X11_DIR/f'X{number}'
            if not sock.is_socket():
                raise RuntimeError(f'Isolated X socket {sock} not found')
            yield Display(f':{number}', sock, None)
        finally:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()


@contextmanager
def open_display(mode, log):
    if mode == 'isolated':
        with isolated(log) as d:
            yield d
    else:
        yield desktop()
