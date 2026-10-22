"""Scanner survey and launch messages, using a fake sysfs tree."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tools/pika-recorder')]
import survey
import usb

GUID = bytes.fromhex('a15157a5c5f35e4a8d5a6854b8fa2716')


class SurveyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'usb'
        self.device('1-2', '2bc5', '0c0b', 'Creality', 'Creality Pika', xu=True)
        self.device('1-3', '2bc5', '0abc', 'Creality', 'Sermoon S1')
        self.device('1-4', '046d', '0825', 'Logitech', 'HD Webcam')

    def device(self, name, vid, pid, maker, product, xu=False):
        d = self.root/name; d.mkdir(parents=True)
        for key, value in (('idVendor', vid), ('idProduct', pid), ('manufacturer', maker), ('product', product),
                           ('serial', 'SECRET123'), ('bcdDevice', '0419'), ('speed', '5000')):
            (d/key).write_text(value + '\n')
        unit = bytes([26, 0x24, 0x06, 4]) + GUID + bytes([1, 1, 1, 1, 1, 0]) if xu else b''
        (d/'descriptors').write_bytes(bytes([18, 1]) + bytes(16) + bytes([9, 2]) + bytes(7) + unit)
        intf = d/f'{name}:1.0'; intf.mkdir()
        for key, value in (('bInterfaceNumber', '00'), ('bInterfaceClass', '0e'),
                           ('bInterfaceSubClass', '01'), ('bInterfaceProtocol', '00')):
            (intf/key).write_text(value + '\n')
        (intf/'driver').symlink_to(self.root.parent/'uvcvideo')
        (self.root.parent/'uvcvideo').mkdir(exist_ok=True)

    def test_report_lists_scanners_without_serials(self):
        text = survey.report(self.root, self.root/'none', self.root/'none')
        self.assertIn('USB 2bc5:0c0b  Creality Creality Pika', text)
        self.assertIn('USB 2bc5:0abc  Creality Sermoon S1', text)
        self.assertIn('interface 00: video (UVC) (class 0e/01/00), uvcvideo', text)
        self.assertIn('UVC extension unit 4: ' + GUID.hex(), text)
        self.assertNotIn('SECRET123', text)
        self.assertNotIn('Webcam', text)

    def test_other_scanners_excludes_the_pika(self):
        self.assertEqual(survey.other_scanners(self.root), ['Sermoon S1 (USB 2bc5:0abc)'])
        self.assertIn('No Creality', survey.report(Path(tempfile.mkdtemp()), self.root, self.root))

    def test_launch_explains_unsupported_scanner(self):
        c = {'data_dir': self.root.parent}
        quiet = SimpleNamespace(returncode=1)
        for others, message in ((['Sermoon S1 (USB 2bc5:0abc)'], 'only the Creality Pika is supported over USB'),
                                ([], 'No Creality Pika found')):
            with self.subTest(others=others), patch('usb.discover', return_value=[]), \
                 patch('usb.subprocess.run', return_value=quiet), \
                 patch('survey.other_scanners', return_value=others), \
                 self.assertRaisesRegex(RuntimeError, message):
                usb.prepare(c)


if __name__ == '__main__':
    unittest.main()
