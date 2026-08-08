from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .specialist_models import (
    SpecialistContract,
    SpecialistEvidenceRef,
    SpecialistModelError,
)


class SpecialistEvidenceError(RuntimeError):
    pass


def canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpecialistEvidenceError("specialist evidence must be finite JSON data") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SpecialistEvidenceRecord:
    ref: SpecialistEvidenceRef
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.ref, SpecialistEvidenceRef):
            raise TypeError("ref must be a SpecialistEvidenceRef")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dict")
        if self.payload.get("id") != self.ref.ref_id:
            raise SpecialistEvidenceError("specialist evidence payload ID does not match ref")
        if canonical_hash(self.payload) != self.ref.content_hash:
            raise SpecialistEvidenceError("specialist evidence payload hash does not match ref")

    @property
    def byte_count(self) -> int:
        return len(
            json.dumps(
                self.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )

    def to_dict(self) -> dict[str, object]:
        return {"ref": self.ref.to_dict(), "payload": self.payload}


@dataclass(frozen=True)
class SpecialistEvidencePackage:
    contract: SpecialistContract
    records: tuple[SpecialistEvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contract, SpecialistContract):
            raise TypeError("contract must be a SpecialistContract")
        records = tuple(self.records)
        if any(not isinstance(item, SpecialistEvidenceRecord) for item in records):
            raise TypeError("records must contain SpecialistEvidenceRecord values")
        expected = {
            (item.evidence_kind.value, item.ref_id, item.content_hash)
            for item in self.contract.evidence_refs
        }
        actual = {
            (item.ref.evidence_kind.value, item.ref.ref_id, item.ref.content_hash)
            for item in records
        }
        if len(records) != len(actual):
            raise SpecialistEvidenceError("specialist evidence package contains duplicate records")
        if actual != expected:
            raise SpecialistEvidenceError(
                "specialist evidence package must exactly match contract evidence refs"
            )
        total = sum(item.byte_count for item in records)
        if total > self.contract.budget.max_evidence_bytes:
            raise SpecialistEvidenceError(
                "specialist evidence package exceeds frozen byte budget "
                f"({total} > {self.contract.budget.max_evidence_bytes})"
            )
        object.__setattr__(
            self,
            "records",
            tuple(
                sorted(
                    records,
                    key=lambda item: (item.ref.evidence_kind.value, item.ref.ref_id),
                )
            ),
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "contract_id": self.contract.contract_id,
                "contract_hash": self.contract.content_hash,
                "records": [item.to_dict() for item in self.records],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract.to_dict(),
            "records": [item.to_dict() for item in self.records],
            "content_hash": self.content_hash,
        }
