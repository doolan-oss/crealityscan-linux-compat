"""Display selection and the exports folder, using synthetic sockets and prefixes."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import common
import display
import exports
import integrity


def listen(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    return s


class DisplayTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.x11 = self.root/'x11'; self.x11.mkdir()
        patched = patch.object(display, 'X11_DIR', self.x11)
        patched.start(); self.addCleanup(patched.stop)

    def test_desktop_uses_only_the_current_socket_and_cookie(self):
        sock = listen(self.x11/'X5'); self.addCleanup(sock.close)
        cookie = self.root/'cookie'; cookie.write_text('secret')
        d = display.desktop({'DISPLAY': ':5.0', 'XAUTHORITY': str(cookie)})
        self.assertEqual(d, display.Display(':5', self.x11/'X5', cookie))
        c = {'runner': Path('/runner'), 'data_dir': Path('/state'), 'prefix': Path('/state/prefix')}
        e = {}
        cmd = common.sandbox(c, Path('/log'), e, display=d, gpu=False)
        binds = [cmd[i:i+3] for i in range(len(cmd)-2)]
        self.assertIn(['--ro-bind', str(self.x11/'X5'), str(self.x11/'X5')], binds)
        self.assertIn(['--ro-bind', str(cookie), '/run/xauthority'], binds)
        self.assertEqual((e['DISPLAY'], e['XAUTHORITY']), (':5', '/run/xauthority'))
        self.assertNotIn(str(self.x11), cmd)
        self.assertFalse(any('WAYLAND' in str(x) for x in cmd))

    def test_desktop_refuses_missing_or_remote_display(self):
        for env in ({}, {'DISPLAY': 'host:0'}, {'DISPLAY': ':9'}):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                display.desktop(env)

    def test_isolated_requires_satellite(self):
        with patch('display.shutil.which', return_value=None), \
             self.assertRaisesRegex(RuntimeError, 'xwayland-satellite'):
            with display.isolated(self.root):
                pass

    def fake_satellite(self, body):
        exe = self.root/'bin/xwayland-satellite'; exe.parent.mkdir(exist_ok=True)
        exe.write_text(f'#!{sys.executable}\n' + textwrap.dedent(body))
        exe.chmod(0o755)
        return exe

    def test_isolated_waits_for_ready_and_stops_server(self):
        exe = self.fake_satellite('''
            import os, signal, socket, sys, time
            x = socket.socket(socket.AF_UNIX); x.bind(os.environ['FAKE_X11'] + '/X' + sys.argv[1][1:])
            n = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); n.sendto(b'READY=1', os.environ['NOTIFY_SOCKET'])
            signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
            time.sleep(60)
        ''')
        spawned, real = [], display.subprocess.Popen
        def spawn(*args, **kwargs):
            spawned.append((real(*args, **kwargs), kwargs['env'])); return spawned[-1][0]
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-test', 'FAKE_X11': str(self.x11)}), \
             patch('display.shutil.which', return_value=str(exe)), \
             patch('display.subprocess.Popen', side_effect=spawn):
            with display.isolated(self.root) as d:
                self.assertTrue(d.socket.is_socket())
                self.assertEqual((d.name, d.xauthority), (':' + d.socket.name[1:], None))
        proc, env = spawned[0]
        self.assertIsNotNone(proc.poll())
        self.assertNotIn('DISPLAY', env)

    def test_isolated_reports_early_exit(self):
        exe = self.fake_satellite('import sys; sys.exit(3)\n')
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-test'}), \
             patch('display.shutil.which', return_value=str(exe)), \
             self.assertRaisesRegex(RuntimeError, 'exited'):
            with display.isolated(self.root):
                pass


class ExportsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_exports_dir_must_be_dedicated(self):
        home = self.root/'home'; data = self.root/'state'; source = self.root/'source'
        with patch.dict(os.environ, {'HOME': str(home)}):
            for bad in (home, self.root, Path('/'), data/'x', source, 'relative'):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    exports.check_dir(bad, (data, source))
            self.assertEqual(exports.check_dir(home/'Documents/CrealityScan', (data, source)),
                             home/'Documents/CrealityScan')

    def test_exports_mount_only_when_requested(self):
        c = {'runner': Path('/runner'), 'data_dir': Path('/state'), 'prefix': Path('/state/prefix')}
        self.assertNotIn(exports.EXPORTS_MOUNT, common.sandbox(c, Path('/log'), {}, gpu=False))
        cmd = common.sandbox(c, Path('/log'), {}, gpu=False, exports=Path('/media/scans/CrealityScan'))
        self.assertIn(['--bind', '/media/scans/CrealityScan', exports.EXPORTS_MOUNT],
                      [cmd[i:i+3] for i in range(len(cmd)-2)])

    def profiles(self):
        prefix = self.root/'prefix'; users = prefix/'drive_c/users'
        out = self.root/'exports'; out.mkdir()
        return prefix, users, out

    def test_folders_move_into_exports_and_link(self):
        prefix, users, out = self.profiles()
        (users/'empty/Documents/Music/deep').mkdir(parents=True)
        (users/'used/Documents').mkdir(parents=True); (users/'used/Documents/scan.stl').write_text('mesh')
        projects = users/'used/AppData/Local/Creality/CrealityScan/Projects'
        (projects/'Project_1/result').mkdir(parents=True); (projects/'Project_1/result/Mesh.ply').write_text('data')
        outside = self.root/'outside'; outside.mkdir(); (outside/'secret').write_text('keep')
        (users/'moved').mkdir(); (users/'moved/Documents').symlink_to(outside, target_is_directory=True)
        (users/'Public/Documents').mkdir(parents=True)
        kept, moved = exports.link_folders(prefix, out)
        self.assertEqual((kept, sorted(moved)), ([], ['Project_1', 'scan.stl']))
        for name in ('empty', 'used', 'moved'):
            self.assertEqual(os.readlink(users/name/'Documents'), exports.EXPORTS_MOUNT)
            self.assertEqual(os.readlink(users/name/'AppData/Local/Creality/CrealityScan/Projects'),
                             exports.EXPORTS_MOUNT + '/Projects')
        self.assertEqual((out/'scan.stl').read_text(), 'mesh')
        self.assertEqual((out/'Projects/Project_1/result/Mesh.ply').read_text(), 'data')
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['Projects', 'scan.stl'])
        self.assertEqual((outside/'secret').read_text(), 'keep')
        self.assertFalse((users/'Public/Documents').is_symlink())
        self.assertEqual(exports.link_folders(prefix, out), ([], []))

    def test_name_clash_and_failed_move_keep_everything(self):
        prefix, users, out = self.profiles()
        docs = users/'steamuser/Documents'; docs.mkdir(parents=True)
        (docs/'a.stl').write_text('prefix a'); (docs/'b.stl').write_text('prefix b')
        (out/'b.stl').write_text('user b')
        kept, moved = exports.link_folders(prefix, out)
        self.assertEqual((kept, moved), (['steamuser/Documents'], []))
        self.assertEqual(sorted(p.name for p in docs.iterdir()), ['a.stl', 'b.stl'])
        self.assertEqual((out/'b.stl').read_text(), 'user b')
        (out/'b.stl').unlink()
        real, calls = os.rename, []
        def flaky(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise OSError('simulated failure')
            return real(*args, **kwargs)
        with patch('exports.os.rename', side_effect=flaky):
            self.assertEqual(exports.link_folders(prefix, out)[0], ['steamuser/Documents'])
        self.assertFalse(docs.is_symlink())
        self.assertEqual([(p.name, p.read_text()) for p in sorted(docs.iterdir())],
                         [('a.stl', 'prefix a'), ('b.stl', 'prefix b')])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['Projects'])

    def test_unexpected_profile_link_is_not_followed(self):
        prefix, users, out = self.profiles()
        outside = self.root/'outside'; outside.mkdir()
        (users/'steamuser/AppData').mkdir(parents=True)
        (users/'steamuser/AppData/Local').symlink_to(outside, target_is_directory=True)
        kept, _ = exports.link_folders(prefix, out)
        self.assertEqual(kept, ['steamuser/AppData/Local/Creality/CrealityScan/Projects'])
        self.assertEqual(list(outside.iterdir()), [])

    def test_integrity_accepts_only_exports_links(self):
        c = {'data_dir': self.root/'state', 'prefix': self.root/'state/prefix'}
        app = c['prefix']/'drive_c/Program Files/CrealityScan'; app.mkdir(parents=True)
        for name in ('CrealityScan.exe', 'pikacam.dll', 'mf.dll'):
            (app/name).write_bytes(b'fixture')
        (c['prefix']/'drive_c/users/steamuser/Documents').mkdir(parents=True)
        out = self.root/'exports'; out.mkdir()
        with patch.object(integrity, 'TRUST_ROOT', self.root/'trust'):
            integrity.save_installation(c, {})
            self.assertEqual(exports.link_folders(c['prefix'], out), ([], []))
            self.assertEqual(len(integrity.verify_installation(c, {})), 3)
            other = c['prefix']/'drive_c/users/steamuser/Desktop'
            other.symlink_to(self.root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'External'):
                integrity.verify_installation(c, {})

if __name__ == '__main__':
    unittest.main()
