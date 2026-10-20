import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from replay import Recording, MAGIC, pack, read_packets, write_packet

class ReplayTests(unittest.TestCase):
    def dataset(self, root):
        (root/'manifest.json').write_text(json.dumps({'format_version':1,'status':'passed','controls_restored':True}))
        images=[]; metadata=[]; rows=[]; metas=[]
        for i, (camera, pts) in enumerate(((0xa2,0xfffffff0),(0xa3,0xfffffff5),(0xa2,8320),(0xa3,8325))):
            image=bytes([i+1])*(1280*960)
            raw=struct.pack('<QH',100+i,1)+struct.pack('<BBIBBHH',12,12,pts,camera,0xc3,0,0)
            base=dict(sequence=i,flags=0x2000,v4l2_us=1000000+i*4167,received_monotonic_ns=100+i)
            rows.append(dict(base,offset=sum(map(len,images)),length=len(image)))
            metas.append(dict(base,offset=sum(map(len,metadata)),length=len(raw)))
            images.append(image);metadata.append(raw)
        for name, blobs, index in [('ir',images,rows),('ir-meta',metadata,metas)]:
            (root/(name+'.bin')).write_bytes(b''.join(blobs))
            (root/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in index))
        return images,metadata

    def test_byte_exact_packets_wrap_seek_loop_and_pacing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);images,metadata=self.dataset(root);report=pack(root)
            self.assertEqual(report['stereo_pair_candidates'],2)
            source=Recording(root)
            frames=list(source.frames(speed=0));self.assertEqual([f[1] for f in frames],images)
            self.assertEqual([f[2] for f in frames],metadata)
            wire=io.BytesIO(MAGIC)
            wire.seek(0,2)
            for frame in frames:write_packet(wire,*frame)
            wire.seek(0);self.assertEqual(list(read_packets(wire)),frames)
            self.assertEqual(len(list(source.frames(speed=0,start=.005,loops=2))),4)
            now=[0];sleeps=[]
            def sleep(t):sleeps.append(t);now[0]+=round(t*1e9)
            list(source.frames(speed=2,clock=lambda:now[0],sleep=sleep))
            self.assertAlmostEqual(sum(sleeps),.012501/2)
            for invalid in (float('nan'),-1,float('inf')):
                with self.assertRaises(ValueError):list(source.frames(speed=invalid))

    def test_corruption_and_truncated_packet_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.dataset(root);pack(root)
            with self.assertRaises(FileExistsError):pack(root)
            with (root/'ir.bin').open('r+b') as f:f.write(b'x')
            with self.assertRaisesRegex(ValueError,'integrity'):Recording(root)
        with self.assertRaisesRegex(ValueError,'Truncated'):
            list(read_packets(io.BytesIO(MAGIC+b'abc')))

    def test_invalid_scan_combinations_rejected_before_hardware(self):
        script=Path(__file__).with_name('recorder.py')
        for flags in (['--color'],['--sync-mode','mixed'],['--fps','90'],['--seconds','31'],['--illumination-test','off']):
            r=subprocess.run([sys.executable,str(script),'--scan-mode','marker-laser',*flags],capture_output=True)
            self.assertEqual(r.returncode,2)

if __name__=='__main__':unittest.main()
