from __future__ import annotations

import unittest

import test_phase47f_simulation_cross_phase_acceptance as _phase47f


_original_run = unittest.TestCase.run


def _annotated_run(self, result=None):
    before_failures = len(result.failures) if result is not None else 0
    before_errors = len(result.errors) if result is not None else 0
    outcome = _original_run(self, result)
    resolved = result if result is not None else outcome
    if resolved is not None:
        new_entries = (
            resolved.failures[before_failures:]
            + resolved.errors[before_errors:]
        )
        for test, traceback_text in new_entries:
            lines = [line.strip() for line in traceback_text.splitlines() if line.strip()]
            detail = lines[-1] if lines else "unknown Phase47F test failure"
            detail = detail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(
                "::error file=tests/test_phase47f_simulation_cross_phase_acceptance.py,"
                f"title=Phase47F {test._testMethodName}::{detail}",
                flush=True,
            )
    return outcome


_phase47f.Phase47FSimulationCrossPhaseAcceptanceTests.run = _annotated_run
