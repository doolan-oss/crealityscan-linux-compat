"""The one ordinary host folder the app may write: its Documents and projects."""
import os
from pathlib import Path
import stat
import subprocess
import stateio

# Fixed sandbox path: the app can repoint its own Documents link, but cannot
# move this mount over trusted files inside the sandbox.
EXPORTS_MOUNT = '/run/creality-exports'
DIRECTORY = os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
# Folders in each Wine profile that live in the exports folder instead, with the
# exports subfolder each uses. The app keeps its own paths, so its project list
# stays valid.
FOLDERS = (('Documents', ''), ('AppData/Local/Creality/CrealityScan/Projects', 'Projects'))


def default_dir():
    try:
        docs = subprocess.run(['xdg-user-dir', 'DOCUMENTS'], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        docs = ''
    base = Path(docs) if docs and Path(docs).is_absolute() else Path.home()/'Documents'
    return base/'CrealityScan'


def check_dir(path, protected):
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError('exports_dir must be absolute (or start with ~)')
    path = path.resolve()
    if Path.home().resolve().is_relative_to(path):
        raise ValueError('exports_dir must be a dedicated folder, not your home directory or a parent of it')
    for p in protected:
        if path.is_relative_to(p) or Path(p).is_relative_to(path):
            raise ValueError('exports_dir must be separate from source, trust, runner and data directories')
    return path


def _exists(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _remove_if_empty(parent, name, depth=0):
    """Remove a tree of empty directories; any file or link keeps it all."""
    if depth > 8 or not stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
        return False
    fd = os.open(name, DIRECTORY, dir_fd=parent)
    try:
        with os.scandir(fd) as it:
            entries = [e.name for e in it]
        if not all(_remove_if_empty(fd, child, depth+1) for child in entries):
            return False
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)
    return True


def _open_dirs(fd, parts):
    """Open nested real directories, creating them, without following links."""
    fd = os.dup(fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd); fd = child
    except BaseException:
        os.close(fd); raise
    return fd


def _move_into(parent, name, target, moved):
    """Move a real folder's contents into target, all or nothing, then remove it.
    Renames only: never copies, overwrites or deletes user files."""
    fd = os.open(name, DIRECTORY, dir_fd=parent)
    try:
        if os.fstat(fd).st_dev != os.fstat(target).st_dev:
            return False
        with os.scandir(fd) as it:
            names = sorted(e.name for e in it)
        names = [n for n in names if not _remove_if_empty(fd, n)]
        if any(_exists(target, n) for n in names):
            return False
        done = []
        try:
            for n in names:
                os.rename(n, n, src_dir_fd=fd, dst_dir_fd=target); done.append(n)
        except OSError:
            for n in reversed(done):
                os.rename(n, n, src_dir_fd=target, dst_dir_fd=fd)
            return False
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)
    moved += names
    return True


def _link(profile, path, link_target, target, moved):
    *parents, name = path.split('/')
    parent = _open_dirs(profile, parents)
    try:
        try:
            mode = os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None and stat.S_ISLNK(mode):
            if os.readlink(name, dir_fd=parent) == link_target:
                return True
            os.unlink(name, dir_fd=parent)
        elif mode is not None and not (stat.S_ISDIR(mode) and (
                _remove_if_empty(parent, name) or _move_into(parent, name, target, moved))):
            return False
        os.symlink(link_target, name, dir_fd=parent)
        return True
    finally:
        os.close(parent)


def link_folders(prefix, exports_dir):
    """Point each Wine profile's FOLDERS at the exports mount, moving existing
    contents into the exports folder. Returns (folders left unchanged, names moved)."""
    kept, moved = [], []
    with stateio.directory(exports_dir) as exports, \
         stateio.directory(Path(prefix)/'drive_c/users') as users:
        for name in sorted(os.listdir(users)):
            if name == 'Public':
                continue
            try:
                profile = os.open(name, DIRECTORY, dir_fd=users)
            except OSError:
                continue
            try:
                for path, sub in FOLDERS:
                    target = _open_dirs(exports, [sub] if sub else [])
                    try:
                        if not _link(profile, path, EXPORTS_MOUNT + ('/'+sub if sub else ''), target, moved):
                            kept.append(f'{name}/{path}')
                    except OSError:
                        kept.append(f'{name}/{path}')
                    finally:
                        os.close(target)
            finally:
                os.close(profile)
    return kept, moved
