"""Security regressions use synthetic files, never an existing Wine prefix."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tools/pika-recorder')]
import common
import integrity
import analyze
import demux
import replay
import safeio
import creality
import stateio
import test_replay


class SecurityTests(unittest.TestCase):
    def test_host_log_and_exit_symlinks_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state';state.mkdir();outside=root/'outside';outside.mkdir()
            (state/'logs').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(OSError):creality.logdir({'data_dir':state},'test')
            self.assertEqual(list(outside.iterdir()),[])
            canary=outside/'secret';canary.write_text('keep')
            (state/'exit-code.txt').symlink_to(canary)
            with self.assertRaises(FileExistsError):stateio.write_new(state/'exit-code.txt','0\n')
            self.assertEqual(canary.read_text(),'keep')

    def test_host_deployment_checks_links_before_truncating(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.write_bytes(b'new code')
            canary=root/'secret';canary.write_bytes(b'keep')
            destination=root/'dll';os.link(canary,destination)
            with self.assertRaises(RuntimeError):stateio.copy_file(source,destination,replace=True)
            self.assertEqual(canary.read_bytes(),b'keep')
            destination.unlink();destination.symlink_to(canary)
            with self.assertRaises(OSError):stateio.copy_file(source,destination,replace=True)
            self.assertEqual(canary.read_bytes(),b'keep')
            destination.unlink();destination.write_bytes(b'old code')
            stateio.copy_file(source,destination,replace=True)
            self.assertEqual(destination.read_bytes(),b'new code')

    def test_app_cannot_replace_host_session_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c={'data_dir':root/'state','prefix':root/'state/prefix'}
            with patch.object(integrity,'TRUST_ROOT',root/'trust'):
                lock=common.owned(c,create=True)
                try:
                    (c['data_dir']/'session.lock').write_text('untrusted replacement')
                    with self.assertRaises(BlockingIOError):common.owned(c)
                    self.assertTrue(integrity.installation_path(c).with_suffix('.lock').is_file())
                finally:lock.close()

    def test_installation_baseline_outside_state_and_complete_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); c={'data_dir':root/'state','prefix':root/'state/prefix'}
            app=c['prefix']/'drive_c/Program Files/CrealityScan';app.mkdir(parents=True)
            for name in ('CrealityScan.exe','pikacam.dll','mf.dll'): (app/name).write_bytes(b'fixture')
            with patch.object(integrity,'TRUST_ROOT',root/'trust'):
                integrity.save_installation(c,{'helper':'test'})
                baseline=integrity.installation_path(c)
                self.assertFalse(baseline.is_relative_to(c['data_dir']))
                self.assertEqual(len(integrity.verify_installation(c,{'helper':'test'})),3)
                (c['data_dir']/'installation.json').write_text('{"schema":1,"files":{}}')
                (app/'pikacam.dll').write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'content changed'):
                    integrity.verify_installation(c,{'helper':'test'})
                (app/'pikacam.dll').write_bytes(b'fixture')
                (app/'extra.dll').write_bytes(b'injected')
                with self.assertRaises(RuntimeError):integrity.verify_installation(c,{'helper':'test'})
                (app/'extra.dll').unlink()
                (app/'mf.dll').unlink()
                with self.assertRaises(RuntimeError):integrity.verify_installation(c,{'helper':'test'})
                (app/'mf.dll').write_bytes(b'fixture')
                data=json.loads(baseline.read_text());data['files']={};baseline.write_text(json.dumps(data))
                with self.assertRaises(RuntimeError):integrity.verify_installation(c,{'helper':'test'})

    def test_runner_tree_covers_other_libraries_additions_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'other.so').write_bytes(b'original')
            before=integrity.tree_digest(root)
            (root/'other.so').write_bytes(b'changed')
            self.assertNotEqual(before,integrity.tree_digest(root))
            (root/'other.so').write_bytes(b'original');(root/'added.dll').write_bytes(b'x')
            self.assertNotEqual(before,integrity.tree_digest(root))
            (root/'escape').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(RuntimeError,'External'):integrity.tree_digest(root)

    def test_analyzer_symlink_and_hardlink_outputs_preserve_target(self):
        for link in ('symlink','hardlink'):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);recording=root/'recording';recording.mkdir()
                target=root/'canary';target.write_text('keep')
                if link=='symlink':(recording/'summary.json').symlink_to(target)
                else:os.link(target,recording/'summary.json')
                with self.assertRaises(OSError):analyze.analyze(recording)
                self.assertEqual(target.read_text(),'keep')

    def test_symlink_inputs_ancestors_and_fifo_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);real=root/'real';real.mkdir();(real/'x').write_text('private')
            (root/'linked').symlink_to(real,target_is_directory=True)
            (root/'x').symlink_to(real/'x')
            os.mkfifo(root/'pipe')
            for p in (root/'linked/x',root/'x',root/'pipe'):
                with self.assertRaises((OSError,ValueError)):safeio.read_text(p)

    def test_parent_swap_cannot_redirect_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'dir';parent.mkdir();outside=root/'outside';outside.mkdir()
            real_open=os.open;swapped=[False]
            def raced_open(path,flags,*args,**kwargs):
                if path=='out' and not swapped[0]:
                    swapped[0]=True;parent.rename(root/'old');parent.symlink_to(outside,target_is_directory=True)
                return real_open(path,flags,*args,**kwargs)
            with patch('safeio.os.open',side_effect=raced_open):safeio.write_text(parent/'out','safe')
            self.assertFalse((outside/'out').exists())
            self.assertEqual((root/'old/out').read_text(),'safe')

    def test_replay_symlink_pack_and_demux_reject_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);recording=root/'recording';recording.mkdir()
            test_replay.ReplayTests().dataset(recording)
            outside=root/'outside';outside.mkdir()
            (recording/'replay-v1').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(FileExistsError):replay.pack(recording)
            with self.assertRaises(FileExistsError):demux.demux(recording,recording/'replay-v1')
            self.assertEqual(list(outside.iterdir()),[])

    def test_aggregate_limits_and_sparse_replay_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'index';p.write_bytes(b'x'*100)
            with patch('safeio.MAX_INDEX_BYTES',16):
                with self.assertRaisesRegex(ValueError,'byte limit'):safeio.read_jsonl(p)
            p.write_text('{}\n'*3)
            with patch('safeio.MAX_ROWS',2):
                with self.assertRaisesRegex(ValueError,'row limit'):safeio.read_jsonl(p)
            test_replay.ReplayTests().dataset(root)
            rows=safeio.read_jsonl(root/'ir.jsonl');rows[-1]['v4l2_us']+=86400*1000000
            (root/'ir.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaisesRegex(ValueError,'timestamp gap'):replay.pack(root)
            rec=replay.Recording.__new__(replay.Recording)
            rec.events=[{'time_ns':0},{'time_ns':86400*10**9}]
            with self.assertRaisesRegex(ValueError,'duration/gap'):list(rec.frames())

    def test_pairing_density_bound(self):
        frames=[{'phase_tag':'test','camera':cam,'device_pts_raw':0,'sequence':i}
                for cam in ('left','right') for i in range(20)]
        with patch('demux.MAX_ROWS',40):
            with self.assertRaisesRegex(ValueError,'density'):demux.candidate_pairs(frames)

    def test_no_host_root_mount_and_network_requires_opt_in(self):
        c={'runner':Path('/runner'),'data_dir':Path('/state'),'prefix':Path('/state/prefix')}
        cmd=common.sandbox(c,Path('/log'),{},gpu=False)
        self.assertNotIn(['--ro-bind','/','/'],[cmd[i:i+3] for i in range(len(cmd)-2)])
        self.assertNotIn('/home',cmd);self.assertNotIn('/etc',cmd);self.assertNotIn('/tmp/.X11-unix',cmd)
        with self.assertRaisesRegex(RuntimeError,'opt in'):
            common.sandbox(c,Path('/log'),{},gpu=False,network=True)

    def test_wine_returns_sandbox_exit_code(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'prefix';prefix.mkdir()
            baseline=root/'trusted';baseline.write_text('fixture')
            c={'prefix':prefix,'runner':root/'runner','data_dir':root,'exports_dir':root/'exports'}
            with patch('creality.environment',return_value={}), \
                 patch('creality.installation_path',return_value=baseline), \
                 patch('creality.verify_install',return_value={}), \
                 patch('creality.subprocess.run',return_value=SimpleNamespace(returncode=7)):
                self.assertEqual(creality.wine(c,root,['dummy.exe'],display=False,workdir=prefix),7)
            self.assertEqual((root/'exit-code.txt').read_text(),'7\n')

if __name__=='__main__':unittest.main()
