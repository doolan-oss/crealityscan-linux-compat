import unittest,subprocess,sys,os
from pathlib import Path
from device import Control
from illumination import prepare
class SyncTests(unittest.TestCase):
 def test_mode_before_second_gate_and_second_gate_off_before_restore_mode(self):
  c=object.__new__(Control);c.fd=os.open('/dev/null',os.O_RDONLY);c.saved={};state={};calls=[]
  def get(p):return dict(current=state.get(p,0),min=0,max=6 if p==192 else 1,step=1)
  def transact(op,p,v):
   if p==152 and state.get(192,0)!=4:raise RuntimeError('Second gate requires mixed mode')
   calls.append((p,v));state[p]=v;return b''
  c.get=get;c.transact=transact
  prepare(c,'mixed-dual');self.assertEqual(calls,[(192,4),(3,1),(152,1)])
  c.close();self.assertEqual(calls[-3:],[(152,0),(3,0),(192,0)])
  self.assertTrue(all(v==0 for v in state.values()))
 def test_cli_rejects_unverified_combinations_before_hardware_access(self):
  script=Path(__file__).with_name('recorder.py')
  for extra in (['--fps','120'],['--seconds','4'],['--laser-test'],['--illumination-test','off']):
   r=subprocess.run([sys.executable,str(script),'--sync-mode','mixed',*extra],capture_output=True,text=True)
   self.assertEqual(r.returncode,2,r.stderr)
if __name__=='__main__':unittest.main()
