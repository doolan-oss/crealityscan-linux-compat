# -I excludes the caller's cwd and user site packages. Add only this source folder.
import runpy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
runpy.run_module('recorder',run_name='__main__')
