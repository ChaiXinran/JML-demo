"""Run the supported JML–JML regression suite without Web or OpenJML."""

from __future__ import annotations

import sys
import unittest


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "test_semantic_judge",
        "test_cli",
        "test_hardening",
        "test_2027_exercises",
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
