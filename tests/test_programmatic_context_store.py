from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_benchmark import (
    ContextExperimentObservation,
    ContextExperimentPolicy,
    ContextExperimentReport,
    compare_context_case,
)
from origin_forge.programmatic_context_interpreter import (
    ContextAdapterRegistry,
    ContextProgramInterpreter,
)
from origin_forge.programmatic_context_models import (
    ContextArgument,
    ContextInstruction,
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextProgram,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
)
from origin_forge.programmatic_context_store import (
    ProgrammaticContextStore,
    ProgrammaticContextStoreError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import canonical_bytes


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


class ProgrammaticContextStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("programmatic-context-store-test")
        self.store = ProgrammaticContextStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _objects(self):
        descriptor = ContextOperationDescriptor(
            operation_id="context.echo",
            version="1",
            adapter_fingerprint=HASH_A,
            input_schema_hash=HASH_B,
            output_schema_hash=HASH_C,
            max_calls=2,
            max_response_bytes=4096,
            replay_class=ContextReplayClass.DETERMINISTIC,
        )
        catalog = ContextOperationCatalog.create((descriptor,))
        request = ContextRequest.create(
            project_id=self.runtime.project_id(),
            objective="Persist exact programmatic context evidence.",
        )
        program = ContextProgram.create(
            request=request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(
                ContextInstruction(
                    0,
                    "echo",
                    "context.echo",
                    "1",
                    (ContextArgument.literal("value", {"x": 1}),),
                ),
            ),
            output_bindings=("echo",),
        )
        registry = ContextAdapterRegistry()
        registry.register(
            descriptor,
            lambda args: {"value": args["value"]},
            validate_input=lambda args: None,
            validate_output=lambda value: None,
        )
        result = ContextProgramInterpreter(registry).execute(
            request=request,
            catalog=catalog,
            program=program,
        )
        baseline = ContextExperimentObservation(True, 900, 3, 3000, 500, 12000, 1000, 100, HASH_D)
        programmatic = ContextExperimentObservation(True, 900, 2, 2000, 400, 8000, 1000, 90, HASH_C)
        policy = ContextExperimentPolicy()
        case = compare_context_case(
            case_id="store.case",
            case_hash=HASH_A,
            environment_hash=HASH_B,
            baseline=baseline,
            programmatic=programmatic,
            policy=policy,
        )
        experiment = ContextExperimentReport.create(
            program=program,
            policy=policy,
            cases=(case,),
        )
        return request, catalog, program, result.package, result.trace, experiment

    def test_publish_and_load_all_context_objects(self) -> None:
        request, catalog, program, package, execution, experiment = self._objects()
        published = (
            ("requests", request.request_id, request.content_hash, self.store.publish_request(request)),
            ("catalogs", catalog.catalog_id, catalog.content_hash, self.store.publish_catalog(catalog)),
            ("programs", program.program_id, program.content_hash, self.store.publish_program(program)),
            ("packages", package.package_id, package.content_hash, self.store.publish_package(package)),
            ("executions", execution.execution_id, execution.content_hash, self.store.publish_execution(execution)),
            ("experiments", experiment.experiment_id, experiment.content_hash, self.store.publish_experiment(experiment)),
        )
        for category, object_id, expected_hash, path in published:
            self.assertTrue(path.is_file())
            envelope = self.store.load(category, object_id)
            self.assertEqual(envelope["content_hash"], expected_hash)
            self.assertEqual(envelope["object_id"], object_id)

    def test_no_overwrite_even_for_identical_object(self) -> None:
        request, *_ = self._objects()
        self.store.publish_request(request)
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "already exists"):
            self.store.publish_request(request)

    def test_canonical_payload_tampering_is_detected(self) -> None:
        request, *_ = self._objects()
        path = self.store.publish_request(request)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["objective"] = "tampered"
        path.write_bytes(canonical_bytes(envelope))
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "content hash drifted"):
            self.store.load("requests", request.request_id)

    def test_noncanonical_rewrite_is_rejected(self) -> None:
        request, *_ = self._objects()
        path = self.store.publish_request(request)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "not canonical"):
            self.store.load("requests", request.request_id)

    def test_symlinked_category_and_object_are_rejected(self) -> None:
        request, *_ = self._objects()
        root = self.runtime.state_dir / "programmatic-context"
        root.mkdir()
        target_dir = self.runtime.state_dir / "outside-context"
        target_dir.mkdir()
        (root / "requests").symlink_to(target_dir, target_is_directory=True)
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "may not be a symlink"):
            self.store.publish_request(request)

        (root / "requests").unlink()
        (root / "requests").mkdir()
        target = self.runtime.state_dir / "outside-context.json"
        target.write_text("{}", encoding="utf-8")
        (root / "requests" / f"{request.request_id}.json").symlink_to(target)
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "may not be a symlink"):
            self.store.load("requests", request.request_id)

    def test_wrong_category_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProgrammaticContextStoreError, "invalid"):
            self.store.load("requests", new_id(IdKind.CONTEXT_PROGRAM))

    def test_listing_revalidates_objects(self) -> None:
        request, catalog, *_ = self._objects()
        self.store.publish_request(request)
        self.store.publish_catalog(catalog)
        self.assertEqual(
            self.store.list_objects("requests")[0]["content_hash"],
            request.content_hash,
        )
        self.assertEqual(
            self.store.list_objects("catalogs")[0]["object_id"],
            catalog.catalog_id,
        )


if __name__ == "__main__":
    unittest.main()
