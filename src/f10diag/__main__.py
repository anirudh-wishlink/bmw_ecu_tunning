"""Allow ``python -m f10diag``.

With no arguments it runs the offline demonstration, so the implemented layers
can be exercised without a vehicle.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    argv = sys.argv[1:] or ["demo"]
    raise SystemExit(main(argv))
