"""Holdout suite path setup: tools/m4 and tools on sys.path, no game data needed."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
M4 = os.path.dirname(HERE)
TOOLS = os.path.dirname(M4)
for p in (HERE, M4, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)
