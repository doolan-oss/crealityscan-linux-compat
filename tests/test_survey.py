"""Scanner survey, using a fake sysfs tree."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tools/pika-recorder')]
import survey

GUID = bytes.fromhex('a15157a5c5f35e4a8d5a6854b8fa2716')


class SurveyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)/'usb'
        self.device('1-2', '2bc5', '0c0b', 'Creality', 'Creality Pika', xu=True)
        self.device('1-3', '2bc5', '0abc', 'Creality', 'Lizard')
        self.device('1-4', '046d', '0825', 'Logitech', 'HD Webcam')
        self.device('1-5', '2bc5', '0c06', 'Creality', 'Creality Sermoon S1', xu=True)

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
        self.assertIn('USB 2bc5:0abc  Creality Lizard', text)
        self.assertIn('USB 2bc5:0c06  Creality Creality Sermoon S1', text)
        self.assertIn('interface 00: video (UVC) (class 0e/01/00), uvcvideo', text)
        self.assertIn('UVC extension unit 4: ' + GUID.hex() + ' (selectors 1)', text)
        self.assertNotIn('SECRET123', text)
        self.assertNotIn('Webcam', text)

    def test_other_scanners_excludes_known_models(self):
        self.assertEqual(survey.other_scanners(self.root), ['Lizard (USB 2bc5:0abc)'])
        with tempfile.TemporaryDirectory() as empty:
            self.assertIn('No Creality', survey.report(Path(empty), self.root, self.root))


if __name__ == '__main__':
    unittest.main()
