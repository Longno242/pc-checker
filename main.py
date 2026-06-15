#!/usr/bin/env python3

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.gui.app import run_app


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
