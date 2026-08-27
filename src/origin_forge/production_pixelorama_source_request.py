from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, validate_id
from .pixelorama_models import (
    BridgeBudget,
    BridgeOperation,
    ExportSpec,
    PixeloramaBridgeRequest,
    SpriteProjectSpec,
)
from .pixelorama_protocol import (
    PixeloramaProtocolError,
    parse_bridge_budget,
    parse_export_spec,
    parse_sprite_spec,
)
from .production_work_order_models import canonical_bytes, content_hash


class PixeloramaSourceRequestError(ValueError):
    pass


@dataclass(frozen=True)
class PixeloramaSourceInvocationRequest:
    """Immutable source/animation request reconstructed from a WorkOrder."""

    task_id: str
    accepted_design_id: str
    accepted_design_hash: str
    design_input_id: str
    planning_input_id: str
    sprite_spec: SpriteProjectSpec
    export_specs: tuple[ExportSpec, ...]
    budget: BridgeBudget

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise PixeloramaSourceRequestError("task_id must be a TASK ID")
        if not validate_id(
            self.accepted_design_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE
        ):
            raise PixeloramaSourceRequestError("accepted_design_id must be a DESIGNACC ID")
        if not isinstance(self.accepted_design_hash, str) or not self.accepted_design_hash.startswith("sha256:"):
            raise PixeloramaSourceRequestError("accepted_design_hash must use sha256: format")
        if not isinstance(self.design_input_id, str) or not self.design_input_id:
            raise PixeloramaSourceRequestError("design_input_id must be non-empty")
        if not isinstance(self.planning_input_id, str) or not self.planning_input_id:
            raise PixeloramaSourceRequestError("planning_input_id must be non-empty")
        if not isinstance(self.sprite_spec, SpriteProjectSpec):
            raise PixeloramaSourceRequestError("sprite_spec must be a SpriteProjectSpec")
        exports = tuple(self.export_specs)
        if any(not isinstance(value, ExportSpec) for value in exports):
            raise PixeloramaSourceRequestError("export_specs must contain ExportSpec values")
        object.__setattr__(self, "export_specs", tuple(sorted(exports, key=lambda value: value.relative_path)))
        if not isinstance(self.budget, BridgeBudget):
            raise PixeloramaSourceRequestError("budget must be a BridgeBudget")

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "accepted_design_id": self.accepted_design_id,
            "accepted_design_hash": self.accepted_design_hash,
            "design_input_id": self.design_input_id,
            "planning_input_id": self.planning_input_id,
            "sprite_spec": self.sprite_spec.to_dict(),
            "export_specs": [value.to_dict() for value in self.export_specs],
            "budget": self.budget.to_dict(),
        }

    def to_bridge_request(self) -> PixeloramaBridgeRequest:
        return PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=self.sprite_spec,
            export_specs=self.export_specs,
            budget=self.budget,
        )


def decode_pixelorama_source_request(
    task_id: str,
    payload: object,
    accepted_design_projection: object,
) -> PixeloramaSourceInvocationRequest:
    """Decode exact source payload plus the resolver-owned design projection."""
    if not isinstance(payload, dict) or set(payload) != {
        "operation", "sprite_spec", "export_specs", "budget"
    }:
        raise PixeloramaSourceRequestError("Pixelorama source payload fields are not exact")
    if payload["operation"] != BridgeOperation.CREATE_SPRITE_PROJECT.value:
        raise PixeloramaSourceRequestError("Pixelorama source operation is not CREATE_SPRITE_PROJECT")
    if not isinstance(payload["export_specs"], list):
        raise PixeloramaSourceRequestError("Pixelorama source export_specs must be an array")
    try:
        request = PixeloramaSourceInvocationRequest(
            task_id=task_id,
            accepted_design_id=accepted_design_projection["acceptance_id"],
            accepted_design_hash=accepted_design_projection["acceptance_hash"],
            design_input_id=accepted_design_projection["design_input_id"],
            planning_input_id=accepted_design_projection["planning_input_id"],
            sprite_spec=parse_sprite_spec(payload["sprite_spec"]),
            export_specs=tuple(parse_export_spec(value) for value in payload["export_specs"]),
            budget=parse_bridge_budget(payload["budget"]),
        )
    except (KeyError, TypeError, PixeloramaProtocolError) as exc:
        raise PixeloramaSourceRequestError("Pixelorama source request projection is invalid") from exc
    canonical_bytes(payload)
    return request
