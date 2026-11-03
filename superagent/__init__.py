"""Checkout entry point for the same runtime shipped inside the Claude skill."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / ".claude/skills/delegate/runtime/superagent")]
__version__ = "0.2.0"
