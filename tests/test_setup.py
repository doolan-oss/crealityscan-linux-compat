import json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from common import load,owned,expect,winpath,environment,sandbox
class SetupTests(unittest.TestCase):
    def setUp(self):
        trust=tempfile.TemporaryDirectory()
        self.addCleanup(trust.cleanup)
        patched=patch('integrity.TRUST_ROOT',Path(trust.name))
        patched.start();self.addCleanup(patched.stop)
    def config(self,d):
        c=json.loads((ROOT/'config/config.example.json').read_text())
        for k in ('runner','installer','dxvk_dir','data_dir'):c[k]=str(Path(d)/('path with spaces '+k))
        p=Path(d)/'config.json';p.write_text(json.dumps(c));return p
    def test_portable_paths_and_explicit_environment(self):
        with tempfile.TemporaryDirectory()as d:
            c=load(self.config(d));e=environment(c,Path(d))
            self.assertEqual(e['CREALITY_PREFIX_GUARD'],str(c['prefix']))
            self.assertIn('opencl=b',e['WINEDLLOVERRIDES']);self.assertNotIn('ROCR_VISIBLE_DEVICES',e)
            self.assertTrue(winpath(c['prefix']).startswith('Z:\\'))
    def test_unknown_environment_and_relative_paths_rejected(self):
        with tempfile.TemporaryDirectory()as d:
            p=self.config(d);c=json.loads(p.read_text());c['environment']={'LD_PRELOAD':'/bad.so'};p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load(p)
            c['environment']={};c['runner']='relative';p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load(p)
    def test_refuse_existing_unowned_data_and_lock_live_session(self):
        with tempfile.TemporaryDirectory()as d:
            c=load(self.config(d));c['data_dir'].mkdir();(c['data_dir']/'user-project').write_text('keep')
            with self.assertRaisesRegex(RuntimeError,'unowned'):owned(c,True)
            (c['data_dir']/'user-project').unlink();lock=owned(c,True)
            with self.assertRaises(BlockingIOError):owned(c)
            lock.close();owned(c).close()
    def test_prefix_symlink_refused_and_changed_hash_rejected(self):
        with tempfile.TemporaryDirectory()as d:
            c=load(self.config(d));owned(c,True).close();c['prefix'].symlink_to(Path(d),target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError,'symlink'):owned(c)
            p=Path(d)/'file';p.write_text('changed')
            with self.assertRaises(RuntimeError):expect(p,'0'*64)
    def test_no_camera_or_network_exposure_in_diagnostics(self):
        with tempfile.TemporaryDirectory()as d:
            c=load(self.config(d));cmd=sandbox(c,Path(d),{},display=False,gpu=False)
            self.assertIn('--unshare-net',cmd);self.assertIn('--clearenv',cmd)
            self.assertNotIn('--dev-bind',cmd);self.assertNotIn('/dev/video0',cmd)
    def test_current_and_earlier_pinned_dxvk_accepted(self):
        import common
        with tempfile.TemporaryDirectory()as d:
            dxvk=Path(d);c={'runner':dxvk,'dxvk_dir':dxvk}
            sets=[{'d3d11.dll':b'new d3d11','dxgi.dll':b'new dxgi'},{'d3d11.dll':b'old d3d11','dxgi.dll':b'old dxgi'}]
            pins=[{n:common.hashlib.sha256(v).hexdigest() for n,v in s.items()} for s in sets]
            lock={'dxvk':pins[0],'dxvk_also_accepted':[{'version':'old',**pins[1]}]}
            with patch.dict(common.LOCK,lock),patch('common.tree_digest',return_value=common.LOCK['runner_tree_sha256']),patch('common.expect'):
                for files in sets:
                    for n,v in files.items():(dxvk/n).write_bytes(v)
                    common.dependencies(c)
                (dxvk/'dxgi.dll').write_bytes(b'new dxgi')
                with self.assertRaisesRegex(RuntimeError,'DXVK'):common.dependencies(c)
    def test_cli_help_from_other_directory(self):
        r=subprocess.run([sys.executable,str(ROOT/'scripts/creality.py'),'--help'],cwd='/tmp',capture_output=True)
        self.assertEqual(r.returncode,0)
    def test_native_offline_suite(self):
        r=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tools/pika-recorder'),'-p','test_*.py'],cwd='/tmp',capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
if __name__=='__main__':unittest.main()
