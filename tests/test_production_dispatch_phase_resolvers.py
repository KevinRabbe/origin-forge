from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_dispatch_phase_resolvers as phase_resolver_module
from origin_forge.audio_models import AudioOperation
from origin_forge.audio_profiles import (
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_phase_resolvers import (
    AudioProfileInputResolver,
    PhaseSpecificResolverReviewStatus,
    build_dispatch_input_resolver_registry,
    phase_specific_resolver_review,
)
from origin_forge.production_dispatch_resolvers import DispatchInputResolutionError
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.runtime import OriginForgeRuntime


_RUNTIME_HASH = "sha256:" + "1" * 64


def _state_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    if not root.exists():
        return ()
    rows: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            rows.append((path.relative_to(root).as_posix(), b"<symlink>"))
        elif path.is_file():
            rows.append((path.relative_to(root).as_posix(), path.read_bytes()))
    return tuple(rows)


class ProductionDispatchPhaseResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase34-protected-resolvers")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _profile(self) -> GovernedAudioProfile:
        return GovernedAudioProfile.create(
            kind=AudioProfileKind.PROCEDURAL_SFX,
            operation=AudioOperation.SYNTHESIZE_SFX,
            backend_id="origin-forge-procedural",
            backend_version="1",
            runtime_hash=_RUNTIME_HASH,
            target_sample_rate=48_000,
            target_channels=1,
        )

    @staticmethod
    def _ref(profile: GovernedAudioProfile, *, revision: int | None = None, role: str = "audio_profile") -> WorkOrderInputRef:
        return WorkOrderInputRef(
            WorkOrderRefType.AUDIO_PROFILE,
            profile.profile_id,
            profile.profile_hash.removeprefix("sha256:"),
            role,
            revision,
        )

    def test_audio_profile_resolution_binds_exact_immutable_profile_without_mutation(self) -> None:
        profile = self._profile()
        AudioProfileStore(self.runtime).put(profile)
        before = _state_snapshot(self.runtime.state_dir)

        resolved = build_dispatch_input_resolver_registry().resolve(
            self.runtime,
            self._ref(profile),
        )

        self.assertEqual(resolved.source_id, profile.profile_id)
        self.assertEqual(
            resolved.source_content_hash,
            profile.profile_hash.removeprefix("sha256:"),
        )
        self.assertEqual(resolved.source_revision, None)
        self.assertEqual(resolved.source_object_type, "AUDIO_PROFILE")
        self.assertEqual(resolved.resolution_class, "PROTECTED_AUDIO_PROFILE")
        self.assertEqual(resolved.projection, profile.to_dict())
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

    def test_missing_audio_profile_read_is_noncreating_and_cross_project_ref_fails_closed(self) -> None:
        profile = self._profile()
        ref = self._ref(profile)
        audio_root = self.runtime.state_dir / "audio-profiles"
        self.assertFalse(audio_root.exists())
        before = _state_snapshot(self.runtime.state_dir)
        with self.assertRaisesRegex(
            DispatchInputResolutionError,
            "exact ID/hash",
        ):
            build_dispatch_input_resolver_registry().resolve(self.runtime, ref)
        self.assertFalse(audio_root.exists())
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

        AudioProfileStore(self.runtime).put(profile)
        with tempfile.TemporaryDirectory() as other_dir:
            other = OriginForgeRuntime(other_dir)
            other.initialize("other-project")
            other_before = _state_snapshot(other.state_dir)
            with self.assertRaisesRegex(
                DispatchInputResolutionError,
                "exact ID/hash",
            ):
                build_dispatch_input_resolver_registry().resolve(other, ref)
            self.assertEqual(other_before, _state_snapshot(other.state_dir))
            self.assertFalse((other.state_dir / "audio-profiles").exists())

    def test_revision_role_and_tamper_fail_closed(self) -> None:
        profile = self._profile()
        stored = AudioProfileStore(self.runtime).put(profile)
        resolver = AudioProfileInputResolver()

        with self.assertRaisesRegex(
            DispatchInputResolutionError,
            "not revision-numbered",
        ):
            resolver.resolve(self.runtime, self._ref(profile, revision=1))

        wrong_role = self._ref(profile, role="source")
        with self.assertRaisesRegex(
            DispatchInputResolutionError,
            "no trusted input resolver",
        ):
            build_dispatch_input_resolver_registry().resolve(self.runtime, wrong_role)

        value = json.loads(stored.path.read_text(encoding="utf-8"))
        value["target_channels"] = 2
        stored.path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            DispatchInputResolutionError,
            "canonical protected-store revalidation",
        ):
            resolver.resolve(self.runtime, self._ref(profile))

    def test_combined_registry_is_deterministic_and_adds_reviewed_phase_claims(self) -> None:
        first = build_dispatch_input_resolver_registry()
        second = build_dispatch_input_resolver_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(
            tuple(value.resolver_id for value in first.descriptors),
            (
                "resolver.core.artifact@1",
                "resolver.core.design-rule@1",
                "resolver.core.project-entity@1",
                "resolver.core.verification@1",
                "resolver.phase.audio-profile@1",
                "resolver.phase.model3d-request@1",
            ),
        )
        phase_claims = [
            claim
            for descriptor in first.descriptors
            if descriptor.resolver_id.startswith("resolver.phase.")
            for claim in descriptor.claims
        ]
        self.assertEqual(len(phase_claims), 2)
        claims = {claim.ref_type: claim for claim in phase_claims}
        audio_claim = claims[WorkOrderRefType.AUDIO_PROFILE]
        self.assertEqual(audio_claim.source_id_prefix, "AUDPROF-")
        self.assertEqual(audio_claim.source_object_type, "AUDIO_PROFILE")
        self.assertEqual(audio_claim.role, "audio_profile")
        model3d_claim = claims[WorkOrderRefType.MODEL3D_REQUEST]
        self.assertEqual(model3d_claim.source_id_prefix, "MODEL3DREQ-")
        self.assertEqual(model3d_claim.source_object_type, "MODEL3D_REQUEST")
        self.assertEqual(model3d_claim.role, "model3d_request")

    def test_review_keeps_unproven_phase_families_explicitly_deferred(self) -> None:
        rows = phase_specific_resolver_review()
        self.assertEqual(
            tuple(value.evidence_family for value in rows),
            (
                "audio-profile",
                "image-workflow",
                "media-profile",
                "model3d-request",
                "phase-specific-evidence",
                "playtest-scenario",
                "runtime-observation-request",
                "simulation-spec",
            ),
        )
        supported = [
            value.evidence_family
            for value in rows
            if value.status is PhaseSpecificResolverReviewStatus.SUPPORTED
        ]
        self.assertEqual(supported, ["audio-profile", "model3d-request"])
        self.assertTrue(
            all(
                value.status is not PhaseSpecificResolverReviewStatus.SUPPORTED
                for value in rows
                if value.evidence_family not in {"audio-profile", "model3d-request"}
            )
        )

        generic_ref = WorkOrderInputRef(
            WorkOrderRefType.PHASE_SPECIFIC_EVIDENCE,
            new_id(IdKind.MEDIA_FINGERPRINT),
            "a" * 64,
            "media_fingerprint",
            None,
        )
        with self.assertRaisesRegex(
            DispatchInputResolutionError,
            "no trusted input resolver",
        ):
            build_dispatch_input_resolver_registry().resolve(self.runtime, generic_ref)

    def test_phase_resolver_source_has_no_scan_mutation_or_execution_surface(self) -> None:
        source = inspect.getsource(phase_resolver_module)
        self.assertNotIn("importlib", source)
        self.assertNotIn("subprocess", source)
        tree = ast.parse(source)
        forbidden = {
            "execute",
            "drive",
            "generate",
            "dispatch",
            "transition_task",
            "start_run",
            "create_run",
            "put",
            "list",
            "publish_work_order",
            "publish_audit",
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
