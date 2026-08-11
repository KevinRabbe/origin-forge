from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_dispatch_binding_review as review_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_dispatch_binding import build_builtin_dispatch_binder_registry
from origin_forge.production_dispatch_binding_review import (
    BuiltinBindingReviewStatus,
    builtin_binding_review,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_work_order_builtin import build_builtin_dispatch_catalog
from origin_forge.production_work_order_models import WorkOrderRefType


class ProductionDispatchBindingReviewTests(unittest.TestCase):
    def test_every_phase32_builtin_adapter_is_reviewed_exactly_once(self) -> None:
        phase32 = build_builtin_capability_catalog()
        rows = builtin_binding_review()
        self.assertEqual(
            tuple(value.adapter_id for value in rows),
            tuple(sorted(phase32.adapter_ids)),
        )
        self.assertEqual(len(rows), len({value.adapter_id for value in rows}))

    def test_bindable_set_exactly_matches_dispatch_catalog_and_binder_registry(self) -> None:
        phase32 = build_builtin_capability_catalog()
        dispatch_catalog = build_builtin_dispatch_catalog(phase32)
        binder_registry = build_builtin_dispatch_binder_registry()
        rows = builtin_binding_review()

        bindable = {
            value.adapter_id
            for value in rows
            if value.status is BuiltinBindingReviewStatus.BINDABLE
        }
        self.assertEqual(bindable, {"originforge.code.bounded-retry"})
        self.assertEqual(
            bindable,
            {value.adapter_id for value in dispatch_catalog.contracts},
        )
        self.assertEqual(
            bindable,
            {value.adapter_id for value in binder_registry.descriptors},
        )
        self.assertEqual(
            binder_registry.descriptors[0].dispatch_contract_id,
            dispatch_catalog.contracts[0].contract_id,
        )

    def test_audio_profile_resolution_does_not_silently_promote_audio_backends(self) -> None:
        resolver_registry = build_dispatch_input_resolver_registry()
        claims = {
            claim.ref_type
            for descriptor in resolver_registry.descriptors
            for claim in descriptor.claims
        }
        self.assertIn(WorkOrderRefType.ARTIFACT, claims)
        self.assertIn(WorkOrderRefType.AUDIO_PROFILE, claims)

        rows = {value.adapter_id: value for value in builtin_binding_review()}
        ffmpeg = rows["originforge.audio.ffmpeg"]
        piper = rows["originforge.audio.piper"]
        self.assertEqual(ffmpeg.status, BuiltinBindingReviewStatus.DEFERRED)
        self.assertEqual(
            ffmpeg.blocker,
            "AUDIO_SOURCE_STRUCTURE_NOT_RESOLVED",
        )
        self.assertIn("PCM hash", ffmpeg.reason)
        self.assertEqual(piper.status, BuiltinBindingReviewStatus.DEFERRED)
        self.assertEqual(
            piper.blocker,
            "AUDIO_NATIVE_REQUEST_IDENTITY_INCOMPLETE",
        )
        self.assertIn("operation/workspace identity", piper.reason)

    def test_every_deferred_adapter_has_one_explicit_nonempty_blocker(self) -> None:
        rows = builtin_binding_review()
        deferred = [
            value
            for value in rows
            if value.status is BuiltinBindingReviewStatus.DEFERRED
        ]
        self.assertEqual(len(deferred), 9)
        self.assertTrue(all(value.blocker for value in deferred))
        self.assertEqual(
            len({value.blocker for value in deferred}),
            len(deferred),
        )
        self.assertTrue(all(value.reason.strip() for value in deferred))

    def test_review_module_has_no_backend_invocation_or_state_mutation_surface(self) -> None:
        source = inspect.getsource(review_module)
        self.assertNotIn("importlib", source)
        self.assertNotIn("subprocess", source)
        tree = ast.parse(source)
        forbidden = {
            "drive",
            "execute",
            "generate",
            "dispatch",
            "transition_task",
            "start_run",
            "create_run",
            "finish_run",
            "record_verification",
            "publish_work_order",
            "publish_audit",
            "resolve_and_publish",
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called_attributes | called_names))


if __name__ == "__main__":
    unittest.main()
