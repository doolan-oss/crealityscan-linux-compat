import runpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_module('replay', run_name='__main__')
