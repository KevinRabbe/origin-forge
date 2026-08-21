from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.db import SCHEMA_VERSION
from origin_forge.ids import IdKind, new_id
from origin_forge.production_pixelorama_dispatch_output_binding_models import (
    PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
    PIXELORAMA_EXECUTION_OWNER_ID,
    PixeloramaDispatchOutputBinding,
    PixeloramaDispatchOutputBindingModelError,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    PixeloramaDispatchOutputBindingReadError,
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_dispatch_output_binding_store import (
    PixeloramaDispatchOutputBindingConflict,
    PixeloramaDispatchOutputBindingStoreError,
    publish_pixelorama_dispatch_output_binding,
)
from origin_forge.runtime import OriginForgeRuntime


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64


class PixeloramaDispatchOutputBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase49a-binding")
        self.project_id = self.runtime.project_id()
        self.execution = self._insert_execution()
        self.binding = self._binding_for(self.execution)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _insert_execution(self) -> dict[str, object]:
        data: dict[str, object] = {
            "execution_id": new_id(IdKind.DISPATCH_EXECUTION),
            "project_id": self.project_id,
            "claim_id": new_id(IdKind.DISPATCH_CLAIM),
            "claim_revision_at_start": 0,
            "task_id": new_id(IdKind.TASK),
            "task_revision": 1,
            "task_content_hash": _HASH_A,
            "work_order_id": new_id(IdKind.PRODUCTION_WORK_ORDER),
            "work_order_hash": _HASH_B,
            "input_resolution_id": new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
            "input_resolution_hash": _HASH_C,
            "dispatch_binding_id": new_id(IdKind.DISPATCH_BINDING),
            "dispatch_binding_hash": _HASH_D,
            "binding_audit_id": new_id(IdKind.DISPATCH_BINDING_AUDIT),
            "binding_audit_hash": _HASH_E,
            "selected_adapter_id": "originforge.pixelorama.spritesheet-export",
            "selected_adapter_fingerprint": _HASH_A,
            "dispatch_contract_id": "pixelorama.spritesheet-export@1",
            "dispatch_contract_hash": _HASH_B,
            "binder_id": "binder.pixelorama.spritesheet-export@1",
            "binder_fingerprint": _HASH_C,
            "execution_owner_id": PIXELORAMA_EXECUTION_OWNER_ID,
            "execution_owner_fingerprint": _HASH_D,
            "runtime_dependency_plan_hash": _HASH_E,
            "status": "STARTED",
            "revision": 0,
            "created_at": "2026-08-16T16:00:00Z",
            "updated_at": "2026-08-16T16:00:00Z",
            "terminal_detail_hash": None,
        }
        conn = sqlite3.connect(self.runtime.store.db_path)
        try:
            conn.execute(
                """INSERT INTO dispatch_executions(
                       execution_id, project_id, claim_id, claim_revision_at_start,
                       task_id, task_revision, task_content_hash,
                       work_order_id, work_order_hash,
                       input_resolution_id, input_resolution_hash,
                       dispatch_binding_id, dispatch_binding_hash,
                       binding_audit_id, binding_audit_hash,
                       selected_adapter_id, selected_adapter_fingerprint,
                       dispatch_contract_id, dispatch_contract_hash,
                       binder_id, binder_fingerprint,
                       execution_owner_id, execution_owner_fingerprint,
                       runtime_dependency_plan_hash, status, revision,
                       created_at, updated_at, terminal_detail_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(data[key] for key in (
                    "execution_id", "project_id", "claim_id", "claim_revision_at_start",
                    "task_id", "task_revision", "task_content_hash", "work_order_id",
                    "work_order_hash", "input_resolution_id", "input_resolution_hash",
                    "dispatch_binding_id", "dispatch_binding_hash", "binding_audit_id",
                    "binding_audit_hash", "selected_adapter_id", "selected_adapter_fingerprint",
                    "dispatch_contract_id", "dispatch_contract_hash", "binder_id",
                    "binder_fingerprint", "execution_owner_id", "execution_owner_fingerprint",
                    "runtime_dependency_plan_hash", "status", "revision", "created_at",
                    "updated_at", "terminal_detail_hash",
                )),
            )
            conn.commit()
        finally:
            conn.close()
        return data

    def _binding_for(self, execution: dict[str, object]) -> PixeloramaDispatchOutputBinding:
        return PixeloramaDispatchOutputBinding(
            execution_id=str(execution["execution_id"]),
            claim_id=str(execution["claim_id"]),
            task_id=str(execution["task_id"]),
            task_revision=int(execution["task_revision"]),
            task_content_hash=str(execution["task_content_hash"]),
            work_order_id=str(execution["work_order_id"]),
            work_order_hash=str(execution["work_order_hash"]),
            dispatch_binding_id=str(execution["dispatch_binding_id"]),
            dispatch_binding_hash=str(execution["dispatch_binding_hash"]),
            execution_owner_id=str(execution["execution_owner_id"]),
            run_id=new_id(IdKind.RUN),
            request_artifact_id=new_id(IdKind.ARTIFACT),
            result_artifact_id=new_id(IdKind.ARTIFACT),
            output_artifact_id=new_id(IdKind.ARTIFACT),
            output_verification_id=new_id(IdKind.VERIFICATION),
            run_verification_id=new_id(IdKind.VERIFICATION),
            output_content_hash=_HASH_A,
            output_byte_count=1234,
            schema_version=PIXELORAMA_DISPATCH_OUTPUT_BINDING_SCHEMA_VERSION,
            created_at="2026-08-16T16:01:00Z",
        )

    def test_schema_13_binding_table_survives_schema_14_with_unique_output_identities(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 17)
        with self.runtime.store.session() as conn:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("pixelorama_dispatch_output_bindings",),
            ).fetchone()[0]
            self.assertIn("execution_id TEXT PRIMARY KEY", sql)
            for column in (
                "claim_id", "run_id", "request_artifact_id", "result_artifact_id",
                "output_artifact_id", "output_verification_id", "run_verification_id",
            ):
                self.assertIn(f"{column} TEXT NOT NULL UNIQUE", sql)
            self.assertIn("CHECK (schema_version = 1)", sql)
            self.assertIn("CHECK (output_byte_count >= 0)", sql)

    def test_publish_read_round_trip_and_exact_duplicate_are_idempotent(self) -> None:
        first = publish_pixelorama_dispatch_output_binding(self.runtime, self.binding)
        second = publish_pixelorama_dispatch_output_binding(self.runtime, self.binding)
        read_back = read_pixelorama_dispatch_output_binding(
            self.runtime, self.binding.execution_id
        )
        self.assertEqual(first, self.binding)
        self.assertEqual(second, self.binding)
        self.assertEqual(read_back, self.binding)
        with self.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM pixelorama_dispatch_output_bindings"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_execution_with_different_relation_fails_closed(self) -> None:
        publish_pixelorama_dispatch_output_binding(self.runtime, self.binding)
        conflicting = replace(
            self.binding,
            output_artifact_id=new_id(IdKind.ARTIFACT),
        )
        with self.assertRaises(PixeloramaDispatchOutputBindingConflict):
            publish_pixelorama_dispatch_output_binding(self.runtime, conflicting)

    def test_unique_pixelorama_output_identities_cannot_be_reused_by_second_execution(self) -> None:
        publish_pixelorama_dispatch_output_binding(self.runtime, self.binding)
        second_execution = self._insert_execution()
        fresh = self._binding_for(second_execution)
        unique_fields = (
            "run_id", "request_artifact_id", "result_artifact_id", "output_artifact_id",
            "output_verification_id", "run_verification_id",
        )
        for field in unique_fields:
            candidate = replace(fresh, **{field: getattr(self.binding, field)})
            with self.subTest(field=field):
                with self.assertRaises(PixeloramaDispatchOutputBindingConflict):
                    publish_pixelorama_dispatch_output_binding(self.runtime, candidate)

    def test_binding_must_match_frozen_execution_authority(self) -> None:
        wrong = replace(self.binding, task_content_hash=_HASH_B)
        with self.assertRaises(PixeloramaDispatchOutputBindingStoreError):
            publish_pixelorama_dispatch_output_binding(self.runtime, wrong)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pixelorama_dispatch_output_bindings"
                ).fetchone()[0],
                0,
            )

    def test_model_rejects_malformed_or_ambiguous_identity(self) -> None:
        with self.assertRaises(PixeloramaDispatchOutputBindingModelError):
            replace(self.binding, execution_id="DISPEXEC-not-a-uuid")
        with self.assertRaises(PixeloramaDispatchOutputBindingModelError):
            replace(self.binding, output_content_hash="A" * 64)
        with self.assertRaises(PixeloramaDispatchOutputBindingModelError):
            replace(self.binding, output_byte_count=-1)
        with self.assertRaises(PixeloramaDispatchOutputBindingModelError):
            replace(self.binding, schema_version=2)
        with self.assertRaises(PixeloramaDispatchOutputBindingModelError):
            replace(
                self.binding,
                result_artifact_id=self.binding.request_artifact_id,
            )

    def test_read_rejects_missing_and_tampered_execution_relation(self) -> None:
        with self.assertRaises(PixeloramaDispatchOutputBindingReadError):
            read_pixelorama_dispatch_output_binding(self.runtime, self.binding.execution_id)
        publish_pixelorama_dispatch_output_binding(self.runtime, self.binding)
        conn = sqlite3.connect(self.runtime.store.db_path)
        try:
            conn.execute(
                "UPDATE dispatch_executions SET task_content_hash = ? WHERE execution_id = ?",
                (_HASH_B, self.binding.execution_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(PixeloramaDispatchOutputBindingReadError):
            read_pixelorama_dispatch_output_binding(self.runtime, self.binding.execution_id)


if __name__ == "__main__":
    unittest.main()
