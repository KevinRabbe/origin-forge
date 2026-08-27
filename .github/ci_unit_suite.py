"""Run the platform unit tier without capability-specific real-tool suites."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _cases(item)
        else:
            yield item


def main() -> int:
    discovered = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    unit_cases = [
        case
        for case in _cases(discovered)
        if not case.__class__.__module__.rsplit(".", 1)[-1].endswith("_real")
    ]
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(unit_cases))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
