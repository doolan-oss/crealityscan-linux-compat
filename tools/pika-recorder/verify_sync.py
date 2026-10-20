#!/usr/bin/python3
"""Offline acceptance check for --sync-mode mixed; never opens the scanner.
Optical thresholds apply to a visible target, not arbitrary dark/empty scenes.
"""
import argparse,json,statistics
from pathlib import Path
from collections import Counter
from demux import signed_delta
from safeio import read_text, read_jsonl, open_file

def check(root):
 root=Path(root);m=json.loads(read_text(root/'manifest.json'));d=root/'demux-v2'
 summary=json.loads(read_text(d/'summary.json'));rows=read_jsonl(d/'frames.jsonl')
 result={'recording':str(root.resolve()),'checks':{},'cameras':{}}
 checks=result['checks'];checks['raw_capture_passed']=m['status']=='passed'
 checks['controls_restored']=m.get('controls_restored') is True
 checks['no_rejected_frames']=summary['rejected']==0
 checks['no_sequence_gaps']=all(s['sequence_gaps']==0 for s in m['summary'].values())
 checks['stereo_timestamp_agreement']=0<summary['pair_candidates'] and summary['pair_abs_delta_raw_max']<=100
 with open_file(root/'ir.bin','rb') as f:
  for camera in ('left','right'):
   tail=[r for r in rows if r['camera']==camera][-60:];phases=[r['phase_tag']for r in tail]
   pts=[r['device_pts_raw']for r in tail];dt=[signed_delta(b,a)for a,b in zip(pts,pts[1:])]
   c={'phase_counts':dict(Counter(phases)),'median_pts_interval':statistics.median(dt)if dt else None,'optical':{}}
   checks[camera+'_stable_cycle']=len(tail)==60 and set(phases)=={'0xc3','0xc4','0xc8'} and all(phases[i]==phases[i-3]for i in range(3,len(phases)))
   checks[camera+'_90hz_timing']=bool(dt) and all(10800<=v<=11500 for v in dt)
   for phase in sorted(set(phases)):
    stats=[]
    for r in tail:
     if r['phase_tag']!=phase:continue
     if type(r['offset'])is not int or r['offset']<0 or r['length']!=1280*960:raise ValueError('Invalid payload range')
     f.seek(r['offset']);b=f.read(r['length'])
     if len(b)!=1280*960:raise ValueError('Invalid payload')
     count=b.translate(bytes(int(i>64)for i in range(256))).count(1)
     stats.append((sum(b)/len(b),count))
    c['optical'][phase]={'median_mean':statistics.median(x[0]for x in stats),'median_pixels_above64':statistics.median(x[1]for x in stats)}
   result['cameras'][camera]=c
 result['protocol_passed']=all(checks.values())
 result['scene_matches_expected']=all(
  c['optical'].get('0xc3',{}).get('median_pixels_above64',0)>100 and
  c['optical'].get('0xc8',{}).get('median_pixels_above64',0)>500 and
  c['optical'].get('0xc4',{}).get('median_pixels_above64',100)<10
  for c in result['cameras'].values())
 result['optical_caveat']='Brightness supports gate isolation on this target; inspect images to distinguish stripes from speckles. No wavelength measurement.'
 return result

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('recording',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args()
 r=check(args.recording);text=json.dumps(r,indent=2)+'\n'
 if args.output:
  with open_file(args.output,'x')as f:f.write(text)
 print(text,end='');raise SystemExit(0 if r['protocol_passed']and r['scene_matches_expected']else 1)
