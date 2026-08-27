from __future__ import annotations

import json
from pathlib import Path

from .ids import IdKind, validate_id
from .specialist_evidence import (
    SpecialistEvidenceError,
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
)
from .specialist_models import (
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistModelError,
)
from .specialist_store import SpecialistStore


class SpecialistEvidenceStoreError(RuntimeError):
    pass


class SpecialistEvidenceStore:
    FORMAT_VERSION = 1

    def __init__(
        self,
        store: SpecialistStore,
        *,
        max_packages: int = 4096,
        max_package_bytes: int = 2 * 1024 * 1024,
    ):
        if not isinstance(store, SpecialistStore):
            raise TypeError("store must be a SpecialistStore")
        if not isinstance(max_packages, int) or isinstance(max_packages, bool) or max_packages <= 0:
            raise ValueError("max_packages must be a positive integer")
        if (
            not isinstance(max_package_bytes, int)
            or isinstance(max_package_bytes, bool)
            or max_package_bytes <= 0
        ):
            raise ValueError("max_package_bytes must be a positive integer")
        self.store = store
        self.runtime = store.runtime
        self.directory = store.root / "evidence"
        self.max_packages = max_packages
        self.max_package_bytes = max_package_bytes

    @staticmethod
    def _canonical_bytes(package: SpecialistEvidencePackage) -> bytes:
        return (
            json.dumps(
                {
                    "format_version": SpecialistEvidenceStore.FORMAT_VERSION,
                    "kind": "SPECIALIST_EVIDENCE_PACKAGE",
                    "payload": package.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def ensure(self) -> None:
        self.store.ensure()
        self.store._validate_dir(self.directory, create=True)

    def list_contract_ids(self) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for path in self.directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise SpecialistEvidenceStoreError(
                    f"specialist evidence registry contains unsupported entry: {path.name}"
                )
            contract_id = path.stem
            if not validate_id(contract_id, IdKind.SPECIALIST_CONTRACT):
                raise SpecialistEvidenceStoreError(
                    f"specialist evidence registry contains invalid contract ID: {contract_id}"
                )
            values.append(contract_id)
            if len(values) > self.max_packages:
                raise SpecialistEvidenceStoreError(
                    f"specialist evidence catalog exceeds limit ({len(values)} > {self.max_packages})"
                )
        return tuple(sorted(values))

    def put(self, package: SpecialistEvidencePackage) -> Path:
        if not isinstance(package, SpecialistEvidencePackage):
            raise TypeError("package must be a SpecialistEvidencePackage")
        self.ensure()
        stored_contract = self.store.load_contract(package.contract.contract_id)
        if stored_contract != package.contract:
            raise SpecialistEvidenceStoreError(
                "frozen specialist evidence package does not match stored contract"
            )
        data = self._canonical_bytes(package)
        if len(data) > self.max_package_bytes:
            raise SpecialistEvidenceStoreError(
                "specialist evidence package exceeds store byte limit "
                f"({len(data)} > {self.max_package_bytes})"
            )
        path = self.directory / f"{package.contract.contract_id}.json"
        if path.exists() or path.is_symlink():
            current = self.store._bounded_read(
                path,
                self.max_package_bytes,
                "specialist evidence package",
            )
            if current != data:
                raise SpecialistEvidenceStoreError(
                    "specialist evidence package contract ID is immutable and already exists"
                )
            return path
        if len(self.list_contract_ids()) >= self.max_packages:
            raise SpecialistEvidenceStoreError(
                f"specialist evidence catalog exceeds limit ({self.max_packages + 1} > {self.max_packages})"
            )
        if not self.store._atomic_publish(path, data):
            current = self.store._bounded_read(
                path,
                self.max_package_bytes,
                "specialist evidence package",
            )
            if current != data:
                raise SpecialistEvidenceStoreError(
                    "specialist evidence package contract ID is immutable and already exists"
                )
        return path

    def load(self, contract_id: str) -> SpecialistEvidencePackage:
        self.ensure()
        if not validate_id(contract_id, IdKind.SPECIALIST_CONTRACT):
            raise SpecialistEvidenceStoreError("invalid specialist evidence contract ID")
        path = self.directory / f"{contract_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(contract_id)
        data = self.store._bounded_read(
            path,
            self.max_package_bytes,
            "specialist evidence package",
        )
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistEvidenceStoreError("invalid specialist evidence package JSON") from exc
        if (
            not isinstance(raw, dict)
            or set(raw) != {"format_version", "kind", "payload"}
            or raw["format_version"] != self.FORMAT_VERSION
            or raw["kind"] != "SPECIALIST_EVIDENCE_PACKAGE"
        ):
            raise SpecialistEvidenceStoreError("invalid specialist evidence package envelope")
        payload = raw["payload"]
        if not isinstance(payload, dict) or set(payload) != {"contract", "records", "content_hash"}:
            raise SpecialistEvidenceStoreError("invalid specialist evidence package fields")
        contract = self.store.load_contract(contract_id)
        if payload["contract"] != contract.to_dict():
            raise SpecialistEvidenceStoreError(
                "specialist evidence package embedded contract does not match trusted contract"
            )
        records_raw = payload["records"]
        if not isinstance(records_raw, list):
            raise SpecialistEvidenceStoreError("specialist evidence records must be an array")
        records: list[SpecialistEvidenceRecord] = []
        try:
            for raw_record in records_raw:
                if not isinstance(raw_record, dict) or set(raw_record) != {"ref", "payload"}:
                    raise SpecialistEvidenceStoreError("invalid specialist evidence record fields")
                raw_ref = raw_record["ref"]
                if not isinstance(raw_ref, dict) or set(raw_ref) != {
                    "ref_id",
                    "content_hash",
                    "evidence_kind",
                }:
                    raise SpecialistEvidenceStoreError("invalid specialist evidence ref fields")
                ref = SpecialistEvidenceRef(
                    ref_id=raw_ref["ref_id"],
                    content_hash=raw_ref["content_hash"],
                    evidence_kind=SpecialistEvidenceKind(raw_ref["evidence_kind"]),
                )
                records.append(SpecialistEvidenceRecord(ref, raw_record["payload"]))
            package = SpecialistEvidencePackage(contract, tuple(records))
        except (SpecialistModelError, SpecialistEvidenceError, ValueError, TypeError) as exc:
            raise SpecialistEvidenceStoreError(
                "specialist evidence package validation failed"
            ) from exc
        if payload["content_hash"] != package.content_hash:
            raise SpecialistEvidenceStoreError("specialist evidence package content hash mismatch")
        return package
