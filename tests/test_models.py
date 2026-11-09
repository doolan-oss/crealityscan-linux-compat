"""Scanner model profiles and the USB launch path for each model, using fake
sysfs trees and the V4L2 formats of the Sermoon S1 (issue #7) and the CR-Scan
Otter (issue #10)."""
import os
import io
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

PIKA, S1, OTTER = models.MODELS['pika'], models.MODELS['sermoon-s1'], models.MODELS['otter']
U4, U8, U12 = (g.hex() for g in (fakesysfs.PIKA_GUID, fakesysfs.ORBB_1_GUID, fakesysfs.ORBB_2_GUID))
# Every variable models.environment() set for two-camera models before the Otter;
# the bridge's defaults cover the rest, so these must stay all there is.
TWO_CAMERA_KEYS = {'PIKA_USB_PID', 'PIKA_USB_PRODUCT', 'PIKA_MODEL_NAME', 'PIKA_MODES_0', 'PIKA_MODES_1', 'PIKA_XU'}
# The values the bridge and helpers used before profiles existed (helpers-v1).
PIKA_V1_MODES = (
    'GREY:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10;MJPG:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10',
    'YUYV:1280x960:60,50,40,30,20,15,10,5;MJPG:1280x960:60,50,40,30,20,15,10,5;'
    'NV12:1280x960:60,50,40,30,20,15,10,5;BGR3:1280x960:60,50,40,30,20,15,10,5')
PARSER = r'''
#include <stdio.h>
#include <string.h>
#include "scanner-profile.h"
/* defaults | limits | modes TEXT | units TEXT | endpoint-units TEXT | cameras TEXT | pid TEXT:
 * prints what the C side parsed */
int main(int argc, char **argv) {
  (void)argc;
  if (!strcmp(argv[1], "defaults")) {
    printf("%s\n%s\n%s\n%04x\n%u\n%s\n", profile_default_modes_for(0), profile_default_modes_for(1), profile_default_units,
           profile_default_pid, profile_default_cameras, profile_default_modes_for(2) ? "endpoint 2 has a default" : "-");
    return 0;
  }
  if (!strcmp(argv[1], "limits")) {
    printf("%d %d %d", PROFILE_MAX_CAMERAS, PROFILE_MAX_MODES, PROFILE_MAX_TYPES);
    return 0;
  }
  if (!strcmp(argv[1], "cameras")) {
    unsigned n;
    if (profile_parse_cameras(argv[2], &n)) return 1;
    printf("%u", n);
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
  if (!strcmp(argv[1], "units") || !strcmp(argv[1], "endpoint-units")) {
    profile_units u;
    if (argv[1][0] == 'u' ? profile_parse_units(argv[2], &u) : profile_parse_endpoint_units(argv[2], &u)) return 1;
    if (!u.count) printf("no units");
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

    def test_two_camera_models_get_no_new_settings(self):
        pika = models.environment(PIKA, fakesysfs.descriptors(0x0c0b, ((4, fakesysfs.PIKA_GUID, 7),)))
        self.assertEqual(set(pika), TWO_CAMERA_KEYS)
        self.assertEqual(set(models.environment(S1, fakesysfs.S1_DESCRIPTORS)), TWO_CAMERA_KEYS)
        self.assertEqual(models.camera_keys(PIKA), ['0:0', '0:1', '2:0', '2:1'])
        self.assertFalse(PIKA.units_per_camera or S1.units_per_camera)
        self.assertTrue(PIKA.needs_metadata and S1.needs_metadata)

    def test_otter_profile_matches_the_reported_camera_formats(self):
        listed = fakesysfs.formats_from_survey(fakesysfs.OTTER_SURVEY)
        for endpoint, node in enumerate(('/dev/video0', '/dev/video2', '/dev/video4')):
            # Same formats, sizes and rates, in the order the camera lists them.
            camera = [(f, w, h, tuple(map(round, rates))) for _, f, _, sizes in listed[node] for w, h, rates in sizes]
            native = [m for m in OTTER.modes[endpoint] if m[0] not in ('NV12', 'BGR3')]
            self.assertEqual(native, camera)
        decoded = [m[1:] for m in OTTER.modes[2] if m[0] in ('NV12', 'BGR3')]
        self.assertEqual(decoded, 2 * [m[1:] for m in OTTER.modes[2] if m[0] == 'MJPG'])
        self.assertEqual((OTTER.pid, OTTER.experimental, OTTER.units_per_camera, OTTER.needs_metadata), ('06da', True, True, False))
        self.assertEqual(models.camera_keys(OTTER), ['0:0', '0:1', '2:0', '2:1', '4:0', '4:1'])

    def test_otter_cameras_each_get_their_own_extension_units(self):
        e = models.environment(OTTER, fakesysfs.descriptors(0x06da, None, per_camera=fakesysfs.OTTER_UNITS))
        self.assertEqual(set(e) - TWO_CAMERA_KEYS, {'PIKA_MODES_2', 'PIKA_CAMERAS', 'PIKA_XU_0', 'PIKA_XU_1', 'PIKA_XU_2',
                                                     'PIKA_METADATA_REQUIRED'})
        self.assertEqual((e['PIKA_CAMERAS'], e['PIKA_METADATA_REQUIRED']), ('3', '0'))
        # The SDK sends its vendor commands to a camera's last vendor-specific node:
        # unit 4 on the depth camera, as on Windows.
        self.assertEqual((e['PIKA_XU_0'], e['PIKA_XU_1'], e['PIKA_XU_2']), (f'4:{U4}:7', f'8:{U8}:3', f'12:{U12}:3'))
        self.assertTrue(e['PIKA_MODES_0'].startswith('Y10 :320x200:30,20,15,10,5;Y10 :640x400:'))
        self.assertEqual(e['PIKA_MODES_0'], e['PIKA_MODES_1'])
        self.assertIn('BGR3:1920x1080:30,20,15,10,5', e['PIKA_MODES_2'])
        self.assertEqual(models.unit_report(OTTER, models.camera_units(fakesysfs.descriptors(0x06da, None, per_camera=fakesysfs.OTTER_UNITS))),
                         ([f'camera 0 (interface 0): unit 4 {U4} selectors 1,2,3', f'camera 1 (interface 2): unit 8 {U8} selectors 1,2',
                           f'camera 2 (interface 4): unit 12 {U12} selectors 1,2'], []))

    def test_otter_unit_layouts_other_than_expected_still_launch(self):
        u4, u8, u12 = (4, fakesysfs.PIKA_GUID, 0), (8, fakesysfs.ORBB_1_GUID, 0x3), (12, fakesysfs.ORBB_2_GUID, 0)
        # All units on the depth camera, in the device's order, and none on the colour camera.
        raw = fakesysfs.descriptors(0x06da, None, per_camera=((u8, u4), (u12,), ()))
        e = models.environment(OTTER, raw)
        self.assertEqual((e['PIKA_XU_0'], e['PIKA_XU_1'], e['PIKA_XU_2']), (f'8:{U8}:3;4:{U4}:ffffffff', f'12:{U12}:ffffffff', 'none'))
        self.assertEqual(models.unit_report(OTTER, models.camera_units(raw))[1],
                         ['camera 0: extension unit 4 reports no controls', 'camera 1: extension unit 12 reports no controls'])
        other = fakesysfs.descriptors(0x06da, None, per_camera=(((4, fakesysfs.S1_UNIT6_GUID, 7),), (u8,), ()))
        self.assertEqual(models.environment(OTTER, other)['PIKA_XU_0'], 'none')
        self.assertEqual(models.unit_report(OTTER, models.camera_units(other))[1],
                         ['camera 0: extension unit 4 differs from the known hardware', 'extension unit 12 is on no camera'])

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

    def test_extension_units_are_read_per_camera(self):
        u6, u4 = fakesysfs.S1_UNIT6_GUID.hex(), fakesysfs.PIKA_GUID.hex()
        raw = fakesysfs.descriptors(0x0c06, ((6, fakesysfs.S1_UNIT6_GUID, 0x1f), (4, fakesysfs.PIKA_GUID, 0x07)),
                                    ((6, fakesysfs.S1_UNIT6_GUID, 0x03), (4, fakesysfs.PIKA_GUID, 0)))
        self.assertEqual(models.camera_units(raw), [(0, [(6, u6, 0x1f), (4, u4, 7)]), (2, [(6, u6, 3), (4, u4, 0)])])
        lines, problems = models.unit_report(S1, models.camera_units(raw))
        self.assertEqual(lines, [f'camera 0 (interface 0): unit 6 {u6} selectors 1,2,3,4,5; unit 4 {u4} selectors 1,2,3',
                                 f'camera 1 (interface 2): unit 6 {u6} selectors 1,2; unit 4 {u4} selectors no controls'])
        self.assertEqual(problems, ['camera 1: extension unit 4 reports no controls'])

    def test_s1_with_controls_missing_on_one_or_both_cameras_still_gets_a_profile(self):
        u6, u4 = (6, fakesysfs.S1_UNIT6_GUID, 0x1f), (4, fakesysfs.PIKA_GUID, 0)
        rgb_only = fakesysfs.descriptors(0x0c06, ((6, fakesysfs.S1_UNIT6_GUID, 0x1f), (4, fakesysfs.PIKA_GUID, 7)), (u6, u4))
        both = fakesysfs.descriptors(0x0c06, (u6, u4))
        # Units in the device's order; the bridge gets one mask per unit: what any
        # camera lists, or every selector if none lists one.
        for raw, mask, problems in ((rgb_only, '7', ['camera 1: extension unit 4 reports no controls']),
                                    (both, 'ffffffff', ['camera 0: extension unit 4 reports no controls',
                                                        'camera 1: extension unit 4 reports no controls'])):
            with self.subTest(mask=mask):
                self.assertEqual(models.environment(S1, raw)['PIKA_XU'],
                                 f'6:{fakesysfs.S1_UNIT6_GUID.hex()}:1f;4:{fakesysfs.PIKA_GUID.hex()}:{mask}')
                self.assertEqual(models.unit_report(S1, models.camera_units(raw))[1], problems)
        missing6 = fakesysfs.descriptors(0x0c06, ((4, fakesysfs.PIKA_GUID, 7),))
        self.assertEqual(models.environment(S1, missing6)['PIKA_XU'], f'4:{fakesysfs.PIKA_GUID.hex()}:7')
        self.assertIn('camera 0: extension unit 6 differs from the known hardware',
                      models.unit_report(S1, models.camera_units(missing6))[1])

    def test_topology_nodes_follow_the_real_device_order(self):
        # The SDK opens the vendor protocol (unit 4) at topology node 1 on the S1 and node 0
        # on the Pika; on Windows nodes follow the descriptors, where the S1 lists unit 6 first.
        u6, u4 = fakesysfs.S1_UNIT6_GUID.hex(), fakesysfs.PIKA_GUID.hex()
        self.assertEqual(models.camera_units(fakesysfs.S1_DESCRIPTORS), [(0, [(6, u6, 0), (4, u4, 7)]), (2, [(6, u6, 0), (4, u4, 0)])])
        self.assertEqual(models.environment(S1, fakesysfs.S1_DESCRIPTORS)['PIKA_XU'], f'6:{u6}:ffffffff;4:{u4}:7')
        pika = models.environment(PIKA, fakesysfs.descriptors(0x0c0b, ((4, fakesysfs.PIKA_GUID, 7),)))
        self.assertEqual(pika['PIKA_XU'], f'4:{u4}:7')

    def test_pika_still_refuses_extension_units_that_differ(self):
        good = ((4, fakesysfs.PIKA_GUID, 7),)
        for rgb, message in ((((4, fakesysfs.PIKA_GUID, 0),), 'camera 1: extension unit 4 reports no controls'),
                             (((5, fakesysfs.PIKA_GUID, 7),), 'camera 1: extension unit 4 differs')):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, 'Creality Pika: ' + message):
                models.environment(PIKA, fakesysfs.descriptors(0x0c0b, good, rgb))

    @unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
    def test_c_parser_reads_every_profile_and_rejects_malformed_ones(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d)/'parser'
            (Path(d)/'parser.c').write_text(PARSER)
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-I', ROOT/'src/usb-bridge', Path(d)/'parser.c', '-o', exe], check=True)
            run = lambda *a: subprocess.run([exe, *a], capture_output=True, text=True)
            self.assertEqual(run('defaults').stdout.split('\n')[:6], [*PIKA_V1_MODES, '4:a15157a5c5f35e4a8d5a6854b8fa2716:7', '0c0b', '2', '-'])
            cameras, max_modes, max_types = map(int, run('limits').stdout.split())
            for model in models.MODELS.values():
                self.assertLessEqual(len(model.modes), cameras)
                for modes in model.modes:
                    text = models.encode_modes(modes)
                    self.assertEqual(run('modes', text).stdout, text)
                    self.assertLessEqual(len(modes), max_modes)
                    self.assertLessEqual(sum(len(m[3]) for m in modes), max_types)
                    self.assertLess(len(text), 4096)  # the bridge's buffer
                xu = ';'.join(f'{u}:{g}:7' for u, g in model.units)
                self.assertEqual(run('units', xu).stdout, xu)
                self.assertEqual(run('endpoint-units', xu).stdout, xu)
                self.assertEqual(run('pid', model.pid).stdout, model.pid)
            self.assertEqual(run('modes', 'Y10 :1280x800:30,5').stdout, 'Y10 :1280x800:30,5')
            self.assertEqual(run('endpoint-units', 'none').stdout, 'no units')
            self.assertEqual([run('cameras', n).stdout for n in ('2', '3', '4')], ['2', '3', '4'])
            for bad in ('', '1', '5', '03', '3 ', 'x'):
                self.assertEqual(run('cameras', bad).returncode, 1, bad)
            too_many_rates = ';'.join([f'MJPG:640x{480 + i}:' + ','.join(['30'] * 16) for i in range(max_types // 16 + 1)])
            for bad in ('', 'GREY:1280x960:', 'GREY:1280x960:0', 'GRAY:1280x960:30', 'GREY:1280x:30', 'GREY:1280x960:30;',
                        'GREY:8x8:30', 'Y10:1280x800:30', 'Y16 :1280x800:30', too_many_rates,
                        ';'.join(['GREY:640x480:30'] * (max_modes + 1))):
                self.assertEqual(run('modes', bad).returncode, 1, bad)
            for bad in ('4:a151:7', '0:' + '00' * 16 + ':7', '4:' + '00' * 16 + ':0', '4:' + '00' * 16 + ':123456789', 'none'):
                self.assertEqual(run('units', bad).returncode, 1, bad)
            for bad in ('', 'None', 'none;4:' + '00' * 16 + ':7'):
                self.assertEqual(run('endpoint-units', bad).returncode, 1, bad)
            for bad in ('c06', '0c0g', '00000c06', '0000'):
                self.assertEqual(run('pid', bad).returncode, 1, bad)

    @unittest.skipUnless(shutil.which('gcc') and Path('/usr/include/libyuv/convert.h').exists(), 'needs gcc and libyuv')
    def test_frame_helper_checks_every_camera_of_the_profile(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d)/'sdk-frame-helper'
            subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', ROOT/'src/usb-bridge/sdk-frame-helper.c', '-o', exe, '-lyuv'],
                           check=True)
            check = lambda env, *args: subprocess.run([exe, *(args or ['--check-profile'])], env={'PATH': '/usr/bin:/bin', **env},
                                                      capture_output=True, text=True)
            otter = models.environment(OTTER, fakesysfs.descriptors(0x06da, None, per_camera=fakesysfs.OTTER_UNITS))
            r = check(otter)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('PROFILE scanner 2bc5:06da, 3 cameras', r.stdout)
            self.assertIn('endpoint 0: Y10  320x200 at 30 20 15 10 5 fps', r.stdout)
            self.assertIn('endpoint 2: BGR3 1920x1080 at 30 20 15 10 5 fps', r.stdout)
            pika = check({})  # no profile: the Pika's built-in values
            self.assertEqual(pika.returncode, 0, pika.stderr)
            self.assertIn('PROFILE scanner 2bc5:0c0b, 2 cameras', pika.stdout)
            self.assertIn('endpoint 1: BGR3 1280x960 at 60 50 40 30 20 15 10 5 fps', pika.stdout)
            self.assertNotIn('endpoint 2', pika.stdout)
            self.assertEqual(check({k: v for k, v in otter.items() if k != 'PIKA_MODES_2'}).returncode, 2)
            self.assertEqual(check(dict(otter, PIKA_CAMERAS='9')).returncode, 2)
            # Serving needs one camera node per endpoint.
            self.assertEqual(check(dict(otter, PIKA_CAMERA_PORT='38999'), '/dev/null', '/dev/null').returncode, 2)


class LaunchTests(unittest.TestCase):
    """usb.prepare against fake sysfs trees: what the bridge and helpers are given."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.log = self.root/'log'; self.log.mkdir()
        self.config = {'data_dir': self.root, 'experimental_scanners': []}

    def prepare(self, device, formats=None, helper_ok=True, access=lambda node, mode: True, helper_cameras=None):
        listed = formats or {}
        quiet = SimpleNamespace(returncode=1)
        def run(cmd, **kwargs):
            if cmd[-1] != '--check-profile':
                return quiet
            # Like sdk-frame-helper: a line per mode of each endpoint it knows of.
            cameras = helper_cameras or int(kwargs['env'].get('PIKA_CAMERAS', '2'))
            return SimpleNamespace(returncode=0 if helper_ok else 2, stdout=f'PROFILE scanner 2bc5:{kwargs["env"]["PIKA_USB_PID"]}\n' +
                                   ''.join(f'endpoint {n}: GREY 640x480 at 30 fps\n' for n in range(cameras)))
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
        self.assertEqual(e['PIKA_XU'], f'6:{fakesysfs.S1_UNIT6_GUID.hex()}:1f;4:{fakesysfs.PIKA_GUID.hex()}:7')
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

    def test_real_s1_descriptors_launch(self):
        device = fakesysfs.scanner(self.root, raw=fakesysfs.S1_DESCRIPTORS)
        self.config['experimental_scanners'] = ['sermoon-s1']
        with patch('sys.stdout', io.StringIO()):
            e, nodes = self.prepare(device)
        self.assertEqual(e['PIKA_XU'], f'6:{fakesysfs.S1_UNIT6_GUID.hex()}:ffffffff;4:{fakesysfs.PIKA_GUID.hex()}:7')
        self.assertEqual(e['PIKA_USB_DESCRIPTOR'], fakesysfs.S1_DESCRIPTORS[:18].hex())
        report = (self.log/'scanner.txt').read_text()
        self.assertIn(f'camera 0 (interface 0): unit 6 {fakesysfs.S1_UNIT6_GUID.hex()} selectors no controls; '
                      f'unit 4 {fakesysfs.PIKA_GUID.hex()} selectors 1,2,3', report)
        self.assertIn('Warning: camera 1: extension unit 4 reports no controls', report)

    def test_s1_without_unit_4_controls_launches_with_warnings(self):
        device = fakesysfs.scanner(self.root, units=((6, fakesysfs.S1_UNIT6_GUID, 0x1f), (4, fakesysfs.PIKA_GUID, 0)))
        self.config['experimental_scanners'] = ['sermoon-s1']
        with patch('sys.stdout', io.StringIO()) as out:
            e, nodes = self.prepare(device)
        self.assertIn(f'4:{fakesysfs.PIKA_GUID.hex()}:ffffffff', e['PIKA_XU'])
        self.assertIn('Warning: Creality Sermoon S1 camera 1: extension unit 4 reports no controls; continuing', out.getvalue())
        report = (self.log/'scanner.txt').read_text()
        self.assertIn('Extension units:\ncamera 0 (interface 0): unit 6 ', report)
        self.assertIn(f'unit 4 {fakesysfs.PIKA_GUID.hex()} selectors no controls', report)
        self.assertIn('Warning: camera 0: extension unit 4 reports no controls\nWarning: camera 1:', report)

    def test_old_helpers_are_reported_for_the_s1(self):
        device = fakesysfs.scanner(self.root)
        self.config['experimental_scanners'] = ['sermoon-s1']
        with self.assertRaisesRegex(RuntimeError, 'do not support the Creality Sermoon S1.*setup'):
            self.prepare(device, helper_ok=False)

    def test_otter_needs_the_experimental_setting(self):
        fakesysfs.otter(self.root)
        with self.assertRaisesRegex(RuntimeError, r'CR-Scan Otter is experimental.*creality.py experimental otter'):
            self.prepare(None)

    def test_otter_launch_environment(self):
        device = fakesysfs.otter(self.root)
        self.config['experimental_scanners'] = ['otter']
        e, nodes = self.prepare(device, fakesysfs.formats_from_survey(fakesysfs.OTTER_SURVEY))
        self.assertEqual((e['PIKA_USB_PID'], e['PIKA_USB_PRODUCT'], e['PIKA_MODEL_NAME'], e['PIKA_CAMERAS']),
                         ('06da', 'Creality CR-Scan Otter', 'CR-Scan Otter', '3'))
        self.assertEqual([e[f'PIKA_NODE_{n}'] for n in range(3)], ['/dev/video0', '/dev/video2', '/dev/video4'])
        self.assertEqual([e[f'PIKA_METADATA_{n}'] for n in range(3)], ['/dev/video1', '/dev/video3', '/dev/video5'])
        self.assertEqual([e[f'PIKA_CAMERA_NAME_{n}'] for n in range(3)], ['CR-Scan Otter De', 'CR-Scan Otter IR', 'CR-Scan Otter RG'])
        self.assertEqual((e['PIKA_XU_0'], e['PIKA_XU_1'], e['PIKA_XU_2']), (f'4:{U4}:7', f'8:{U8}:3', f'12:{U12}:3'))
        self.assertEqual(e['PIKA_METADATA_REQUIRED'], '0')
        self.assertEqual((e['PIKA_USB_SERIAL'], e['PIKA_USB_REVISION']), ('OTTER7SERIAL', '1'))
        self.assertEqual(nodes, [f'/dev/video{n}' for n in range(6)] + ['/dev/hidraw7'])
        report = (self.log/'scanner.txt').read_text()
        self.assertIn('Scanner: Creality CR-Scan Otter (experimental), USB 2bc5:06da', report)
        self.assertIn('PIKA_CAMERAS=3', report)
        self.assertIn(f'PIKA_XU_2=12:{U12}:3', report)
        self.assertIn('endpoint 2: GREY 640x480 at 30 fps', report)
        self.assertNotIn('does not list', report)
        self.assertNotIn('Warning', report)
        self.assertNotIn('OTTER7SERIAL', report)

    def test_otter_log_notes_formats_the_camera_does_not_list(self):
        device = fakesysfs.otter(self.root)
        self.config['experimental_scanners'] = ['otter']
        listed = fakesysfs.formats_from_survey(fakesysfs.OTTER_SURVEY.replace('1920x1080@30/20/15/10/5, 640x360', '1920x1080@15/10/5, 640x360', 1))
        self.prepare(device, listed)
        self.assertIn('endpoint 2: camera does not list YUYV 1920x1080 at 30,20 fps', (self.log/'scanner.txt').read_text())

    def test_two_camera_helpers_are_refused_for_the_otter(self):
        device = fakesysfs.otter(self.root)
        self.config['experimental_scanners'] = ['otter']
        with self.assertRaisesRegex(RuntimeError, 'do not support the Creality CR-Scan Otter.*setup'):
            self.prepare(device, helper_cameras=2)

    def test_otter_with_a_missing_camera_node_is_explained(self):
        device = fakesysfs.otter(self.root)
        (self.root/'class/video4linux/video5').rename(self.root/'gone')
        self.config['experimental_scanners'] = ['otter']
        with self.assertRaisesRegex(RuntimeError, r'CR-Scan Otter is missing camera nodes \(4:1\); unplug and replug'):
            self.prepare(device)

    def test_unknown_and_missing_scanners_are_explained(self):
        quiet = SimpleNamespace(returncode=1)
        for others, message in ((['Lizard (USB 2bc5:0abc)'], 'covers only the Creality Pika'), ([], 'No supported Creality scanner')):
            with self.subTest(others=others), patch.object(usb, 'V4L', self.root/'none'), \
                 patch('usb.subprocess.run', return_value=quiet), patch('survey.other_scanners', return_value=others), \
                 self.assertRaisesRegex(RuntimeError, message):
                usb.prepare(self.config)


if __name__ == '__main__':
    unittest.main()
