from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_dispatch_binding_review as review_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_dispatch_binding import (
    build_builtin_dispatch_binder_registry,
)
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

    def test_bindable_set_exactly_matches_reviewed_dispatch_views_and_binder_registry(self) -> None:
        phase32 = build_builtin_capability_catalog()
        code_dispatch = build_builtin_dispatch_catalog(phase32)
        build_phase32 = CapabilityCatalog.create(
            (phase32.capability("build.integration"),),
            (phase32.adapter("originforge.build.integration"),),
        )
        build_dispatch = build_builtin_dispatch_catalog(build_phase32)
        simulation_phase32 = CapabilityCatalog.create(
            (phase32.capability("simulation.run"),),
            (phase32.adapter("originforge.simulation.deterministic"),),
        )
        simulation_dispatch = build_builtin_dispatch_catalog(simulation_phase32)
        pixelorama_phase32 = CapabilityCatalog.create(
            (phase32.capability("media.2d.export"),),
            (phase32.adapter("originforge.pixelorama.export"),),
        )
        pixelorama_dispatch = build_builtin_dispatch_catalog(pixelorama_phase32)
        pixelorama_source_phase32 = CapabilityCatalog.create(
            (phase32.capability("media.2d.source"),),
            (phase32.adapter("originforge.pixelorama.source"),),
        )
        pixelorama_source_dispatch = build_builtin_dispatch_catalog(
            pixelorama_source_phase32
        )
        blender_phase32 = CapabilityCatalog.create(
            (phase32.capability("media.3d.blender"),),
            (phase32.adapter("originforge.blender.model3d"),),
        )
        blender_dispatch = build_builtin_dispatch_catalog(blender_phase32)
        image_phase32 = CapabilityCatalog.create(
            (phase32.capability("image.generate"),),
            (phase32.adapter("originforge.image.generate"),),
        )
        image_dispatch = build_builtin_dispatch_catalog(image_phase32)
        ffmpeg_phase32 = CapabilityCatalog.create(
            (phase32.capability("media.audio.process"),),
            (phase32.adapter("originforge.audio.ffmpeg"),),
        )
        ffmpeg_dispatch = build_builtin_dispatch_catalog(ffmpeg_phase32)
        piper_phase32 = CapabilityCatalog.create(
            (phase32.capability("media.audio.tts"),),
            (phase32.adapter("originforge.audio.piper"),),
        )
        piper_dispatch = build_builtin_dispatch_catalog(piper_phase32)
        runtime_phase32 = CapabilityCatalog.create(
            (phase32.capability("runtime.observe"),),
            (phase32.adapter("originforge.runtime.observe"),),
        )
        runtime_dispatch = build_builtin_dispatch_catalog(runtime_phase32)
        playtest_phase32 = CapabilityCatalog.create(
            (phase32.capability("runtime.playtest"),),
            (phase32.adapter("originforge.playtest.cooperative"),),
        )
        playtest_dispatch = build_builtin_dispatch_catalog(playtest_phase32)
        binder_registry = build_builtin_dispatch_binder_registry()
        rows = builtin_binding_review()

        bindable = {
            value.adapter_id
            for value in rows
            if value.status is BuiltinBindingReviewStatus.BINDABLE
        }
        self.assertEqual(
            bindable,
            {
                "originforge.build.integration",
                "originforge.blender.model3d",
                "originforge.code.bounded-retry",
                "originforge.pixelorama.export",
                "originforge.pixelorama.source",
                "originforge.simulation.deterministic",
                "originforge.image.generate",
                "originforge.audio.ffmpeg",
                "originforge.audio.piper",
                "originforge.runtime.observe",
                "originforge.playtest.cooperative",
            },
        )
        reviewed_contracts = (
            *code_dispatch.contracts,
            *build_dispatch.contracts,
            *simulation_dispatch.contracts,
            *pixelorama_dispatch.contracts,
            *pixelorama_source_dispatch.contracts,
            *blender_dispatch.contracts,
            *image_dispatch.contracts,
            *ffmpeg_dispatch.contracts,
            *piper_dispatch.contracts,
            *runtime_dispatch.contracts,
            *playtest_dispatch.contracts,
        )
        self.assertEqual(
            bindable,
            {value.adapter_id for value in reviewed_contracts},
        )
        self.assertEqual(
            bindable,
            {value.adapter_id for value in binder_registry.descriptors},
        )
        contracts_by_adapter = {
            value.adapter_id: value.contract_id for value in reviewed_contracts
        }
        self.assertEqual(
            {
                value.adapter_id: value.dispatch_contract_id
                for value in binder_registry.descriptors
            },
            contracts_by_adapter,
        )
        self.assertEqual(code_dispatch.contract_ids, ("code.bounded-retry@1",))
        self.assertEqual(
            simulation_dispatch.contract_ids,
            ("simulation.deterministic@1",),
        )
        self.assertEqual(
            pixelorama_dispatch.contract_ids,
            ("pixelorama.spritesheet-export@1",),
        )
        self.assertEqual(
            blender_dispatch.contract_ids,
            ("blender.export-glb@1",),
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
        simulation = rows["originforge.simulation.deterministic"]
        pixelorama = rows["originforge.pixelorama.export"]
        self.assertEqual(ffmpeg.status, BuiltinBindingReviewStatus.BINDABLE)
        self.assertIsNone(ffmpeg.blocker)
        self.assertIn("PCM16 WAV", ffmpeg.reason)
        image = rows["originforge.image.generate"]
        self.assertEqual(image.status, BuiltinBindingReviewStatus.BINDABLE)
        self.assertIsNone(image.blocker)
        self.assertEqual(piper.status, BuiltinBindingReviewStatus.BINDABLE)
        self.assertIsNone(piper.blocker)
        self.assertIn("v25", piper.reason)
        self.assertEqual(simulation.status, BuiltinBindingReviewStatus.BINDABLE)
        self.assertIsNone(simulation.blocker)
        self.assertIn("zero-ref", simulation.reason)
        self.assertEqual(pixelorama.status, BuiltinBindingReviewStatus.BINDABLE)
        self.assertIsNone(pixelorama.blocker)
        self.assertIn("metadata-only", pixelorama.reason)

    def test_every_deferred_adapter_has_one_explicit_nonempty_blocker(self) -> None:
        rows = builtin_binding_review()
        deferred = [
            value
            for value in rows
            if value.status is BuiltinBindingReviewStatus.DEFERRED
        ]
        self.assertEqual(len(deferred), 1)
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
