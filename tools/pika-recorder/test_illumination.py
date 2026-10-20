import unittest
from device import Control
from illumination import GATES,PRESETS,allowed,prepare
class Tests(unittest.TestCase):
 def test_opt_in_allowlist(self):
  for p,v in ((5,1),(154,1),(159,100),(192,7),(98,2),(239,1),(2026,3000)):
   c=object.__new__(Control)
   with self.assertRaises(ValueError):c.set(p,v,allow_illumination_test=True)
  for preset in PRESETS.values():
   for p,v in preset.items():self.assertTrue(allowed(p,v))
 def test_prepare_orders_off_before_mode_before_on(self):
  calls=[]
  class Fake:
   def get(self,p):return {'current':0}
   def set(self,p,v,**kw):calls.append((p,v))
  prepare(Fake(),'line-mode-6')
  self.assertEqual(calls[:len(GATES)],[(p,0) for p in GATES])
  self.assertEqual(calls[-2:],[(192,6),(3,1)])
 def test_restore_on_failed_enable(self):
  c=object.__new__(Control);c.saved={};c.get=lambda p:dict(current=0,min=0,max=1,step=1);c.transact=lambda *a:b''
  with self.assertRaises(RuntimeError):c.set(158,1,allow_illumination_test=True)
  self.assertEqual(c.saved,{158:0})
 def test_rejected_enable_already_off_needs_no_restore_write(self):
  import os
  c=object.__new__(Control);c.saved={152:0};c.fd=os.open('/dev/null',os.O_RDONLY)
  c.get=lambda p:{'current':0}
  c.transact=lambda *a:self.fail('Do not repeat a rejected write when original value is verified')
  c.close()
if __name__=='__main__':unittest.main()
