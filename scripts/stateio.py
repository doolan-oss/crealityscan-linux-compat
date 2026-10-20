"""Host operations on app-writable state must not follow app-created links."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import stat


@contextmanager
def directory(path, create=False):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for part in Path(os.path.abspath(path)).parts[1:]:
            if create:
                try:os.mkdir(part,mode=0o700,dir_fd=fd)
                except FileExistsError:pass
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=child
        yield fd
    finally:os.close(fd)


def ensure_directory(path):
    with directory(path,create=True):pass


def open_file(path, mode='rb'):
    path=Path(path)
    flags={'rb':os.O_RDONLY,'xb':os.O_WRONLY|os.O_CREAT|os.O_EXCL,
           'replace':os.O_WRONLY|os.O_CREAT}[mode]
    with directory(path.parent) as parent:
        fd=os.open(path.name,flags|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600,dir_fd=parent)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise RuntimeError('State file must be singly linked and regular')
        # Check first: O_TRUNC at open time would damage a hard-link target.
        if mode=='replace':os.ftruncate(fd,0)
        return os.fdopen(fd,'rb' if mode=='rb' else 'wb')
    except BaseException:
        os.close(fd);raise


def read_text(path, limit=16*1024*1024):
    with open_file(path) as f:
        data=f.read(limit+1)
    if len(data)>limit:raise RuntimeError('State text exceeds size limit')
    return data.decode('utf-8',errors='replace')


def write_new(path,text):
    with open_file(path,'xb') as f:f.write(text.encode())


def copy_file(source,destination,*,replace=False):
    with open_file(source) as src, open_file(destination,'replace' if replace else 'xb') as dst:
        shutil.copyfileobj(src,dst)
