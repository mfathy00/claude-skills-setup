"""Isolated-Python entry point for an installed skill, independent of cwd/PYTHONPATH."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from superagent.cli import main

raise SystemExit(main())
