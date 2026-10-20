#!/usr/bin/python3
"""Integration check: replay through a binary pipe in a device-free sandbox."""
from collections import defaultdict
import hashlib,json,os,subprocess,sys,time
from safeio import open_file
from pathlib import Path
from replay import Recording,read_packets,read_at
root=Path(__file__).resolve().parents[2]
folder=Path(sys.argv[1]).absolute()
recording=Recording(folder)
command=['/usr/bin/bwrap','--unshare-net','--unshare-pid','--die-with-parent',
         '--tmpfs','/','--ro-bind','/usr','/usr','--dev','/dev','--proc','/proc',
         '--tmpfs','/tmp','--clearenv','--setenv','PATH','/usr/bin:/bin',
         '--setenv','LANG','C.UTF-8','--chdir','/run/recording']
for name in ('bin','lib','lib64'):
    p=Path('/')/name
    if p.is_symlink():command+=['--symlink',os.readlink(p),str(p)]
    elif p.exists():command+=['--ro-bind',str(p),str(p)]
command+=['--ro-bind',str(Path(__file__).parent),'/run/recorder',
          '--ro-bind',str(folder),'/run/recording',
          '/usr/bin/python3','/run/recorder/replay.py','/run/recording','--speed','0','--packet-stream']
producer=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
count=0;image_hash=defaultdict(hashlib.sha256);meta_hash=defaultdict(hashlib.sha256)
try:
    for event,payload,meta in read_packets(producer.stdout):
        expected=recording.events[count]
        if event!={**expected,'replay_loop':0}:raise ValueError('Event differs')
        image_hash[event['stream']].update(payload);meta_hash[event['stream']].update(meta);count+=1
finally:
    producer.stdout.close()
    diagnostics=producer.stderr.read().decode();code=producer.wait()
if code or count!=len(recording.events):raise RuntimeError(f'Producer failed/incomplete: {code}, {diagnostics}')
expected_meta=defaultdict(hashlib.sha256)
for stream in image_hash:
    if image_hash[stream].hexdigest()!=recording.report['files'][stream+'.bin']['sha256']:
        raise ValueError('Payload bytes differ from original file')
    with open_file(folder/(stream+'-meta.bin'),'rb') as f:
        for event in recording.events:
            if event['stream']==stream:
                expected_meta[stream].update(read_at(f,{'offset':event['metadata_offset'],'length':event['metadata_length']}))
    if expected_meta[stream].digest()!=meta_hash[stream].digest():raise ValueError('Metadata bytes differ')
# Real timed replay of the final second, without device access in this process either.
start=max(0,recording.report['duration_ns']/1e9-1)
t0=time.monotonic();timed=list(recording.frames(speed=1,start=start));elapsed=time.monotonic()-t0
expected=(timed[-1][0]['time_ns']-timed[0][0]['time_ns'])/1e9
if elapsed<expected-.01 or elapsed>expected+.25:raise ValueError(f'Timed replay drift: {elapsed} vs {expected}')
print(json.dumps({'passed':True,'events':count,'payload_sha256':{k:v.hexdigest()for k,v in image_hash.items()},
                  'metadata_sha256':{k:v.hexdigest()for k,v in meta_hash.items()},
                  'producer_devices':'private /dev; no camera or GPU nodes; private network',
                  'timed_tail_events':len(timed),'timed_tail_expected_seconds':expected,'timed_tail_elapsed_seconds':elapsed,
                  'producer_summary':json.loads(diagnostics)},indent=2))
