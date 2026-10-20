import json
from pathlib import Path
import struct
import tempfile
import unittest
from analyze import uvc_records,load_index
from device import parse_response,Control

class Tests(unittest.TestCase):
    def test_response_validation(self):
        payload=struct.pack('<5i',1000,3000,10,1000,10)
        raw=struct.pack('<5H',0x4252,11,1,9,0)+payload
        self.assertEqual(parse_response(raw,1,9),payload)
        for op,rid in ((2,9),(1,10)):
            with self.assertRaises(ValueError):parse_response(raw,op,rid)
        with self.assertRaises(ValueError):parse_response(raw[:15],1,9)
        with self.assertRaises(RuntimeError):parse_response(struct.pack('<5H',0x4252,1,1,9,1),1,9)

    def test_uvc_records_preserve_every_header(self):
        header=struct.pack('<BBIIH',12,0x0c,123,456,789)
        record=struct.pack('<QH',10000,99)+header
        parsed=uvc_records(record*2)
        self.assertEqual(len(parsed),2)
        self.assertEqual(parsed[0]['pts'],123)
        self.assertEqual(parsed[0]['scr_clock'],456)
        self.assertEqual(parsed[0]['header_hex'],header.hex())

    def test_uvc_rejects_bad_lengths(self):
        for raw in (b'\0',b'\0'*12,struct.pack('<QHBB',1,2,255,12),struct.pack('<QHBB',1,2,2,12)):
            with self.assertRaises(ValueError):uvc_records(raw)

    def test_index_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'ir.bin').write_bytes(b'1234')
            (d/'ir.jsonl').write_text(json.dumps({'offset':0,'length':4})+'\n')
            self.assertEqual(len(load_index(d,'ir')),1)
            for offset,length in ((1,3),(0,5),(0,3),(0,-1)):
                (d/'ir.jsonl').write_text(json.dumps({'offset':offset,'length':length}))
                with self.assertRaises(ValueError):load_index(d,'ir')

    def test_write_allowlist(self):
        c=object.__new__(Control)
        for prop,value in ((29,1),(3,1),(152,1),(153,1),(2026,3000)):
            with self.assertRaises(ValueError):c.set(prop,value)

    def test_restore_saved_before_failed_readback(self):
        c=object.__new__(Control);c.saved={}
        c.get=lambda p:{'current':1000,'min':10,'max':3000,'step':10}
        c.transact=lambda *a:b''
        with self.assertRaises(RuntimeError):c.set(2026,2000)
        self.assertEqual(c.saved,{2026:1000})

if __name__=='__main__':unittest.main()
