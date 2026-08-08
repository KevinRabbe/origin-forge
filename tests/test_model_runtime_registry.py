from __future__ import annotations

import unittest

from origin_forge.model_runtime_registry import (
    ModelRuntimeBinding,
    ModelRuntimeRegistry,
    ModelRuntimeRegistryError,
)
from origin_forge.model_scheduler import ModelResourceProfile, ModelRole
from origin_forge.resource_scheduler import ResourceLease, ResourceRequest


class RuntimeLoader:
    def __init__(self, name: str, *, instance=None):
        self.name = name
        self.instance = instance
        self.loaded = []
        self.unloaded = []

    def load(self, profile, lease):
        self.loaded.append((profile.profile_id, lease.lease_id))
        return self.instance if self.instance is not None else {"runtime": self.name, "n": len(self.loaded)}

    def unload(self, instance):
        self.unloaded.append(instance)


class ModelRuntimeRegistryTests(unittest.TestCase):
    @staticmethod
    def _profile(runtime_id: str, profile_id: str = "profile") -> ModelResourceProfile:
        return ModelResourceProfile(
            profile_id,
            ModelRole.CODER_STRONG,
            f"model-{profile_id}",
            runtime_id,
            ResourceRequest(cpu_slots=1),
        )

    @staticmethod
    def _lease(lease_id: str = "LEASE-1") -> ResourceLease:
        return ResourceLease(lease_id, "RUN-test", 1, 0, None)

    def test_registry_is_deterministic_and_rejects_duplicates(self) -> None:
        a = RuntimeLoader("a")
        b = RuntimeLoader("b")
        registry = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-b", b), ModelRuntimeBinding("runtime-a", a))
        )
        self.assertEqual(registry.runtime_ids(), ("runtime-a", "runtime-b"))
        self.assertIs(registry.loader("runtime-a"), a)
        with self.assertRaises(ModelRuntimeRegistryError):
            ModelRuntimeRegistry(
                (ModelRuntimeBinding("runtime-a", a), ModelRuntimeBinding("runtime-a", b))
            )

    def test_dispatches_load_and_unload_to_profile_runtime(self) -> None:
        a = RuntimeLoader("a")
        b = RuntimeLoader("b")
        dispatch = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-a", a), ModelRuntimeBinding("runtime-b", b))
        ).dispatch_loader()

        first = dispatch.load(self._profile("runtime-a", "a"), self._lease("LEASE-a"))
        second = dispatch.load(self._profile("runtime-b", "b"), self._lease("LEASE-b"))
        self.assertEqual(dispatch.active_runtime_ids(), ("runtime-a", "runtime-b"))
        self.assertEqual(a.loaded, [("a", "LEASE-a")])
        self.assertEqual(b.loaded, [("b", "LEASE-b")])

        dispatch.unload(second)
        dispatch.unload(first)
        self.assertEqual(len(a.unloaded), 1)
        self.assertEqual(len(b.unloaded), 1)
        self.assertEqual(dispatch.active_runtime_ids(), ())

    def test_unknown_runtime_fails_before_loader_call(self) -> None:
        loader = RuntimeLoader("a")
        dispatch = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-a", loader),)
        ).dispatch_loader()
        with self.assertRaisesRegex(ModelRuntimeRegistryError, "unknown configured"):
            dispatch.load(self._profile("missing"), self._lease())
        self.assertEqual(loader.loaded, [])
        self.assertEqual(dispatch.active_runtime_ids(), ())

    def test_none_instance_is_rejected_and_not_tracked(self) -> None:
        class NoneLoader:
            def load(self, profile, lease):
                return None

            def unload(self, instance):
                raise AssertionError("must not unload an instance that never existed")

        dispatch = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-none", NoneLoader()),)
        ).dispatch_loader()
        with self.assertRaisesRegex(ModelRuntimeRegistryError, "returned no instance"):
            dispatch.load(self._profile("runtime-none"), self._lease())
        self.assertEqual(dispatch.active_runtime_ids(), ())

    def test_unowned_instance_cannot_be_unloaded(self) -> None:
        dispatch = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-a", RuntimeLoader("a")),)
        ).dispatch_loader()
        with self.assertRaisesRegex(ModelRuntimeRegistryError, "not owned"):
            dispatch.unload(object())

    def test_active_instance_reuse_is_rejected(self) -> None:
        shared = object()
        loader = RuntimeLoader("a", instance=shared)
        dispatch = ModelRuntimeRegistry(
            (ModelRuntimeBinding("runtime-a", loader),)
        ).dispatch_loader()
        first = dispatch.load(self._profile("runtime-a", "one"), self._lease("LEASE-1"))
        with self.assertRaisesRegex(ModelRuntimeRegistryError, "already-active"):
            dispatch.load(self._profile("runtime-a", "two"), self._lease("LEASE-2"))
        self.assertEqual(dispatch.active_runtime_ids(), ("runtime-a",))
        dispatch.unload(first)


if __name__ == "__main__":
    unittest.main()
