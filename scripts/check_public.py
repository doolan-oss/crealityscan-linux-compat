#!/usr/bin/env python3
"""Check the staged Git publication set; never scans ignored runtime data."""
import argparse,subprocess,sys,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--worktree',action='store_true',help='Check tracked and nonignored new source files before staging')
args=ap.parse_args()
command=['git','ls-files','-z']+(['--cached','--others','--exclude-standard']if args.worktree else [])
files=subprocess.check_output(command,cwd=root).decode().split('\0');bad=[];count=0
for name in filter(None,files):
    p=root/name;count+=1
    if p.is_symlink():bad.append((name,'symlink'));continue
    if p.suffix.lower()in {'.exe','.dll','.so','.obj','.o','.a','.lib','.bin','.jpg','.png','.zip','.xz','.pkg','.pyc'}:bad.append((name,'binary/runtime file'));continue
    if name.startswith(('build/','logs/','recordings/','prefix','downloads/','backups/','exports/','.local-trust/'))or re.fullmatch(r'config(?:\..+)?\.local\.json',name):bad.append((name,'local data'));continue
    raw=p.read_bytes() if args.worktree else subprocess.check_output(['git','show',':'+name],cwd=root)
    if len(raw)>1024*1024 or b'\0'in raw:bad.append((name,'large/binary file'));continue
    if re.search(rb'/home/[A-Za-z0-9_.-]+/',raw) or re.search(rb'GPU-[0-9a-fA-F]{16}',raw):bad.append((name,'personal path/identity'))
if not count:bad.append(('<index>','no staged source'))
if bad:
    for name,reason in bad:print(f'FAIL {name}: {reason}')
    sys.exit(1)
scope='worktree' if args.worktree else 'index'
print(f'PASS: {count} source/documentation files ({scope}); no runtime binaries, personal home paths or local data.')
