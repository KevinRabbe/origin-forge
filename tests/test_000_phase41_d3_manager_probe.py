from __future__ import annotations

import os
import unittest

import test_phase40_manager_advance_acceptance as target


_real_advance = target.advance_production_manager_once


def _traced_advance(runtime):
    result = _real_advance(runtime)
    print(
        "::error title=Phase41D3 manager result::"
        f"status={result.status.value} lower={result.lower_status} "
        f"prep={result.preparation_id} detail={result.detail!r}",
        flush=True,
    )
    return result


target.advance_production_manager_once = _traced_advance
suite = unittest.TestSuite()
suite.addTest(
    target.Phase40ManagerAdvanceAcceptanceTests(
        "test_concurrent_managers_prepare_one_oldest_task_once_and_never_fall_through"
    )
)
result = unittest.TestResult()
suite.run(result)
for test, tb in result.errors + result.failures:
    compact = " | ".join(line.strip() for line in tb.splitlines() if line.strip())
    print(f"::error title=Phase41D3 probe failure::{test.id()} {compact}", flush=True)
print(
    f"::error title=Phase41D3 probe summary::failures={len(result.errors) + len(result.failures)}",
    flush=True,
)
os._exit(97)
