"""Run hk_cloud_scanner.py corp mode via runpy (sets __file__ correctly)."""
import sys, os

scanner_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(scanner_dir)
sys.path.insert(0, scanner_dir)
sys.path.insert(0, parent_dir)

script_path = os.path.join(scanner_dir, 'hk_cloud_scanner.py')

# Use runpy.run_path which properly sets __file__
import runpy
sys.argv = [script_path, 'corp']
runpy.run_path(script_path, run_name='__main__')
