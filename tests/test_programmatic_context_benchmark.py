from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_benchmark import (
    ContextExperimentObservation,
    ContextExperimentPolicy,
    ContextExperimentReport,
    ContextExperimentVerdict,
    compare_context_case,
)
from origin_forge.programmatic_context_models import (
    ContextInstruction,
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextProgram,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
    ProgrammaticContextModelError,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def _program() -> ContextProgram:
    request = ContextRequest.create(
        project_id=new_id(IdKind.PROJECT),
        objective="Benchmark conventional versus programmatic context.",
    )
    descriptor = ContextOperationDescriptor(
        operation_id="context.noop",
        version="1",
        adapter_fingerprint=HASH_A,
        input_schema_hash=HASH_B,
        output_schema_hash=HASH_C,
        max_calls=1,
        max_response_bytes=4096,
        replay_class=ContextReplayClass.DETERMINISTIC,
    )
    catalog = ContextOperationCatalog.create((descriptor,))
    return ContextProgram.create(
        request=request,
        catalog=catalog,
        budget=ContextProgramBudget(),
        instructions=(ContextInstruction(0, "result", "context.noop", "1", ()),),
        output_bindings=("result",),
    )


def _observation(
    *,
    success: bool = True,
    quality: int = 900,
    calls: int = 3,
    input_tokens: int = 3000,
    output_tokens: int = 500,
    context_bytes: int = 12000,
    wall_time_ms: int = 1000,
    resource_units: int = 100,
    evidence_hash: str = HASH_D,
) -> ContextExperimentObservation:
    return ContextExperimentObservation(
        success=success,
        quality_milli=quality,
        model_calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        context_bytes=context_bytes,
        wall_time_ms=wall_time_ms,
        resource_units=resource_units,
        evidence_hash=evidence_hash,
    )


class ProgrammaticContextBenchmarkTests(unittest.TestCase):
    def test_equivalent_quality_with_lower_context_cost_is_improved(self) -> None:
        case = compare_context_case(
            case_id="case.alpha",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(
                calls=2,
                input_tokens=2000,
                output_tokens=400,
                context_bytes=8000,
                resource_units=90,
            ),
            policy=ContextExperimentPolicy(),
        )
        self.assertIs(case.verdict, ContextExperimentVerdict.IMPROVED)
        self.assertIn("model_calls", case.improvements)
        self.assertEqual(case.regression_reasons, ())

    def test_quality_regression_dominates_large_efficiency_gain(self) -> None:
        case = compare_context_case(
            case_id="case.quality",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(quality=900),
            programmatic=_observation(
                quality=899,
                calls=1,
                input_tokens=100,
                output_tokens=100,
                context_bytes=100,
                resource_units=1,
            ),
            policy=ContextExperimentPolicy(),
        )
        self.assertIs(case.verdict, ContextExperimentVerdict.REGRESSED)
        self.assertIn("quality_milli", case.regression_reasons)

    def test_success_regression_dominates_savings(self) -> None:
        case = compare_context_case(
            case_id="case.success",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(success=True),
            programmatic=_observation(
                success=False,
                calls=1,
                input_tokens=100,
                output_tokens=100,
                context_bytes=100,
                resource_units=1,
            ),
            policy=ContextExperimentPolicy(),
        )
        self.assertIs(case.verdict, ContextExperimentVerdict.REGRESSED)
        self.assertIn("success", case.regression_reasons)

    def test_cost_increase_beyond_frozen_policy_is_regression(self) -> None:
        case = compare_context_case(
            case_id="case.cost",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(calls=4),
            policy=ContextExperimentPolicy(),
        )
        self.assertIs(case.verdict, ContextExperimentVerdict.REGRESSED)
        self.assertIn("model_calls", case.regression_reasons)

    def test_allowed_wall_time_increase_does_not_create_false_regression(self) -> None:
        case = compare_context_case(
            case_id="case.wall",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(wall_time_ms=2000),
            policy=ContextExperimentPolicy(max_wall_time_increase_ms=1000),
        )
        self.assertIs(case.verdict, ContextExperimentVerdict.EQUIVALENT)

    def test_report_is_regression_dominant_across_cases(self) -> None:
        program = _program()
        improved = compare_context_case(
            case_id="case.a",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(calls=2, input_tokens=2000, output_tokens=400, context_bytes=8000, resource_units=90),
            policy=ContextExperimentPolicy(),
        )
        regressed = compare_context_case(
            case_id="case.b",
            case_hash=HASH_C,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(quality=800),
            policy=ContextExperimentPolicy(),
        )
        report = ContextExperimentReport.create(
            program=program,
            policy=ContextExperimentPolicy(),
            cases=(improved, regressed),
        )
        self.assertIs(report.verdict, ContextExperimentVerdict.REGRESSED)
        self.assertFalse(report.to_dict()["phase26_promotion_authorized"])
        self.assertFalse(report.to_dict()["production_activation_authorized"])
        self.assertFalse(report.to_dict()["production_task_verified"])
        report.bind_program(program)

    def test_environment_drift_and_forged_report_verdict_fail_closed(self) -> None:
        program = _program()
        first = compare_context_case(
            case_id="case.a",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(calls=2, input_tokens=2000, output_tokens=400, context_bytes=8000, resource_units=90),
            policy=ContextExperimentPolicy(),
        )
        second = replace(first, case_id="case.b", environment_hash=HASH_C)
        with self.assertRaisesRegex(ProgrammaticContextModelError, "environment changed"):
            ContextExperimentReport.create(
                program=program,
                policy=ContextExperimentPolicy(),
                cases=(first, second),
            )

        report = ContextExperimentReport.create(
            program=program,
            policy=ContextExperimentPolicy(),
            cases=(first,),
        )
        with self.assertRaisesRegex(ProgrammaticContextModelError, "verdict is inconsistent"):
            replace(report, verdict=ContextExperimentVerdict.REGRESSED)

    def test_report_recomputes_and_rejects_forged_case_classification(self) -> None:
        program = _program()
        valid = compare_context_case(
            case_id="case.forged",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(calls=2, input_tokens=2000, output_tokens=400, context_bytes=8000, resource_units=90),
            policy=ContextExperimentPolicy(),
        )
        forged = replace(
            valid,
            verdict=ContextExperimentVerdict.REGRESSED,
            regression_reasons=("quality_milli",),
            improvements=(),
        )
        with self.assertRaisesRegex(ProgrammaticContextModelError, "case classification is inconsistent"):
            ContextExperimentReport.create(
                program=program,
                policy=ContextExperimentPolicy(),
                cases=(forged,),
            )

    def test_report_rejects_program_hash_drift(self) -> None:
        program = _program()
        case = compare_context_case(
            case_id="case.a",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=_observation(),
            programmatic=_observation(calls=2, input_tokens=2000, output_tokens=400, context_bytes=8000, resource_units=90),
            policy=ContextExperimentPolicy(),
        )
        report = ContextExperimentReport.create(
            program=program,
            policy=ContextExperimentPolicy(),
            cases=(case,),
        )
        changed_program = replace(program, program_id=new_id(IdKind.CONTEXT_PROGRAM))
        with self.assertRaisesRegex(ProgrammaticContextModelError, "exact program"):
            report.bind_program(changed_program)


if __name__ == "__main__":
    unittest.main()
