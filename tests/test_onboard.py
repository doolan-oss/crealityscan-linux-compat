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
