#!/usr/bin/env python3
"""Hardware-free sandbox regression check; creates only a temporary dummy state."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from common import ROOT, load, sandbox

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',type=Path,default=ROOT/'config.local.json')
    args=ap.parse_args()
    config=load(args.config)
    with tempfile.TemporaryDirectory(prefix='creality-isolation-') as temp:
        root=Path(temp);c=dict(config)
        c['data_dir']=root/'state';c['prefix']=c['data_dir']/'prefix'
        c['prefix'].mkdir(parents=True)
        (c['prefix']/'home').mkdir()
        canary=root/'outside-state-secret';canary.write_text('harmless secret')
        executable=c['prefix']/'dummy.dll';executable.write_bytes(b'dummy code')
        probes={'canary':str(canary),'trust':str(ROOT/'.local-trust'),
                'state':str(c['data_dir']),'code':str(executable),
                'network':os.readlink('/proc/self/ns/net')}
        code='''import errno,json,os
from pathlib import Path
p=json.loads(os.environ['TEST_PATHS'])
assert not Path(p['canary']).exists()
assert not Path(p['trust']).exists()
assert not Path('/etc/shadow').exists()
assert not Path('/tmp/.X11-unix').exists()
assert not Path('/dev/video0').exists()
assert os.readlink('/proc/self/ns/net')!=p['network']
Path(p['state'],'writable').write_text('allowed')
try:
    fd=os.open(p['code'],os.O_RDWR)
except OSError as error:
    assert error.errno==errno.EROFS
else:
    os.close(fd)
    raise AssertionError('Executable mount is writable')
print('PASS: canary/trust/host secrets and display hidden; private network/devices; state writable; code read-only')
'''
        cmd=sandbox(c,c['data_dir'],{'TEST_PATHS':json.dumps(probes)},gpu=False,
                    code_files=['dummy.dll'])
        subprocess.run([*cmd,'/usr/bin/python3','-I','-c',code],check=True,timeout=20)
        assert canary.read_text()=='harmless secret'
        assert executable.read_bytes()==b'dummy code'

if __name__=='__main__':main()
