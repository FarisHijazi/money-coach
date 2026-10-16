"""Shared paths and your personal values.

DATA: where every input/output file lives — $MONEY_DATA, else this directory.
P: personal.py (gitignored) from DATA, else from this directory, else the placeholders in
personal.example.py. Every script reads names, regexes and budgets through `from config import P`.
"""
import importlib.util
import os
from pathlib import Path

CODE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MONEY_DATA") or CODE)

_path = next(p for p in (DATA / "personal.py", CODE / "personal.py", CODE / "personal.example.py") if p.exists())
_spec = importlib.util.spec_from_file_location("personal", _path)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
