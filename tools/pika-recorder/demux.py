#!/usr/bin/python3
"""Offline Pika camera/phase split. Original recording bytes are never modified."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import struct
from safeio import open_file, write_text, write_bytes, read_bytes, mkdir_new, MAX_ROWS
from analyze import load_index,uvc_records

CAMERAS={0xa2:'left',0xa3:'right'}
# Recovered from the SDK's Sermoon callback used for these Pika frames.
PHASE_ENUM={0xc2:5,0xc3:2,0xc4:1,0xc5:3,0xc6:4,0xc7:6,0xc8:7}
# Numeric SDK mapping is stable in measured headers; optical meaning is not.
# In native mode 6, C4 contains projected speckles. Never equate it with white LED.
PHASE_ROLE={phase:f'sdk_type_{value}_slot' for phase,value in PHASE_ENUM.items()}



def classify(raw):
    headers=uvc_records(raw)
    if not headers:raise ValueError('No UVC headers')
    triples=set()
    for record in headers:
        h=bytes.fromhex(record['header_hex'])
        # This layout is established only for the standard 12-byte header with PTS+SCR.
        if len(h)!=12 or h[1]&0x0c != 0x0c:raise ValueError('Unsupported header layout')
        if h[1]&0x40:raise ValueError('UVC error flag')
        triples.add((h[6],h[7],struct.unpack_from('<I',h,2)[0]))
    if len(triples)!=1:raise ValueError('Conflicting camera/phase/PTS headers in a frame')
    camera,phase,pts=triples.pop()
    if camera not in CAMERAS:raise ValueError(f'Unknown camera tag 0x{camera:02x}')
    if phase not in PHASE_ENUM:raise ValueError(f'Unknown phase tag 0x{phase:02x}')
    return {'camera':CAMERAS[camera],'camera_tag':f'0x{camera:02x}',
            'phase_tag':f'0x{phase:02x}','sdk_light_type':PHASE_ENUM[phase],
            'phase_role':PHASE_ROLE[phase],'device_pts_raw':pts,'uvc_header_count':len(headers),
            'illumination_emitted':'not_established_by_tag'}


def signed_delta(a,b):return ((a-b+(1<<31))&0xffffffff)-(1<<31)


def candidate_pairs(frames,tolerance=100):
    """Mutual, unique near-neighbours of the same phase, across opposite cameras.
    PTS differences in this Pika data behave as microseconds. Keep raw units in
    output because the device clock's absolute calibration is not independently verified.
    No sequence parity or exact equality assumption. Conservative: ambiguous => unpaired.
    """
    if len(frames)>MAX_ROWS:raise ValueError('Too many pairing frames')
    by=defaultdict(list)
    for r in frames:by[(r['phase_tag'],r['camera'])].append(r)
    pairs=[]
    for phase in sorted({r['phase_tag']for r in frames}):
        left=by[(phase,'left')];right=by[(phase,'right')]
        # Bounded short recordings; sorted circular PTS neighbours via bisect avoids O(N²).
        import bisect
        ordered=sorted((r['device_pts_raw'],i) for i,r in enumerate(right))
        points=[v for v,i in ordered]
        candidates={};reverse=defaultdict(list)
        edges=0
        for i,l in enumerate(left):
            p=l['device_pts_raw'];ids=set()
            for center in (p,p-(1<<32),p+(1<<32)):
                lo=bisect.bisect_left(points,center-tolerance);hi=bisect.bisect_right(points,center+tolerance)
                edges+=hi-lo
                if edges>MAX_ROWS*8:raise ValueError('Excessive ambiguous pairing density')
                ids.update(ordered[k][1] for k in range(lo,hi))
            candidates[i]=ids
            for j in ids:reverse[j].append(i)
        for i,ids in candidates.items():
            if len(ids)!=1:continue
            j=next(iter(ids))
            if len(reverse[j])!=1:continue
            l,r=left[i],right[j]
            pairs.append({'phase_tag':phase,'left_sequence':l['sequence'],'right_sequence':r['sequence'],
                          'right_minus_left_pts_raw':signed_delta(r['device_pts_raw'],l['device_pts_raw']),
                          'kind':'timestamp_candidate_not_calibrated_stereo_pair'})
    return sorted(pairs,key=lambda r:min(r['left_sequence'],r['right_sequence']))


def demux(root,out,export=False):
    root=Path(root).absolute();out=Path(out).absolute()
    if out==root or root in out.parents and out.name in ('ir.bin','ir.jsonl'):raise ValueError('Invalid output')
    rows=load_index(root,'ir');meta=load_index(root,'ir-meta')
    mkdir_new(out)
    metadata=defaultdict(list)
    for row in meta:metadata[row['sequence']].append(row)
    classified=[];rejected=[];groups=defaultdict(list)
    with open_file(root/'ir-meta.bin','rb') as f:
        for row in rows:
            try:
                if row['flags']&0x40 or row['length']!=1280*960:raise ValueError('Invalid image buffer')
                matches=metadata[row['sequence']]
                if len(matches)!=1:raise ValueError('Missing or duplicate matching metadata')
                m=matches[0]
                if m['flags']&0x40:raise ValueError('Metadata buffer error flag')
                f.seek(m['offset']);d=classify(f.read(m['length']))
                result={**row,**d,'source_file':str(root/'ir.bin')}
                classified.append(result)
                groups[f"{d['camera']}-{d['phase_tag'][2:]}"] .append(result)
            except ValueError as e:rejected.append({**row,'reason':str(e)})
    with open_file(out/'frames.jsonl','w')as f:
        for row in classified:f.write(json.dumps(row)+'\n')
    with open_file(out/'rejected.jsonl','w')as f:
        for row in rejected:f.write(json.dumps(row)+'\n')
    # Indexes can point into the original data; optionally copy into separate raw streams.
    with open_file(root/'ir.bin','rb')as data:
        for name,group in groups.items():
            with open_file(out/(name+'.jsonl'),'w')as idx:
                target=open_file(out/(name+'.bin'),'xb')if export else None
                try:
                    offset=0
                    for row in group:
                        entry=dict(row)
                        if target:
                            data.seek(row['offset']);payload=data.read(row['length'])
                            if len(payload)!=row['length']:raise ValueError('Truncated image')
                            target.write(payload);entry['source_offset']=row['offset'];entry['offset']=offset
                            entry['source_file']=str(out/(name+'.bin'));offset+=len(payload)
                        idx.write(json.dumps(entry)+'\n')
                finally:
                    if target:target.close()
            sample=group[len(group)//2];data.seek(sample['offset']);payload=data.read(sample['length'])
            write_bytes(out/(name+'-sample.pgm'),b'P5\n1280 960\n255\n'+payload)
    pairs=candidate_pairs(classified)
    write_text(out/'pair-candidates.jsonl',''.join(json.dumps(p)+'\n'for p in pairs))
    summary={'schema_version':2,'source_recording':str(root),'classified':len(classified),'rejected':len(rejected),
             'groups':{name:len(group)for name,group in sorted(groups.items())},
             'camera_mapping':'SDK left=A2; SDK right=A3. Viewpoint differs when facing scanner.',
             'phase_meaning':'SDK slot labels; actual emission and wavelength are not encoded by these labels',
             'pair_candidates':len(pairs),'unpaired_classified_frames':len(classified)-2*len(pairs),
             'pair_tolerance_raw_pts_units':100,
             'pair_delta_raw_median':statistics.median(p['right_minus_left_pts_raw']for p in pairs)if pairs else None,
             'pair_abs_delta_raw_max':max((abs(p['right_minus_left_pts_raw'])for p in pairs),default=None),
             'input_index_hashes':{n:hashlib.sha256(read_bytes(root/n)).hexdigest()for n in ('ir.jsonl','ir-meta.jsonl')},
             'decoder_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_text(out/'summary.json',json.dumps(summary,indent=2)+'\n')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('recording',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--export-streams',action='store_true',help='Copy separate GREY streams; default writes indexes and samples only')
    a=p.parse_args()
    try:print(json.dumps(demux(a.recording,a.output or a.recording/'demux-v2',a.export_streams),indent=2))
    except (OSError,ValueError,KeyError)as e:p.exit(1,f'Demux failed: {e}\n')
