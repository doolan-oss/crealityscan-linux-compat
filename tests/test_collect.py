"""Collecting logs for a bug report: newest session only, serials removed,
links planted by the app not followed."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import collect


class CollectTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        data = self.root/'data'
        self.c = {'data_dir': data, 'prefix': data/'prefix'}
        old, new = data/'logs/20261020-100000-000001-usb', data/'logs/20261021-174547-065691-usb'
        for folder in (old, new, data/'logs/20261022-090000-000001-opencl-probe.exe'):
            folder.mkdir(parents=True)
        (old/'wine.log').write_text('older session\n')
        (new/'wine.log').write_text('[pika-camera-bridge] enumeration: \\\\?\\usb#vid_2bc5&pid_0c06&mi_00#1049&S1SERIAL42&0&0&0#{x}\n'
                                    f'path {Path.home()}/.local/share/crealityscan-linux\n')
        (new/'frames.log').write_text('x' * (collect.LIMIT + 10) + 'END\n')
        app = self.c['prefix']/'drive_c/users/steamuser'/collect.APP_LOGS
        (app/'20261020100000').mkdir(parents=True)
        session = app/'20261021174550'; session.mkdir()
        (session/'ScannerStreamSDK.log').write_text('Device created successfully! Name: Creality Sermoon S1, PID: 0x0c06, SN/ID: S1SERIAL42\n'
                                                    'Pipeline created with device: {name: Creality Sermoon S1, sn: S1SERIAL42}\nSN: unknown\n'
                                                    '[Debug] GetDeviceWifiPassword : hunter2!\n\twifiBridgeSsid:HomeNet,\n'
                                                    'WiFiGetCurrentSSID failed: initialize failed\n')
        (session/'device_info.json').write_text('{"serialNumber": "OTHER123XYZ"}')
        secret = self.root/'secret.txt'; secret.write_text('do not share')
        (session/'planted.log').symlink_to(secret)
        (session/'Native').mkdir()

    def test_newest_session_bundled_and_redacted(self):
        target, launch, app = collect.collect(self.c, ['CONNECTED99'], self.root)
        self.assertEqual((launch.name, app.name), ('20261021-174547-065691-usb', '20261021174550'))
        with zipfile.ZipFile(target) as z:
            files = {n: z.read(n).decode() for n in z.namelist()}
        self.assertEqual(sorted(files), ['app-20261021174550/ScannerStreamSDK.log', 'app-20261021174550/device_info.json',
                                         'launch-20261021-174547-065691-usb/frames.log', 'launch-20261021-174547-065691-usb/wine.log'])
        everything = ''.join(files.values())
        for secret in ('S1SERIAL42', 'OTHER123XYZ', 'do not share', 'older session', str(Path.home()), 'hunter2', 'HomeNet'):
            self.assertNotIn(secret, everything)
        self.assertIn('SN/ID: SERIAL', everything)
        self.assertIn('SN: unknown', everything)
        self.assertIn('GetDeviceWifiPassword : REMOVED', everything)
        self.assertIn('WiFiGetCurrentSSID failed: initialize failed', everything)
        self.assertIn('path ~/.local/share', everything)
        frames = files['launch-20261021-174547-065691-usb/frames.log']
        self.assertTrue(frames.startswith('[first 14 bytes left out]') and frames.endswith('END\n'))

    def test_logs_and_experimental_commands(self):
        import json, subprocess
        config = self.root/'config.json'
        c = json.loads((ROOT/'config/config.example.json').read_text())
        for key in ('runner', 'installer', 'dxvk_dir'):
            c[key] = str(self.root/key)
        c['data_dir'] = str(self.root/'empty-data')
        config.write_text(json.dumps(c))
        run = lambda *a: subprocess.run([sys.executable, ROOT/'scripts/creality.py', '--config', config, *a],
                                        capture_output=True, text=True, cwd=self.root)
        r = run('logs')
        self.assertEqual(r.returncode, 1)
        self.assertIn('No logs found', r.stderr)
        r = run('experimental')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('sermoon-s1: Creality Sermoon S1 (USB 2bc5:0c06), off', r.stdout)
        self.assertEqual(run('experimental', 'sermoon-s1').returncode, 0)
        self.assertIn('sermoon-s1', json.loads(config.read_text())['experimental_scanners'])
        for command in ('launch', 'smoke'):  # refused cleanly by the runner check, not a Python error
            self.assertIn('Refused/failed: Complete Wine runner', run(command).stderr)

    def test_nothing_to_collect(self):
        with self.assertRaisesRegex(RuntimeError, 'No logs found'):
            collect.collect({'data_dir': self.root/'none', 'prefix': self.root/'none/prefix'}, [], self.root)


if __name__ == '__main__':
    unittest.main()
