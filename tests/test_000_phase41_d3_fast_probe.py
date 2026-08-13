from __future__ import annotations

import os
import unittest

import test_phase40_manager_advance_acceptance as phase40_acceptance
import test_production_manager_advance_admission as manager_admission
import test_production_manager_advance_inventory as manager_inventory
import test_production_manager_advance_once as manager_once
import test_production_manager_advance_selection as manager_selection
import test_production_manager_advance_status as manager_status
import test_production_preparation_activation as preparation_activation
import test_production_preparation_owner_assembly as owner_assembly
import test_production_preparation_phase34_finalize as phase34_finalize
import test_production_preparation_status as preparation_status
import test_production_preparation_work_order_finalize as work_order_finalize


modules = (
    preparation_activation,
    owner_assembly,
    preparation_status,
    work_order_finalize,
    phase34_finalize,
    manager_admission,
    manager_inventory,
    manager_selection,
    manager_status,
    manager_once,
    phase40_acceptance,
)
failures: list[str] = []
for module in modules:
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TestResult()
    suite.run(result)
    for test, tb in result.errors + result.failures:
        compact = " | ".join(line.strip() for line in tb.splitlines() if line.strip())
        print(f"::error title=Phase41D3 {test.id()}::{compact}", flush=True)
        failures.append(f"{test.id()}: {compact}")
print(f"::error title=Phase41D3 summary::failures={len(failures)}", flush=True)
os._exit(97)
