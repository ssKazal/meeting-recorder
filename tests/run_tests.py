#!/usr/bin/env python3
"""Minimal zero-dependency test runner (no pytest needed).

Discovers test_*.py in this directory, runs every top-level `test_*` function,
and reports pass/fail. Run with:  python3 tests/run_tests.py
"""

import importlib.util
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    passed = failed = 0
    for test_file in sorted(HERE.glob("test_*.py")):
        mod = load_module(test_file)
        for name in dir(mod):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"PASS {test_file.name}::{name}")
            except Exception:
                failed += 1
                print(f"FAIL {test_file.name}::{name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
