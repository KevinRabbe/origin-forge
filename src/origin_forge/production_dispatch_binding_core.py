from __future__ import annotations

from typing import Protocol, Sequence

from .ids import IdKind, new_id
from .production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBinderDescriptor,
    DispatchBinding,
    DispatchBindingAudit,
    DispatchBindingCurrentness,
    DispatchBindingCurrentnessStatus,
    DispatchBindingModelError,
)
from .production_dispatch_resolution_models import InputResolutionBundle
from .production_dispatch_resolvers import (
    DispatchInputResolutionError,
    WorkOrderInputResolverRegistry,
)
from .production_work_order_audit import (
    WorkOrderAuditStatus,
    WorkOrderCurrentnessStatus,
    inspect_work_order_currentness,
)
from .production_work_order_build import (
    BUILD_ADAPTER_ID,
    BUILD_CONTRACT_ID,
    BUILD_REQUEST_TYPE_ID,
)
from .production_work_order_models import canonical_bytes, content_hash
from .production_work_order_store import (
    ProductionWorkOrderStore,
    ProductionWorkOrderStoreError,
)
from .production_work_orders import ProductionWorkOrder


class DispatchBindingError(RuntimeError):
    pass


class DispatchInputBinder(Protocol):
    @property
    def descriptor(self) -> DispatchBinderDescriptor: ...

    def bind(
        self,
        work_order: ProductionWorkOrder,
        bundle: InputResolutionBundle,
    ) -> object: ...


class CodeBoundedRetryInputBinder:
    """Reconstruct inert `BoundedRetryPolicy.drive()` arguments without calling it."""

    _REQUEST_SCHEMA = {
        "request_type": "BoundedRetryPolicy.drive@1",
        "fields": {
            "task_id": "TASK ID",
            "selected_paths": "canonical string list",
            "auto_context": "boolean",
            "context_seed_paths": "canonical string list",
            "structural_context": "boolean",
            "semantic_context": "boolean",
        },
        "injected_later": [
            "model adapters",
            "sandbox backend",
            "workspace manager",
            "runtime instance",
        ],
        "adapter_invocation": False,
    }
    _SCHEMA_HASH = content_hash(_REQUEST_SCHEMA)
    _FINGERPRINT = content_hash(
        {
            "implementation_id": "origin-forge-code-bounded-retry-dispatch-binder@1",
            "adapter_id": "originforge.code.bounded-retry",
            "dispatch_contract_id": "code.bounded-retry@1",
            "request_schema": _REQUEST_SCHEMA,
            "mapping": {
                "task_id": "WorkOrder.task_id",
                "selected_paths": "WorkOrder.payload.selected_paths",
                "auto_context": "WorkOrder.payload.context_mode == auto",
                "context_seed_paths": "WorkOrder.payload.context_seed_paths",
                "structural_context": "WorkOrder.payload.structural_context",
                "semantic_context": "WorkOrder.payload.semantic_context",
            },
        }
    )
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id="binder.code.bounded-retry@1",
        binder_fingerprint=_FINGERPRINT,
        adapter_id="originforge.code.bounded-retry",
        dispatch_contract_id="code.bounded-retry@1",
        request_type_id="BoundedRetryPolicy.drive@1",
        request_schema_hash=_SCHEMA_HASH,
        accepted_input_roles=(),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(
        self,
        work_order: ProductionWorkOrder,
        bundle: InputResolutionBundle,
    ) -> object:
        if not isinstance(work_order, ProductionWorkOrder):
            raise TypeError("work_order must be a ProductionWorkOrder")
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
        ):
            raise DispatchBindingError(
                "binder WorkOrder does not match the exact input-resolution bundle"
            )
        if (
            work_order.selected_adapter_id != self.descriptor.adapter_id
            or work_order.dispatch_contract_id != self.descriptor.dispatch_contract_id
        ):
            raise DispatchBindingError(
                "bounded-retry binder does not match WorkOrder adapter/contract"
            )
        if bundle.resolved_inputs or work_order.input_refs:
            raise DispatchBindingError(
                "bounded-retry binder accepts no resolved input refs"
            )

        payload = work_order.payload
        expected_fields = {
            "context_mode",
            "selected_paths",
            "context_seed_paths",
            "structural_context",
            "semantic_context",
        }
        if set(payload) != expected_fields:
            raise DispatchBindingError(
                "bounded-retry WorkOrder payload is not the normalized exact contract"
            )
        mode = payload["context_mode"]
        if mode not in {"auto", "manual"}:
            raise DispatchBindingError("bounded-retry context_mode is invalid")
        selected = payload["selected_paths"]
        seeds = payload["context_seed_paths"]
        structural = payload["structural_context"]
        semantic = payload["semantic_context"]
        if (
            not isinstance(selected, list)
            or not all(isinstance(value, str) for value in selected)
            or not isinstance(seeds, list)
            or not all(isinstance(value, str) for value in seeds)
            or type(structural) is not bool
            or type(semantic) is not bool
        ):
            raise DispatchBindingError(
                "bounded-retry normalized payload types drifted"
            )
        if mode == "auto":
            if selected:
                raise DispatchBindingError(
                    "automatic bounded-retry binding may not carry selected_paths"
                )
        elif not selected or seeds:
            raise DispatchBindingError(
                "manual bounded-retry binding requires selected_paths and no seeds"
            )

        return {
            "task_id": work_order.task_id,
            "selected_paths": list(selected),
            "auto_context": mode == "auto",
            "context_seed_paths": list(seeds),
            "structural_context": structural,
            "semantic_context": semantic,
        }


class BuildIntegrationInputBinder:
    """Bind the inert build selector; commands are loaded from project config."""

    _SCHEMA = {
        "request_type": BUILD_REQUEST_TYPE_ID,
        "fields": {"task_id": "TASK ID", "operation": "BUILD", "workspace_id": "WSPACE ID", "workspace_revision": "revision"},
        "injected_later": ["approved build commands", "sandbox backend", "workspace manager"],
        "adapter_invocation": False,
    }
    _SCHEMA_HASH = content_hash(_SCHEMA)
    _FINGERPRINT = content_hash(
        {
            "implementation_id": "origin-forge-build-integration-dispatch-binder@1",
            "adapter_id": BUILD_ADAPTER_ID,
            "dispatch_contract_id": BUILD_CONTRACT_ID,
            "request_schema": _SCHEMA,
        }
    )
    _DESCRIPTOR = DispatchBinderDescriptor(
        binder_id="binder.build.integration@1",
        binder_fingerprint=_FINGERPRINT,
        adapter_id=BUILD_ADAPTER_ID,
        dispatch_contract_id=BUILD_CONTRACT_ID,
        request_type_id=BUILD_REQUEST_TYPE_ID,
        request_schema_hash=_SCHEMA_HASH,
        accepted_input_roles=("build_workspace",),
    )

    @property
    def descriptor(self) -> DispatchBinderDescriptor:
        return self._DESCRIPTOR

    def bind(
        self,
        work_order: ProductionWorkOrder,
        bundle: InputResolutionBundle,
    ) -> object:
        if not isinstance(work_order, ProductionWorkOrder) or not isinstance(
            bundle, InputResolutionBundle
        ):
            raise TypeError("build binder requires a WorkOrder and input bundle")
        if (
            work_order.work_order_id != bundle.work_order_id
            or work_order.content_hash != bundle.work_order_hash
            or work_order.selected_adapter_id != BUILD_ADAPTER_ID
            or work_order.dispatch_contract_id != BUILD_CONTRACT_ID
            or len(bundle.resolved_inputs) != 1
            or len(work_order.input_refs) != 1
        ):
            raise DispatchBindingError("build binder relation is not exact")
        resolved = bundle.resolved_inputs[0]
        if (
            resolved.original_ref.role != "build_workspace"
            or resolved.source_object_type != "WORKSPACE"
            or resolved.resolution_class != "AUDITED_WORKSPACE"
        ):
            raise DispatchBindingError("build binder requires one audited Workspace ref")
        if work_order.payload != {"operation": "BUILD"}:
            raise DispatchBindingError("build WorkOrder payload is not the exact BUILD selector")
        return {
            "task_id": work_order.task_id,
            "operation": "BUILD",
            "workspace_id": resolved.original_ref.ref_id,
            "workspace_revision": resolved.original_ref.revision,
        }


class DispatchInputBinderRegistry:
    def __init__(self, binders: Sequence[DispatchInputBinder]):
        values = tuple(binders)
        if not values:
            raise ValueError("binder registry must not be empty")
        descriptors: list[DispatchBinderDescriptor] = []
        for binder in values:
            descriptor = getattr(binder, "descriptor", None)
            if not isinstance(descriptor, DispatchBinderDescriptor) or not callable(
                getattr(binder, "bind", None)
            ):
                raise TypeError("binder registry values must implement DispatchInputBinder")
            descriptors.append(descriptor)
        ids = [value.binder_id for value in descriptors]
        if len(ids) != len(set(ids)):
            raise ValueError("binder registry contains duplicate binder IDs")
        relations = [
            (value.adapter_id, value.dispatch_contract_id) for value in descriptors
        ]
        if len(relations) != len(set(relations)):
            raise ValueError("binder registry contains ambiguous adapter/contract bindings")
        paired = sorted(
            zip(values, descriptors),
            key=lambda value: value[1].binder_id,
        )
        self._binders = tuple(value[0] for value in paired)
        self._descriptors = tuple(value[1] for value in paired)
        self._fingerprint = content_hash(
            {"binders": [value.to_dict() for value in self._descriptors]}
        )

    @property
    def descriptors(self) -> tuple[DispatchBinderDescriptor, ...]:
        return self._descriptors

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def binder_for(self, bundle: InputResolutionBundle) -> DispatchInputBinder:
        if not isinstance(bundle, InputResolutionBundle):
            raise TypeError("bundle must be an InputResolutionBundle")
        matches = [
            binder
            for binder in self._binders
            if binder.descriptor.adapter_id == bundle.selected_adapter_id
            and binder.descriptor.dispatch_contract_id == bundle.dispatch_contract_id
        ]
        if not matches:
            raise DispatchBindingError(
                "no trusted binder for resolved WorkOrder adapter/contract"
            )
        if len(matches) != 1:
            raise DispatchBindingError("dispatch binder selection is ambiguous")
        binder = matches[0]
        roles = {value.original_ref.role for value in bundle.resolved_inputs}
        if roles != set(binder.descriptor.accepted_input_roles):
            raise DispatchBindingError(
                "resolved input roles do not exactly match trusted binder contract"
            )
        return binder


def builtin_dispatch_binders() -> tuple[DispatchInputBinder, ...]:
    return (BuildIntegrationInputBinder(), CodeBoundedRetryInputBinder())


def build_builtin_dispatch_binder_registry() -> DispatchInputBinderRegistry:
    return DispatchInputBinderRegistry(builtin_dispatch_binders())


def _reconstruct_bundle(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    work_order_id: str,
    audit_id: str,
    *,
    bundle_id: str,
) -> InputResolutionBundle:
    if not isinstance(store, ProductionWorkOrderStore):
        raise TypeError("store must be a ProductionWorkOrderStore")
    if not isinstance(resolver_registry, WorkOrderInputResolverRegistry):
        raise TypeError("resolver_registry must be a WorkOrderInputResolverRegistry")
    work_order = store.load_work_order(work_order_id)
    audit = store.load_audit(audit_id)
    if audit.status is not WorkOrderAuditStatus.PASS:
        raise DispatchBindingError("input resolution requires exact WORKAUD PASS")
    if (
        audit.work_order_id != work_order.work_order_id
        or audit.work_order_hash != work_order.content_hash
        or audit.task_id != work_order.task_id
        or audit.task_revision != work_order.task_revision
        or audit.task_content_hash != work_order.task_content_hash
        or audit.route_decision_id != work_order.route_decision_id
        or audit.route_decision_hash != work_order.route_decision_hash
        or audit.dispatch_catalog_id != work_order.dispatch_catalog_id
        or audit.dispatch_catalog_hash != work_order.dispatch_catalog_hash
        or audit.dispatch_contract_id != work_order.dispatch_contract_id
        or audit.dispatch_contract_hash != work_order.dispatch_contract_hash
    ):
        raise DispatchBindingError(
            "WorkOrder audit does not bind the exact frozen WorkOrder relation"
        )
    resolved = resolver_registry.resolve_all(store.runtime, work_order.input_refs)
    return InputResolutionBundle(
        input_resolution_id=bundle_id,
        work_order_id=work_order.work_order_id,
        work_order_hash=work_order.content_hash,
        work_order_audit_id=audit.work_order_audit_id,
        work_order_audit_hash=audit.content_hash,
        task_id=work_order.task_id,
        task_revision=work_order.task_revision,
        task_content_hash=work_order.task_content_hash,
        route_decision_id=work_order.route_decision_id,
        route_decision_hash=work_order.route_decision_hash,
        selected_adapter_id=work_order.selected_adapter_id,
        selected_adapter_fingerprint=work_order.selected_adapter_fingerprint,
        dispatch_catalog_id=work_order.dispatch_catalog_id,
        dispatch_catalog_hash=work_order.dispatch_catalog_hash,
        dispatch_contract_id=work_order.dispatch_contract_id,
        dispatch_contract_hash=work_order.dispatch_contract_hash,
        resolver_registry_fingerprint=resolver_registry.fingerprint,
        resolved_inputs=resolved,
    )


def create_input_resolution_bundle(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    work_order_id: str,
    audit_id: str,
) -> InputResolutionBundle:
    return _reconstruct_bundle(
        store,
        resolver_registry,
        work_order_id,
        audit_id,
        bundle_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
    )


def _require_bundle_revalidates(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    bundle: InputResolutionBundle,
) -> ProductionWorkOrder:
    if not isinstance(bundle, InputResolutionBundle):
        raise TypeError("bundle must be an InputResolutionBundle")
    expected = _reconstruct_bundle(
        store,
        resolver_registry,
        bundle.work_order_id,
        bundle.work_order_audit_id,
        bundle_id=bundle.input_resolution_id,
    )
    if expected.to_dict() != bundle.to_dict():
        raise DispatchBindingError(
            "input-resolution bundle does not independently reconstruct"
        )
    return store.load_work_order(bundle.work_order_id)


def create_dispatch_binding(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    binder_registry: DispatchInputBinderRegistry,
    bundle: InputResolutionBundle,
) -> DispatchBinding:
    if not isinstance(binder_registry, DispatchInputBinderRegistry):
        raise TypeError("binder_registry must be a DispatchInputBinderRegistry")
    work_order = _require_bundle_revalidates(store, resolver_registry, bundle)
    binder = binder_registry.binder_for(bundle)
    projection = binder.bind(work_order, bundle)
    return DispatchBinding.create(
        bundle,
        binder.descriptor,
        request_projection=projection,
    )


def _binding_with_id(
    bundle: InputResolutionBundle,
    binder: DispatchInputBinder,
    projection: object,
    binding_id: str,
) -> DispatchBinding:
    descriptor = binder.descriptor
    return DispatchBinding(
        dispatch_binding_id=binding_id,
        work_order_id=bundle.work_order_id,
        work_order_hash=bundle.work_order_hash,
        work_order_audit_id=bundle.work_order_audit_id,
        work_order_audit_hash=bundle.work_order_audit_hash,
        input_resolution_id=bundle.input_resolution_id,
        input_resolution_hash=bundle.content_hash,
        task_id=bundle.task_id,
        task_revision=bundle.task_revision,
        task_content_hash=bundle.task_content_hash,
        route_decision_id=bundle.route_decision_id,
        route_decision_hash=bundle.route_decision_hash,
        selected_adapter_id=bundle.selected_adapter_id,
        selected_adapter_fingerprint=bundle.selected_adapter_fingerprint,
        dispatch_catalog_id=bundle.dispatch_catalog_id,
        dispatch_catalog_hash=bundle.dispatch_catalog_hash,
        dispatch_contract_id=bundle.dispatch_contract_id,
        dispatch_contract_hash=bundle.dispatch_contract_hash,
        binder_id=descriptor.binder_id,
        binder_fingerprint=descriptor.binder_fingerprint,
        request_type_id=descriptor.request_type_id,
        request_schema_hash=descriptor.request_schema_hash,
        request_projection_json=canonical_bytes(projection).decode("utf-8"),
    )


def _evaluate_binding_audit(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    binder_registry: DispatchInputBinderRegistry,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
    *,
    audit_id: str,
) -> DispatchBindingAudit:
    failure: str | None = None
    request_hash: str | None = None
    try:
        work_order = _require_bundle_revalidates(store, resolver_registry, bundle)
        binder = binder_registry.binder_for(bundle)
        projection = binder.bind(work_order, bundle)
        expected = _binding_with_id(
            bundle,
            binder,
            projection,
            binding.dispatch_binding_id,
        )
        if expected.to_dict() != binding.to_dict():
            raise DispatchBindingError(
                "dispatch binding does not independently reconstruct"
            )
        request_hash = binding.request_content_hash
    except (
        DispatchBindingError,
        DispatchBindingModelError,
        DispatchInputResolutionError,
        ProductionWorkOrderStoreError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        failure = f"{type(exc).__name__}: {exc}"

    return DispatchBindingAudit(
        binding_audit_id=audit_id,
        dispatch_binding_id=binding.dispatch_binding_id,
        dispatch_binding_hash=binding.content_hash,
        input_resolution_id=bundle.input_resolution_id,
        input_resolution_hash=bundle.content_hash,
        work_order_id=binding.work_order_id,
        work_order_hash=binding.work_order_hash,
        work_order_audit_id=binding.work_order_audit_id,
        work_order_audit_hash=binding.work_order_audit_hash,
        resolver_registry_fingerprint=bundle.resolver_registry_fingerprint,
        binder_id=binding.binder_id,
        binder_fingerprint=binding.binder_fingerprint,
        request_type_id=binding.request_type_id,
        request_schema_hash=binding.request_schema_hash,
        request_content_hash=request_hash,
        status=BindingAuditStatus.PASS if failure is None else BindingAuditStatus.FAIL,
        failure_reason=failure,
    )


def audit_dispatch_binding_frozen(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    binder_registry: DispatchInputBinderRegistry,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
) -> DispatchBindingAudit:
    if not isinstance(binding, DispatchBinding):
        raise TypeError("binding must be a DispatchBinding")
    return _evaluate_binding_audit(
        store,
        resolver_registry,
        binder_registry,
        bundle,
        binding,
        audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
    )


def _frozen_binding_audit_matches(
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
    audit: DispatchBindingAudit,
) -> bool:
    """Revalidate only frozen relations; live source/binder state is separate."""

    if (
        not isinstance(bundle, InputResolutionBundle)
        or not isinstance(binding, DispatchBinding)
        or not isinstance(audit, DispatchBindingAudit)
        or audit.status is not BindingAuditStatus.PASS
    ):
        return False
    try:
        expected = DispatchBindingAudit(
            binding_audit_id=audit.binding_audit_id,
            dispatch_binding_id=binding.dispatch_binding_id,
            dispatch_binding_hash=binding.content_hash,
            input_resolution_id=bundle.input_resolution_id,
            input_resolution_hash=bundle.content_hash,
            work_order_id=binding.work_order_id,
            work_order_hash=binding.work_order_hash,
            work_order_audit_id=binding.work_order_audit_id,
            work_order_audit_hash=binding.work_order_audit_hash,
            resolver_registry_fingerprint=bundle.resolver_registry_fingerprint,
            binder_id=binding.binder_id,
            binder_fingerprint=binding.binder_fingerprint,
            request_type_id=binding.request_type_id,
            request_schema_hash=binding.request_schema_hash,
            request_content_hash=binding.request_content_hash,
            status=BindingAuditStatus.PASS,
            failure_reason=None,
        )
    except (DispatchBindingModelError, TypeError, ValueError):
        return False
    return expected.to_dict() == audit.to_dict()


def inspect_dispatch_binding_currentness(
    store: ProductionWorkOrderStore,
    resolver_registry: WorkOrderInputResolverRegistry,
    binder_registry: DispatchInputBinderRegistry,
    bundle: InputResolutionBundle,
    binding: DispatchBinding,
    audit: DispatchBindingAudit,
) -> DispatchBindingCurrentness:
    if not isinstance(binding, DispatchBinding):
        raise TypeError("binding must be a DispatchBinding")
    if not isinstance(audit, DispatchBindingAudit):
        raise TypeError("audit must be a DispatchBindingAudit")

    def result(
        status: DispatchBindingCurrentnessStatus,
        detail: str | None,
    ) -> DispatchBindingCurrentness:
        return DispatchBindingCurrentness(
            binding.dispatch_binding_id,
            audit.binding_audit_id,
            binding.work_order_id,
            binding.task_id,
            status,
            detail,
        )

    if not _frozen_binding_audit_matches(bundle, binding, audit):
        return result(
            DispatchBindingCurrentnessStatus.INVALID_AUDIT,
            "binding audit does not match the exact frozen binding/bundle relation",
        )
    if bundle.resolver_registry_fingerprint != resolver_registry.fingerprint:
        return result(
            DispatchBindingCurrentnessStatus.RESOLVER_DRIFT,
            "resolver registry fingerprint no longer matches frozen input resolution",
        )

    try:
        binder = binder_registry.binder_for(bundle)
    except (DispatchBindingError, TypeError, ValueError) as exc:
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            f"{type(exc).__name__}: {exc}",
        )
    if (
        binding.binder_id != binder.descriptor.binder_id
        or binding.binder_fingerprint != binder.descriptor.binder_fingerprint
        or binding.request_type_id != binder.descriptor.request_type_id
        or binding.request_schema_hash != binder.descriptor.request_schema_hash
    ):
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            "binding binder identity/schema no longer matches trusted registry",
        )

    try:
        work_order = store.load_work_order(bundle.work_order_id)
        work_order_audit = store.load_audit(bundle.work_order_audit_id)
        catalog = store.load_dispatch_catalog(work_order.dispatch_catalog_id)
    except (ProductionWorkOrderStoreError, KeyError, TypeError, ValueError) as exc:
        return result(
            DispatchBindingCurrentnessStatus.STALE_WORK_ORDER,
            f"{type(exc).__name__}: {exc}",
        )
    work_order_currentness = inspect_work_order_currentness(
        store.runtime,
        store.capability_store,
        catalog,
        store.validator_registry,
        work_order,
        work_order_audit,
    )
    if work_order_currentness.status is not WorkOrderCurrentnessStatus.CURRENT_READY:
        if work_order_currentness.status in {
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
            WorkOrderCurrentnessStatus.INVALID_AUDIT,
        }:
            status = DispatchBindingCurrentnessStatus.STALE_WORK_ORDER
        else:
            status = DispatchBindingCurrentnessStatus.NOT_READY
        return result(
            status,
            f"WorkOrder currentness is {work_order_currentness.status.value}",
        )

    try:
        expected_bundle = _reconstruct_bundle(
            store,
            resolver_registry,
            bundle.work_order_id,
            bundle.work_order_audit_id,
            bundle_id=bundle.input_resolution_id,
        )
    except DispatchInputResolutionError as exc:
        return result(
            DispatchBindingCurrentnessStatus.STALE_INPUT,
            f"{type(exc).__name__}: {exc}",
        )
    except (DispatchBindingError, ProductionWorkOrderStoreError, TypeError, ValueError) as exc:
        return result(
            DispatchBindingCurrentnessStatus.STALE_WORK_ORDER,
            f"{type(exc).__name__}: {exc}",
        )
    if expected_bundle.to_dict() != bundle.to_dict():
        return result(
            DispatchBindingCurrentnessStatus.STALE_INPUT,
            "current resolved input bundle differs from frozen resolution",
        )

    try:
        expected_binding = _binding_with_id(
            expected_bundle,
            binder,
            binder.bind(work_order, expected_bundle),
            binding.dispatch_binding_id,
        )
    except (DispatchBindingError, DispatchBindingModelError, TypeError, ValueError) as exc:
        return result(
            DispatchBindingCurrentnessStatus.BINDER_DRIFT,
            f"{type(exc).__name__}: {exc}",
        )
    if expected_binding.to_dict() != binding.to_dict():
        return result(
            DispatchBindingCurrentnessStatus.INVALID_AUDIT,
            "binding request does not independently reconstruct from current trusted binder",
        )
    return result(DispatchBindingCurrentnessStatus.CURRENT_READY, None)
