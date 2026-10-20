"""Bounded regular-file IO; no symlink traversal or output replacement.

Open each directory component relative to an already-open descriptor. Checking
Path.resolve()/is_symlink() before an ordinary open would leave a race window.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat

MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 20000
MAX_LINE_BYTES = 8192
MAX_PAYLOAD_BYTES = 16 * 1024**3
MAX_IMAGE_BYTES = 8 * 1024**2
MAX_META_BYTES = 64 * 1024
MAX_DURATION_US = 120 * 1000000
MAX_GAP_US = 5 * 1000000


@contextmanager
def parent_fd(path):
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def open_file(path, mode='r'):
    if mode not in ('r', 'rb', 'w', 'wb', 'x', 'xb'):
        raise ValueError('Unsupported safe IO mode')
    writing = mode[0] in 'wx'
    flags = os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL if writing else os.O_RDONLY
    with parent_fd(path) as (parent, name):
        fd = os.open(name, flags, 0o600, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Only singly linked regular files are accepted (no hard links)')
        if not writing and info.st_size > MAX_PAYLOAD_BYTES:
            raise ValueError('File exceeds payload size limit')
        return os.fdopen(fd, mode.replace('w', 'x'))
    except BaseException:
        os.close(fd)
        raise


def exists(path):
    try:
        with open_file(path, 'rb'):
            return True
    except FileNotFoundError:
        return False


def file_size(path):
    with open_file(path, 'rb') as f:
        return os.fstat(f.fileno()).st_size


def read_bytes(path, limit=MAX_INDEX_BYTES):
    with open_file(path, 'rb') as f:
        if os.fstat(f.fileno()).st_size > limit:
            raise ValueError('File exceeds read size limit')
        data = f.read(limit + 1)
        if len(data) > limit:
            raise ValueError('File grew beyond read size limit')
        return data


def read_text(path, limit=MAX_INDEX_BYTES):
    return read_bytes(path, limit).decode('utf-8')


def read_jsonl(path):
    rows = []
    with open_file(path, 'rb') as f:
        if os.fstat(f.fileno()).st_size > MAX_INDEX_BYTES:
            raise ValueError('Index exceeds byte limit')
        consumed = 0
        while line := f.readline(MAX_LINE_BYTES + 1):
            consumed += len(line)
            if len(line) > MAX_LINE_BYTES or consumed > MAX_INDEX_BYTES or len(rows) >= MAX_ROWS:
                raise ValueError('Index exceeds line/byte/row limit')
            rows.append(json.loads(line))
    return rows


def write_bytes(path, data):
    with open_file(path, 'xb') as f:
        f.write(data)


def write_text(path, data):
    with open_file(path, 'x') as f:
        f.write(data)


def mkdir_new(path):
    # Require the caller-selected parent to exist; never resolve a symlinked parent.
    with parent_fd(path) as (parent, name):
        os.mkdir(name, mode=0o700, dir_fd=parent)
