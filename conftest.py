"""Puts the repo root on sys.path so `import momito` works from tests.

pytest imports this file before collecting anything, which is why the test
files themselves do not need a sys.path hack.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
