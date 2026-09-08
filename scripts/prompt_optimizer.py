#!/usr/bin/env python
"""Entry point for `make prompt` local prompt-optimizer modes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.prompt_optimizer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
