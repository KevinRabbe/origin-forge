from __future__ import annotations

import json
import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_models import (
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
)
from origin_forge.programmatic_context_proposal import (
    ContextProgramProposalError,
    parse_context_program_proposal,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class ProgrammaticContextProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ContextRequest.create(
            project_id=new_id(IdKind.PROJECT),
            objective="Parse one bounded model-proposed context program.",
        )
        descriptor = ContextOperationDescriptor(
            operation_id="context.lookup",
            version="1",
            adapter_fingerprint=HASH_A,
            input_schema_hash=HASH_B,
            output_schema_hash=HASH_C,
            max_calls=2,
            max_response_bytes=4096,
            replay_class=ContextReplayClass.DETERMINISTIC,
        )
        self.catalog = ContextOperationCatalog.create((descriptor,))
        self.budget = ContextProgramBudget(max_instructions=2, max_invocations=2)

    def _proposal(self) -> dict[str, object]:
        return {
            "instructions": [
                {
                    "binding": "first",
                    "operation_id": "context.lookup",
                    "operation_version": "1",
                    "arguments": [
                        {"kind": "LITERAL", "name": "id", "literal": "RUN-1"},
                    ],
                },
                {
                    "binding": "second",
                    "operation_id": "context.lookup",
                    "operation_version": "1",
                    "arguments": [
                        {"kind": "REFERENCE", "name": "previous", "reference": "first"},
                    ],
                },
            ],
            "output_bindings": ["second"],
        }

    def test_infrastructure_supplies_identity_catalog_and_budget(self) -> None:
        program = parse_context_program_proposal(
            json.dumps(self._proposal()),
            request=self.request,
            catalog=self.catalog,
            budget=self.budget,
        )
        self.assertEqual(program.request_id, self.request.request_id)
        self.assertEqual(program.request_hash, self.request.content_hash)
        self.assertEqual(program.catalog_id, self.catalog.catalog_id)
        self.assertEqual(program.catalog_hash, self.catalog.content_hash)
        self.assertEqual(program.budget, self.budget)
        self.assertEqual([v.index for v in program.instructions], [0, 1])

    def test_model_cannot_supply_catalog_budget_or_program_identity(self) -> None:
        for forbidden, value in (
            ("program_id", new_id(IdKind.CONTEXT_PROGRAM)),
            ("catalog_id", self.catalog.catalog_id),
            ("catalog_hash", self.catalog.content_hash),
            ("budget", {"max_instructions": 999}),
            ("request_id", self.request.request_id),
        ):
            proposal = self._proposal()
            proposal[forbidden] = value
            with self.assertRaisesRegex(ContextProgramProposalError, "exactly"):
                parse_context_program_proposal(
                    json.dumps(proposal),
                    request=self.request,
                    catalog=self.catalog,
                    budget=self.budget,
                )

    def test_unknown_operation_fails_before_program_is_returned(self) -> None:
        proposal = self._proposal()
        proposal["instructions"][0]["operation_id"] = "shell.exec"  # type: ignore[index]
        with self.assertRaisesRegex(ContextProgramProposalError, "governed validation"):
            parse_context_program_proposal(
                json.dumps(proposal),
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

    def test_forward_reference_and_rebinding_fail_governed_validation(self) -> None:
        proposal = self._proposal()
        proposal["instructions"][0]["arguments"] = [  # type: ignore[index]
            {"kind": "REFERENCE", "name": "future", "reference": "second"}
        ]
        with self.assertRaisesRegex(ContextProgramProposalError, "governed validation"):
            parse_context_program_proposal(
                json.dumps(proposal),
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

        proposal = self._proposal()
        proposal["instructions"][1]["binding"] = "first"  # type: ignore[index]
        with self.assertRaisesRegex(ContextProgramProposalError, "governed validation"):
            parse_context_program_proposal(
                json.dumps(proposal),
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

    def test_duplicate_json_keys_are_rejected(self) -> None:
        raw = '{"instructions":[],"instructions":[],"output_bindings":[]}'
        with self.assertRaisesRegex(ContextProgramProposalError, "duplicate JSON key"):
            parse_context_program_proposal(
                raw,
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

    def test_pathological_integer_is_normalized_to_bounded_proposal_error(self) -> None:
        huge_integer = "9" * 5000
        raw = (
            '{"instructions":[{"binding":"first","operation_id":"context.lookup",'
            '"operation_version":"1","arguments":[{"kind":"LITERAL","name":"id",'
            '"literal":' + huge_integer + '}]}],"output_bindings":["first"]}'
        )
        with self.assertRaisesRegex(ContextProgramProposalError, "invalid bounded JSON"):
            parse_context_program_proposal(
                raw,
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

    def test_literal_float_is_rejected_through_model_contract(self) -> None:
        proposal = self._proposal()
        proposal["instructions"][0]["arguments"][0]["literal"] = 0.5  # type: ignore[index]
        with self.assertRaisesRegex(ContextProgramProposalError, "governed validation"):
            parse_context_program_proposal(
                json.dumps(proposal),
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )

    def test_instruction_budget_is_enforced_before_construction(self) -> None:
        proposal = self._proposal()
        proposal["instructions"].append(proposal["instructions"][0])  # type: ignore[union-attr,index]
        with self.assertRaisesRegex(ContextProgramProposalError, "instruction count"):
            parse_context_program_proposal(
                json.dumps(proposal),
                request=self.request,
                catalog=self.catalog,
                budget=self.budget,
            )


if __name__ == "__main__":
    unittest.main()
