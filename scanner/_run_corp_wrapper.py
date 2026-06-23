"""Wrapper to run hk_cloud_scanner.py corp mode, avoiding __file__ issues."""
import sys, os

# Ensure scanner dir is on sys.path so relative imports work
scanner_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, scanner_dir)
os.chdir(scanner_dir)

# Set __file__ for hk_cloud_scanner to find project root
# The script uses os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# to find the project root. Since this wrapper is in scanner/, dirname(__file__) 
# gives scanner/, so we need to set __file__ to something that when double-dirnamed
# gives the project root.
# This wrapper IS in scanner/, so double dirname of this file = project root
# We'll just import the function directly after patching.

import hk_cloud_scanner

# Override the __file__ reference so it points to the actual script
hk_cloud_scanner.__file__ = os.path.join(scanner_dir, 'hk_cloud_scanner.py')

# Run corp mode
hk_cloud_scanner.run_corp_actions()
