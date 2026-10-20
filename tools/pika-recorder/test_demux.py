import json
from pathlib import Path
import struct
import tempfile
import unittest
from demux import classify,candidate_pairs,demux

def header(camera=0xa2,phase=0xc3,pts=123,clock_aux=b'\0\0'):
    return struct.pack('<QHBBI',1000,4,12,12,pts)+bytes((camera,phase))+clock_aux+b'\0\0'

def frame(camera,pts,sequence,phase='0xc3'):
    return {'camera':camera,'device_pts_raw':pts,'sequence':sequence,'phase_tag':phase}

class Tests(unittest.TestCase):
    def test_camera_phase_independent_of_uvc_fid_and_packet_clock(self):
        self.assertEqual(classify(header()+header(clock_aux=b'\x10\x10'))['camera'],'left')
        self.assertEqual(classify(header(0xa3,0xc8))['sdk_light_type'],7)
        self.assertEqual(classify(header(0xa2,0xc4))['phase_role'],'sdk_type_1_slot')
    def test_conflicting_packet_labels_are_rejected(self):
        for bad in (header()+header(0xa3),header()+header(phase=0xc4),header()+header(pts=124)):
            with self.assertRaises(ValueError):classify(bad)
    def test_unknown_tags_and_error_headers_are_rejected(self):
        for raw in (header(0xa4),header(phase=0xc9),b''):
            with self.assertRaises(ValueError):classify(raw)
        raw=bytearray(header());raw[11]|=0x40
        with self.assertRaises(ValueError):classify(raw)
    def test_pairing_does_not_use_parity_or_exact_pts(self):
        rows=[frame('right',1000,0),frame('left',1020,1),frame('left',34000,2),frame('right',34010,4)]
        pairs=candidate_pairs(rows)
        self.assertEqual([(p['left_sequence'],p['right_sequence'])for p in pairs],[(1,0),(2,4)])
    def test_no_cross_phase_or_ambiguous_pairs(self):
        self.assertEqual(candidate_pairs([frame('left',10,0),frame('right',10,1,'0xc4')]),[])
        self.assertEqual(candidate_pairs([frame('left',10,0),frame('right',10,1),frame('right',20,2)]),[])
    def test_clock_wrap(self):
        pairs=candidate_pairs([frame('left',0xfffffff6,0),frame('right',10,1)])
        self.assertEqual(pairs[0]['right_minus_left_pts_raw'],20)
    def test_stream_export_preserves_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp)/'input';root.mkdir();out=Path(tmp)/'output'
            payloads=[bytes([16])*1228800,bytes([25])*1228800]
            (root/'ir.bin').write_bytes(b''.join(payloads));metas=[header(),header(0xa3,pts=133)]
            (root/'ir-meta.bin').write_bytes(b''.join(metas))
            rows=[{'sequence':i,'offset':i*1228800,'length':1228800,'flags':0,'v4l2_us':i}for i in range(2)]
            mrows=[{'sequence':i,'offset':i*len(metas[0]),'length':len(metas[0]),'flags':0}for i in range(2)]
            (root/'ir.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in rows))
            (root/'ir-meta.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in mrows))
            s=demux(root,out,True)
            self.assertEqual(s['classified'],2);self.assertEqual(s['pair_candidates'],1)
            self.assertEqual((out/'left-c3.bin').read_bytes(),payloads[0])
            self.assertEqual((out/'right-c3.bin').read_bytes(),payloads[1])
            self.assertEqual((root/'ir.bin').read_bytes(),b''.join(payloads))
            with self.assertRaises(FileExistsError):demux(root,out)
if __name__=='__main__':unittest.main()
