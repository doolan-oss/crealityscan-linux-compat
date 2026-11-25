"""Setup helpers and pinned downloads, using local files instead of the network."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import common
import fetch
import integrity
import onboard


def sha(path):
    return common.digest(path)


def tar(path, members):
    with tarfile.open(path, 'w:gz') as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            elif isinstance(data, tuple):
                info.type = tarfile.SYMTYPE; info.linkname = data[1]
                t.addfile(info)
            else:
                info.size = len(data); t.addfile(info, io.BytesIO(data))
    return path


class FetchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_download_checks_hash_before_keeping_file(self):
        src = self.root/'pkg.tar.gz'; src.write_bytes(b'archive')
        out = self.root/'downloads'
        with self.assertRaisesRegex(RuntimeError, 'Checksum'):
            fetch.download(src.as_uri(), '0'*64, out)
        self.assertEqual(list(out.iterdir()), [])
        self.assertEqual(fetch.download(src.as_uri(), sha(src), out).read_bytes(), b'archive')

    def test_unpack_refuses_escapes_and_unexpected_layout(self):
        for members in ({'top/../../evil': b'x'}, {'/abs': b'x'}, {'top/link': ('sym', '/etc/passwd')},
                        {'top/a': b'x', 'other/b': b'y'}):
            with self.subTest(members=list(members)):
                archive = tar(self.root/'a.tar.gz', members)
                with self.assertRaises(Exception):
                    fetch.unpack(archive, self.root, 'top')
                self.assertFalse((self.root/'top').exists())
        self.assertFalse((self.root.parent/'evil').exists())
        archive = tar(self.root/'a.tar.gz', {'top': None, 'top/a': b'x', 'top/l': ('sym', 'a')})
        self.assertEqual((fetch.unpack(archive, self.root, 'top')/'l').read_bytes(), b'x')

    def helper_archive(self, extra=None, tamper=False):
        files = {n: n.encode() for n in fetch.BUILD_NAMES}
        manifest = {n: common.hashlib.sha256(d).hexdigest() for n, d in files.items()}
        if tamper:
            files['mf.dll'] = b'changed'
        members = {'manifest.json': json.dumps(manifest).encode(), **files,
                   'licenses/libyuv-copyright': b'BSD', **(extra or {})}
        return tar(self.root/'helpers.tar.gz', members)

    def test_prebuilt_helpers_checked_against_pin_and_manifest(self):
        build = self.root/'build'
        for kwargs, error in (({'extra': {'evil.so': b'x'}}, 'Unexpected'), ({'extra': {'licenses/a/b': b'x'}}, 'Unexpected'),
                              ({'tamper': True}, 'manifest')):
            with self.subTest(error=error):
                archive = self.helper_archive(**kwargs)
                pin = {'url': archive.as_uri(), 'sha256': sha(archive), 'version': 'test'}
                with patch.dict(fetch.LOCK, {'helpers': pin}), self.assertRaisesRegex(RuntimeError, error):
                    fetch.helpers(self.root/f'runtime-{len(error)}-{kwargs!r:.12}', build)
                self.assertFalse(build.exists())
        archive = self.helper_archive()
        pin = {'url': archive.as_uri(), 'sha256': sha(archive), 'version': 'test'}
        with patch.dict(fetch.LOCK, {'helpers': pin}):
            with self.assertRaisesRegex(RuntimeError, 'Checksum'), \
                 patch.dict(fetch.LOCK, {'helpers': dict(pin, sha256='0'*64)}):
                fetch.helpers(self.root/'runtime-bad', build)
            fetch.helpers(self.root/'runtime', build)
        self.assertEqual((build/'mf.dll').read_bytes(), b'mf.dll')
        self.assertEqual((build/'licenses/libyuv-copyright').read_bytes(), b'BSD')
        self.assertEqual(sorted(json.loads((build/'manifest.json').read_text())), sorted(fetch.BUILD_NAMES))


class OnboardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_installer_found_by_checksum_only(self):
        downloads = self.root/'Downloads'; downloads.mkdir()
        (downloads/'CrealityScan_win_4.3.2.exe').write_bytes(b'not the installer')
        real = downloads/'CrealityScan_win_4.3.2 (1).exe'; real.write_bytes(b'installer')
        with patch('onboard.downloads_dir', return_value=downloads), \
             patch.dict(onboard.LOCK, {'installer_sha256': sha(real)}):
            self.assertEqual(onboard.find_installer(), real)
        with patch('onboard.downloads_dir', return_value=downloads), \
             patch.dict(onboard.LOCK, {'installer_sha256': '0'*64}), \
             patch.dict(os.environ, {'HOME': str(self.root/'home')}):
            self.assertIsNone(onboard.find_installer())

    def test_udev_rule_checked_per_scanner_and_line(self):
        rules = self.root/'rules.d'; rules.mkdir()
        installed = lambda pid: onboard.udev_rule_installed(pid, (rules, self.root/'missing'))
        (rules/'70-creality-pika.rules').write_text((ROOT/'config/70-creality-pika.rules').read_text().split('# Creality Sermoon')[0])
        self.assertTrue(installed('0c0b'))
        self.assertFalse(installed('0c06'))
        # A large third-party file that mentions both IDs, but never as one device.
        (rules/'60-other.rules').write_text('SUBSYSTEM=="usb", ATTRS{idVendor}=="2bc5", ATTRS{idProduct}=="0401", MODE="0666"\n'
                                            'SUBSYSTEM=="usb", ATTRS{idVendor}=="1234", ATTRS{idProduct}=="0c06", MODE="0666"\n'
                                            '# ATTRS{idVendor}=="2bc5", ATTRS{idProduct}=="0c06"\n')
        self.assertFalse(installed('0c06'))
        (rules/'70-creality-pika.rules').write_text((ROOT/'config/70-creality-pika.rules').read_text())
        self.assertTrue(installed('0c06'))
        (rules/'70-creality-pika.rules').write_text('SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2BC5", ATTRS{idProduct}=="0C06", TAG+="uaccess"\n')
        self.assertTrue(installed('0c06'))

    def test_setup_checks_real_access_of_connected_scanners(self):
        import usb
        sys.path.insert(0, str(ROOT/'tests'))
        import fakesysfs
        fakesysfs.scanner(self.root)
        denied = lambda node, mode: 'hidraw' not in node
        def finish(rule_installed):
            out = io.StringIO()
            with patch.object(usb, 'V4L', self.root/'class/video4linux'), patch.object(usb, 'HIDRAW', self.root/'class/hidraw'), \
                 patch('usb.os.access', side_effect=denied), patch('onboard.desktop_entry', return_value=self.root/'entry'), \
                 patch('onboard.udev_rule_installed', return_value=rule_installed), patch('sys.stdout', out):
                onboard.finish(self.root/'config.json')
            return out.getvalue()
        text = finish(False)
        self.assertIn('let your user access the scanner (/dev/hidraw10)', text)
        self.assertIn(onboard.access_command(), text)
        text = finish(True)
        self.assertIn('rule is installed, but /dev/hidraw10 is still not accessible. Unplug and replug', text)
        self.assertIn(onboard.access_command(), text)
        with patch.object(usb, 'V4L', self.root/'class/video4linux'), patch.object(usb, 'HIDRAW', self.root/'class/hidraw'), \
             patch('usb.os.access', return_value=True), patch('onboard.desktop_entry', return_value=self.root/'entry'), \
             patch('onboard.udev_rule_installed', return_value=False), patch('sys.stdout', io.StringIO()) as out:
            onboard.finish(self.root/'config.json')
        self.assertNotIn('sudo', out.getvalue())  # access works: nothing to fix

    def test_desktop_notification_escapes_markup(self):
        import creality
        with patch('creality.shutil.which', return_value='/usr/bin/notify-send'), patch('creality.sys.stderr') as err, \
             patch('creality.subprocess.run') as run:
            err.isatty.return_value = False
            creality.notify('Scanner access blocked: /dev/hidraw10. Run: sudo cp a b && sudo udevadm control --reload <x>')
        self.assertEqual(run.call_args[0][0][-1],
                         'Scanner access blocked: /dev/hidraw10. Run: sudo cp a b &amp;&amp; sudo udevadm control --reload &lt;x&gt;')

    def test_experimental_scanner_setting(self):
        import creality
        path = self.root/'config.json'
        c = json.loads((ROOT/'config/config.example.json').read_text())
        for key in ('runner', 'installer', 'dxvk_dir', 'data_dir'):
            c[key] = str(self.root/key)
        path.write_text(json.dumps(c))
        creality.experimental(path, 'sermoon-s1', False)
        self.assertEqual(json.loads(path.read_text())['experimental_scanners'], ['sermoon-s1'])
        self.assertEqual(common.load(path)['experimental_scanners'], ['sermoon-s1'])
        creality.experimental(path, 'sermoon-s1', True)
        self.assertEqual(json.loads(path.read_text())['experimental_scanners'], [])
        with self.assertRaisesRegex(ValueError, 'choose from: sermoon-s1'):
            creality.experimental(path, 'pika', False)
        path.write_text(json.dumps(dict(c, experimental_scanners='sermoon-s1')))
        with self.assertRaisesRegex(ValueError, 'list of scanner names'):
            common.load(path)

    def test_desktop_entry_quotes_paths(self):
        self.assertEqual(onboard.desktop_quote('/plain/path'), '/plain/path')
        self.assertEqual(onboard.desktop_quote('/a b/100%'), '"/a b/100%%"')
        self.assertEqual(onboard.desktop_quote('/a $b'), '"/a \\\\$b"')
        config = self.root/'my config.json'
        entry = onboard.desktop_entry(config, self.root/'applications').read_text()
        exec_line = next(l for l in entry.splitlines() if l.startswith('Exec='))
        self.assertIn(f'"{config}" launch --mode usb', exec_line)
        self.assertIn('StartupNotify=true', entry)

    def test_missing_installer_and_gpu_explained(self):
        with patch('onboard.find_installer', return_value=None), \
             self.assertRaisesRegex(RuntimeError, 'Downloads'):
            onboard.prepare(self.root/'config.json')
        installer = self.root/'setup.exe'; installer.write_bytes(b'installer')
        with patch.dict(onboard.LOCK, {'installer_sha256': sha(installer)}), \
             patch('onboard.detect_gpu', return_value=None), \
             self.assertRaisesRegex(RuntimeError, 'OpenCL'):
            onboard.prepare(self.root/'config.json', installer)
        self.assertFalse((self.root/'config.json').exists())


class NvidiaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_nvidia_device_nodes_passed_to_sandbox(self):
        dev = self.root/'dev'
        for name in ('dri', 'nvidia-caps'):
            (dev/name).mkdir(parents=True)
        for name in ('nvidia0', 'nvidiactl', 'nvidia-uvm', 'video0', 'kfd-not'):
            (dev/name).write_text('')
        self.assertEqual([p.name for p in common.gpu_devices(dev)],
                         ['dri', 'nvidia-caps', 'nvidia-uvm', 'nvidia0', 'nvidiactl'])

    def drm(self, *vendors):
        drm = self.root/('drm-' + '-'.join(vendors))
        for i, vendor in enumerate(vendors):
            (drm/f'card{i}/device').mkdir(parents=True)
            (drm/f'card{i}/device/vendor').write_text(vendor + '\n')
            (drm/f'card{i}-eDP-1').mkdir()
        return drm

    def test_prime_offload_only_for_hybrid_nvidia(self):
        self.assertTrue(onboard.other_gpu_present(self.drm('0x10de', '0x8086')))
        self.assertFalse(onboard.other_gpu_present(self.drm('0x10de')))
        installer = self.root/'setup.exe'; installer.write_bytes(b'x')
        for gpu, hybrid, expected in (('NVIDIA T600 Laptop GPU', True, '1'), ('NVIDIA T600 Laptop GPU', False, None),
                                      ('AMD Radeon RX 6800 XT', True, None)):
            with self.subTest(gpu=gpu, hybrid=hybrid):
                config = self.root/f'{gpu}-{hybrid}.json'
                with patch('onboard.fetch.runner', return_value=self.root/'runner'), \
                     patch('onboard.fetch.dxvk', return_value=self.root/'dxvk'), \
                     patch('onboard.other_gpu_present', return_value=hybrid), \
                     patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root/'share')}):
                    onboard.write_config(config, gpu, installer)
                env = json.loads(config.read_text())['environment']
                self.assertEqual(env.get('__NV_PRIME_RENDER_OFFLOAD'), expected)
                self.assertTrue(set(env) <= common.ENV_KEYS)


class RerunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, path in (('TRUST_ROOT', self.root/'trust'), ('LEGACY_TRUST_ROOT', self.root/'checkout/.local-trust')):
            patched = patch.object(integrity, name, path); patched.start(); self.addCleanup(patched.stop)

    def config(self):
        data = self.root/'share/data'
        return {'data_dir': data, 'prefix': data/'prefix', 'exports_dir': self.root/'Documents/CrealityScan'}

    def test_unfinished_install_moved_aside_not_deleted(self):
        c = self.config()
        common.owned(c, create=True).close()
        c['prefix'].mkdir(); (c['prefix']/'half-installed.txt').write_text('keep')
        aside = onboard.set_aside_incomplete(c)
        self.assertFalse(c['data_dir'].exists())
        self.assertEqual((aside/'prefix/half-installed.txt').read_text(), 'keep')
        self.assertTrue(aside.name.startswith('data.previous-'))
        self.assertIsNone(onboard.set_aside_incomplete(c))

    def test_finished_or_unowned_folders_left_alone(self):
        c = self.config()
        c['prefix'].mkdir(parents=True); (c['prefix']/'user-file').write_text('keep')
        self.assertIsNone(onboard.set_aside_incomplete(c))  # no ownership marker
        (c['data_dir']/'community-owner.json').write_text(json.dumps({'format': 1, 'owner': 'crealityscan-linux-community'}))
        baseline = integrity.installation_path(c); baseline.parent.mkdir(parents=True); baseline.write_text('{}')
        self.assertIsNone(onboard.set_aside_incomplete(c))  # finished install
        self.assertTrue((c['prefix']/'user-file').exists())

    def test_install_from_earlier_helpers_moved_aside_with_its_baseline(self):
        c = self.config()
        common.owned(c, create=True).close()
        c['prefix'].mkdir(); (c['prefix']/'app.exe').write_text('installed')
        baseline = integrity.installation_path(c)
        baseline.write_text(json.dumps({'schema': 2, 'files': {}, 'build': {'mf.dll': 'old'}}))
        build = self.root/'checkout/build'; build.mkdir(parents=True)
        (build/'manifest.json').write_text(json.dumps({'mf.dll': 'old'}))
        with patch.object(onboard, 'ROOT', self.root/'checkout'):
            self.assertIsNone(onboard.set_aside_outdated(c))  # same helpers: kept
            (build/'manifest.json').write_text(json.dumps({'mf.dll': 'new'}))
            aside = onboard.set_aside_outdated(c)
        self.assertFalse(c['data_dir'].exists() or baseline.exists())
        self.assertEqual((aside/'prefix/app.exe').read_text(), 'installed')
        moved = integrity.installation_path({'data_dir': aside})
        self.assertEqual(json.loads(moved.read_text())['build'], {'mf.dll': 'old'})
        self.assertIsNone(onboard.set_aside_incomplete(c))

    def test_helpers_from_a_superseded_release_are_replaced(self):
        build = self.root/'checkout/build'; build.mkdir(parents=True)
        (build/'mf.dll').write_bytes(b'v1')
        (build/'manifest.json').write_text(json.dumps({'mf.dll': common.hashlib.sha256(b'v1').hexdigest()}))
        fetched = []
        with patch.object(onboard, 'ROOT', self.root/'checkout'), patch('onboard.fetch.helpers', side_effect=fetched.append):
            with patch.dict(onboard.LOCK, {'helpers': {'version': 'v2', 'supersedes': []}}):
                onboard.helpers({}, None)
            self.assertEqual(fetched, [])
            with patch.dict(onboard.LOCK, {'helpers': {'version': 'v2', 'supersedes': [sha(build/'manifest.json')]}}):
                onboard.helpers({}, None)
            self.assertEqual(len(fetched), 1)

    def test_baseline_found_in_legacy_checkout_store(self):
        c = self.config()
        legacy = integrity.LEGACY_TRUST_ROOT/integrity.installation_path(c).name
        legacy.parent.mkdir(parents=True); legacy.write_text('{}')
        self.assertEqual(integrity.installation_path(c), legacy)
        current = integrity.TRUST_ROOT/legacy.name
        current.parent.mkdir(parents=True); current.write_text('{}')
        self.assertEqual(integrity.installation_path(c), current)


if __name__ == '__main__':
    unittest.main()
