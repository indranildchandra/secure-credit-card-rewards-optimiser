"""Make the project root (and scripts/) importable so `import data`, `import tools`,
`import config`, and `import setup_cards` work when running pytest from anywhere."""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCRIPTS = os.path.join(_ROOT, "scripts")
for _p in (_ROOT, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
