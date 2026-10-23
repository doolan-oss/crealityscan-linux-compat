"""Scanner model profiles and the USB launch path for each model, using fake
sysfs trees and the Sermoon S1's V4L2 formats from issue #7."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tools/pika-recorder'), str(ROOT/'tests')]
import fakesysfs
import models
import survey
import usb

PIKA, S1 = models.MODELS['pika'], models.MODELS['sermoon-s1']
# The values the bridge and helpers used before profiles existed (helpers-v1).
PIKA_V1_MODES = (
    'GREY:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10;MJPG:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10',
    'YUYV:1280x960:60,50,40,30,20,15,10,5;MJPG:1280x960:60,50,40,30,20,15,10,5;'
    'NV12:1280x960:60,50,40,30,20,15,10,5;BGR3:1280x960:60,50,40,30,20,15,10,5')
PARSER = r'''
#include <stdio.h>
#include <string.h>
#include "scanner-profile.h"
/* defaults | modes TEXT | units TEXT | pid TEXT: prints what the C side parsed */
int main(int argc, char **argv) {
  (void)argc;
  if (!strcmp(argv[1], "defaults")) {
    printf("%s\n%s\n%s\n%04x\n", profile_default_modes[0], profile_default_modes[1], profile_default_units, profile_default_pid);
    return 0;
  }
  if (!strcmp(argv[1], "modes")) {
    profile_modes t;
    if (profile_parse_modes(argv[2], &t)) return 1;
    for (unsigned i = 0; i < t.count; i++) {
      printf("%s%.4s:%ux%u:", i ? ";" : "", (char *)&t.modes[i].fourcc, t.modes[i].width, t.modes[i].height);
      for (unsigned r = 0; r < t.modes[i].count; r++) printf("%s%u", r ? "," : "", t.modes[i].rates[r]);
    }
    return 0;
  }
  if (!strcmp(argv[1], "units")) {
    profile_units u;
    if (profile_parse_units(argv[2], &u)) return 1;
    for (unsigned i = 0; i < u.count; i++) {
      printf("%s%u:", i ? ";" : "", u.units[i].unit);
      for (unsigned b = 0; b < 16; b++) printf("%02x", u.units[i].guid[b]);
      printf(":%x", u.units[i].mask);
    }
    return 0;
  }
  unsigned pid;
  if (profile_parse_pid(argv[2], &pid)) return 1;
  printf("%04x", pid);
  return 0;
}
'''


class ProfileTests(unittest.TestCase):
    def test_pika_profile_reproduces_the_original_bridge_values(self):
        e = models.environment(PIKA, fakesysfs.descriptors(0x0c0b, ((4, fakesysfs.PIKA_GUID, 7),)))
        self.assertEqual((e['PIKA_MODES_0'], e['PIKA_MODES_1']), PIKA_V1_MODES)
        self.assertEqual(e['PIKA_XU'], '4:a15157a5c5f35e4a8d5a6854b8fa2716:7')
        self.assertEqual((e['PIKA_USB_PID'], e['PIKA_USB_PRODUCT'], e['PIKA_MODEL_NAME']), ('0c0b', 'Creality Pika', 'Pika'))
        self.assertFalse(PIKA.experimental)

    def test_s1_profile_matches_the_reported_camera_formats(self):
        listed = fakesysfs.formats_from_survey(fakesysfs.S1_SURVEY)
        for endpoint, node in enumerate(('/dev/video2', '/dev/video4')):
            camera = {(f, w, h, tuple(map(round, rates))) for _, f, _, sizes in listed[node] for w, h, rates in sizes}
            native = {(f, w, h, rates) for f, w, h, rates in S1.modes[endpoint] if f not in ('NV12', 'BGR3')}
            self.assertEqual(native, camera)
        decoded = {m[1:] for m in S1.modes[1] if m[0] in ('NV12', 'BGR3')}
        self.assertEqual(decoded, {m[1:] for m in S1.modes[1] if m[0] == 'MJPG'})
        self.assertTrue(S1.experimental)
        self.assertEqual(S1.pid, '0c06')

    def test_extension_unit_selectors_come_from_the_descriptors(self):
        raw = fakesysfs.descriptors(0x0c06, ((6, fakesysfs.S1_UNIT6_GUID, 0x1f), (4, fakesysfs.PIKA_GUID, 0x07)))
        self.assertEqual(models.extension_units(raw), {6: (fakesysfs.S1_UNIT6_GUID.hex(), 0x1f), 4: (fakesysfs.PIKA_GUID.hex(), 7)})
        # Unit 4 first: the SDK only addresses unit 4, as on the Pika.
        self.assertEqual(models.environment(S1, raw)['PIKA_XU'],
                         f'4:{fakesysfs.PIKA_GUID.hex()}:7;6:{fakesysfs.S1_UNIT6_GUID.hex()}:1f')
        with self.assertRaisesRegex(RuntimeError, 'unit 6 differs'):
            models.environment(S1, fakesysfs.descriptors(0x0c06, ((4, fakesysfs.PIKA_GUID, 7),)))

    @unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
    def test_c_parser_reads_every_profile_and_rejects_malformed_ones(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d)/'parser'
            (Path(d)/'parser.c').write_text(PARSER)
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-I', ROOT/'src/usb-bridge', Path(d)/'parser.c', '-o', exe], check=True)
            run = lambda *a: subprocess.run([exe, *a], capture_output=True, text=True)
            self.assertEqual(run('defaults').stdout.split('\n')[:4], [*PIKA_V1_MODES, '4:a15157a5c5f35e4a8d5a6854b8fa2716:7', '0c0b'])
            for model in models.MODELS.values():
                for endpoint in (0, 1):
                    text = models.encode_modes(model.modes[endpoint])
                    self.assertEqual(run('modes', text).stdout, text)
                    self.assertLessEqual(sum(len(m[3]) for m in model.modes[endpoint]), 64)  # PROFILE_MAX_TYPES
                xu = ';'.join(f'{u}:{g}:7' for u, g in model.units)
                self.assertEqual(run('units', xu).stdout, xu)
                self.assertEqual(run('pid', model.pid).stdout, model.pid)
            for bad in ('', 'GREY:1280x960:', 'GREY:1280x960:0', 'GRAY:1280x960:30', 'GREY:1280x:30', 'GREY:1280x960:30;',
                        'GREY:8x8:30', ';'.join(['MJPG:640x480:' + ','.join(['30'] * 16)] * 5)):
                self.assertEqual(run('modes', bad).returncode, 1, bad)
            for bad in ('4:a151:7', '0:' + '00' * 16 + ':7', '4:' + '00' * 16 + ':0', '4:' + '00' * 16 + ':123456789'):
                self.assertEqual(run('units', bad).returncode, 1, bad)
            for bad in ('c06', '0c0g', '00000c06', '0000'):
                self.assertEqual(run('pid', bad).returncode, 1, bad)


class LaunchTests(unittest.TestCase):
    """usb.prepare against fake sysfs trees: what the bridge and helpers are given."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.log = self.root/'log'; self.log.mkdir()
        self.config = {'data_dir': self.root, 'experimental_scanners': []}

    def prepare(self, device, formats=None, helper_ok=True, access=lambda node, mode: True):
        listed = formats or {}
        quiet = SimpleNamespace(returncode=1)
        checked = SimpleNamespace(returncode=0 if helper_ok else 2, stdout='PROFILE scanner 2bc5:0c06\n')
        def run(cmd, **kwargs):
            return checked if cmd[-1] == '--check-profile' else quiet
        with patch.object(usb, 'V4L', self.root/'class/video4linux'), patch.object(usb, 'HIDRAW', self.root/'class/hidraw'), \
             patch('usb.subprocess.run', side_effect=run), patch('usb.os.access', side_effect=access), \
             patch('survey.enumerate_formats', side_effect=lambda node: listed.get(node, [])), \
             patch('survey.report', return_value='SURVEY REPORT'):
            e, nodes, lock = usb.prepare(self.config, self.log)
        lock.close()
        return e, nodes

    def test_pika_launch_environment_is_unchanged(self):
        device = fakesysfs.pika(self.root)
        e, nodes = self.prepare(device)
        self.assertEqual((e['PIKA_MODES_0'], e['PIKA_MODES_1']), PIKA_V1_MODES)
        self.assertEqual(e['PIKA_XU'], '4:a15157a5c5f35e4a8d5a6854b8fa2716:7')
        self.assertEqual((e['PIKA_CAMERA_NAME_0'], e['PIKA_CAMERA_NAME_1']), ('Creality Pika Depth Camera', 'Creality Pika RGB Camera'))
        self.assertEqual((e['PIKA_NODE_0'], e['PIKA_METADATA_1']), ('/dev/video0', '/dev/video3'))
        self.assertEqual(nodes, ['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3', '/dev/hidraw10'])
        self.assertIn('Scanner: Creality Pika, USB 2bc5:0c0b', (self.log/'scanner.txt').read_text())

    def test_s1_needs_the_experimental_setting(self):
        fakesysfs.scanner(self.root)
        with self.assertRaisesRegex(RuntimeError, r'experimental.*creality.py experimental sermoon-s1'):
            self.prepare(None)

    def test_s1_launch_environment(self):
        device = fakesysfs.scanner(self.root)
        self.config['experimental_scanners'] = ['sermoon-s1']
        listed = fakesysfs.formats_from_survey(fakesysfs.S1_SURVEY)
        e, nodes = self.prepare(device, listed)
        self.assertEqual((e['PIKA_USB_PID'], e['PIKA_USB_PRODUCT'], e['PIKA_MODEL_NAME']), ('0c06', 'Creality Sermoon S1', 'Sermoon S1'))
        self.assertEqual(e['PIKA_MODES_0'], 'GREY:1280x800:30,25,20,15,10;GREY:1280x960:30,25,20,15,10;'
                                            'GREY:1600x1200:90,80,70,60,50,40,30,15,10')
        self.assertTrue(e['PIKA_MODES_1'].startswith('YUYV:1920x1080:15,10,5;YUYV:1920x1200:15,10,5;MJPG:1920x1080:30,15,10,5;'))
        self.assertIn('BGR3:1920x1200:30,15,10,5', e['PIKA_MODES_1'])
        self.assertEqual(e['PIKA_XU'], f'4:{fakesysfs.PIKA_GUID.hex()}:7;6:{fakesysfs.S1_UNIT6_GUID.hex()}:1f')
        self.assertEqual(e['PIKA_CAMERA_NAME_0'], 'Creality Sermoon S1 Depth Camera')
        self.assertEqual((e['PIKA_USB_SERIAL'], e['PIKA_USB_REVISION'], e['PIKA_USB_PORT'], e['PIKA_USB_PORTS']), ('S1SERIAL42', '1049', '2', '4'))
        self.assertEqual(e['PIKA_USB_STRING_2'], 'Creality Sermoon S1')
        self.assertEqual(nodes, ['/dev/video2', '/dev/video3', '/dev/video4', '/dev/video5', '/dev/hidraw10'])
        report = (self.log/'scanner.txt').read_text()
        self.assertIn('Scanner: Creality Sermoon S1 (experimental), USB 2bc5:0c06', report)
        self.assertNotIn('does not list', report)
        self.assertNotIn('S1SERIAL42', report)

    def test_s1_log_notes_formats_the_camera_does_not_list(self):
        device = fakesysfs.scanner(self.root)
        self.config['experimental_scanners'] = ['sermoon-s1']
        listed = fakesysfs.formats_from_survey(fakesysfs.S1_SURVEY.replace('1600x1200@90/80', '1600x1200@80'))
        self.prepare(device, listed)
        self.assertIn('endpoint 0: camera does not list GREY 1600x1200 at 90 fps', (self.log/'scanner.txt').read_text())

    def test_blocked_hid_node_named_with_the_fix(self):
        import onboard
        device = fakesysfs.scanner(self.root)
        self.config['experimental_scanners'] = ['sermoon-s1']
        denied = lambda node, mode: 'hidraw' not in node
        for installed, start in ((False, 'Scanner access blocked: /dev/hidraw10. Fix once in a terminal, then unplug and replug'),
                                 (True, 'Scanner access blocked: /dev/hidraw10. Unplug and replug the scanner.')):
            with self.subTest(rule_installed=installed), patch('onboard.udev_rule_installed', return_value=installed), \
                 self.assertRaises(RuntimeError) as raised:
                self.prepare(device, access=denied)
            message = str(raised.exception)
            self.assertTrue(message.startswith(start), message)
            self.assertTrue(message.endswith(onboard.access_command()), message)

    def test_old_helpers_are_reported_for_the_s1(self):
        device = fakesysfs.scanner(self.root)
        self.config['experimental_scanners'] = ['sermoon-s1']
        with self.assertRaisesRegex(RuntimeError, 'do not support the Creality Sermoon S1.*setup'):
            self.prepare(device, helper_ok=False)

    def test_unknown_and_missing_scanners_are_explained(self):
        quiet = SimpleNamespace(returncode=1)
        for others, message in ((['Lizard (USB 2bc5:0abc)'], 'covers only the Creality Pika'), ([], 'No supported Creality scanner')):
            with self.subTest(others=others), patch.object(usb, 'V4L', self.root/'none'), \
                 patch('usb.subprocess.run', return_value=quiet), patch('survey.other_scanners', return_value=others), \
                 self.assertRaisesRegex(RuntimeError, message):
                usb.prepare(self.config)


if __name__ == '__main__':
    unittest.main()
