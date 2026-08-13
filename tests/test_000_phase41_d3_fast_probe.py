from __future__ import annotations

import os
import traceback
import unittest

import test_phase39_preparation_acceptance as phase39_acceptance
import test_production_preparation_pinned_candidate as pinned_candidate
import test_production_preparation_tick as preparation_tick


modules = (pinned_candidate, preparation_tick, phase39_acceptance)
failures: list[str] = []
for module in modules:
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TestResult()
    suite.run(result)
    for test, tb in result.errors + result.failures:
        compact = " | ".join(line.strip() for line in tb.splitlines() if line.strip())
        message = f"{test.id()}: {compact}"
        print(f"::error title=Phase41D3 {test.id()}::{compact}", flush=True)
        failures.append(message)
print(
    f"::error title=Phase41D3 summary::failures={len(failures)}",
    flush=True,
)
os._exit(97)
