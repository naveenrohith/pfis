"""Entry point for the local PFIS security lab CLI."""

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

main = import_module("security.cli").main

if __name__ == "__main__":
    raise SystemExit(main())
