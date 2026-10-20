"""Validate recorder indexes and decode standard UVC metadata, never camera identity."""
import json
from pathlib import Path
import struct
import sys
from safeio import (open_file, exists, file_size, read_jsonl, write_text, write_bytes,
                    MAX_IMAGE_BYTES, MAX_META_BYTES, MAX_DURATION_US, MAX_GAP_US)


def uvc_records(raw):
    records=[];pos=0
    while pos < len(raw):
        if len(raw)-pos < 12: raise ValueError(f'Truncated UVCH prefix at {pos}')
        host_ns, sof, n, flags = struct.unpack_from('<QHBB',raw,pos)
        if n < 2 or pos+10+n > len(raw): raise ValueError(f'Invalid UVC header length at {pos}')
        h=raw[pos+10:pos+10+n];k=2
        rec={'host_ns':host_ns,'usb_sof':sof,'header_hex':h.hex(),'flags':flags}
        if flags&4:
            if k+4>n:raise ValueError('Truncated PTS')
            rec['pts']=struct.unpack_from('<I',h,k)[0];k+=4
        if flags&8:
            if k+6>n:raise ValueError('Truncated SCR')
            rec['scr_clock'],rec['scr_sof']=struct.unpack_from('<IH',h,k);k+=6
        rec['extension_hex']=h[k:].hex()
        records.append(rec);pos+=10+n
    return records


def load_index(root,name):
    rows=read_jsonl(root/(name+'.jsonl'))
    size=file_size(root/(name+'.bin'));end=0
    if name.endswith('-meta') and size>16*1024*1024:raise ValueError('Aggregate metadata exceeds limit')
    first=None;prior=None
    for row in rows:
        if not isinstance(row,dict) or any(type(row.get(k)) is not int for k in ('offset','length')):
            raise ValueError('Invalid index types')
        maximum=MAX_META_BYTES if name.endswith('-meta') else MAX_IMAGE_BYTES
        if row['length']>maximum:raise ValueError('Frame exceeds size limit')
        if 'v4l2_us' in row:
            stamp=row['v4l2_us']
            if type(stamp)is not int or stamp<0:raise ValueError('Invalid timestamp')
            if first is None:first=stamp
            if stamp-first>MAX_DURATION_US or (prior is not None and (stamp<prior or stamp-prior>MAX_GAP_US)):
                raise ValueError('Recording duration/timestamp gap exceeds limit')
            prior=stamp
        if row['offset']!=end or row['length']<0:raise ValueError(f'Invalid index: {name}')
        end+=row['length']
        if end>size:raise ValueError(f'Index exceeds file: {name}')
    if end!=size:raise ValueError(f'Unindexed bytes: {name}')
    return rows


def analyze(root):
    root=Path(root);result={}
    for name in ('ir','color'):
        if not exists(root/(name+'.jsonl')):continue
        rows=load_index(root,name);meta=load_index(root,name+'-meta')
        byseq={};malformed=0
        with open_file(root/(name+'-meta.bin'),'rb') as data, open_file(root/(name+'-metadata.jsonl'),'w') as out:
            for row in meta:
                data.seek(row['offset']);raw=data.read(row['length'])
                try: records=uvc_records(raw)
                except ValueError as e:records=[];malformed+=1;row['parse_error']=str(e)
                byseq.setdefault(row['sequence'],[]).extend(records)
                out.write(json.dumps({**row,'uvc':records})+'\n')
        times=[r['v4l2_us'] for r in rows]
        gaps=sum(max(0,b['sequence']-a['sequence']-1) for a,b in zip(rows,rows[1:]))
        count=len(rows);dt=(times[-1]-times[0])/1e6 if count>1 else 0
        summary={'frames':count,'fps_from_v4l2_timestamps':(count-1)/dt if dt>0 else None,
                 'sequence_gaps':gaps,'error_flagged_frames':sum(bool(r['flags']&0x40) for r in rows),
                 'empty_frames':sum(r['length']==0 for r in rows),
                 'metadata_buffers':len(meta),'malformed_metadata_buffers':malformed,
                 'frames_with_metadata':sum(bool(byseq.get(r['sequence'])) for r in rows),
                 'frames_with_pts_scr':sum(any('pts'in m and 'scr_clock'in m for m in byseq.get(r['sequence'],[])) for r in rows),
                 'bytes':file_size(root/(name+'.bin'))}
        if name=='ir':summary['unexpected_payload_sizes']=sum(r['length']!=1280*960 for r in rows)
        # Representative raw sample, no contrast correction. PGM preserves GREY values.
        if rows:
            row=rows[len(rows)//2]
            with open_file(root/(name+'.bin'),'rb') as data:
                data.seek(row['offset']);sample=data.read(row['length'])
            if name=='ir' and len(sample)==1280*960:
                write_bytes(root/'sample-ir.pgm',b'P5\n1280 960\n255\n'+sample)
                summary['sample_pixel_min']=min(sample);summary['sample_pixel_max']=max(sample)
                summary['sample_pixel_mean']=sum(sample)/len(sample)
            elif name=='color' and sample.startswith(b'\xff\xd8'):
                write_bytes(root/'sample-color.jpg',sample)
        result[name]=summary
    write_text(root/'summary.json',json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__': print(json.dumps(analyze(sys.argv[1]),indent=2))
