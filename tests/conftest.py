"""Make the project root importable so `import data`, `import tools`, `import config`
work when running pytest from anywhere."""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
