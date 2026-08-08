from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .runtime import OriginForgeRuntime
from .skill_evaluation import SkillBenchmarkReport, SkillEvalCase


class SkillEvalStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSkillBenchmark:
    report_id: str
    content_hash: str
    suite_hash: str
    path: Path


class SkillEvalStore:
    """Protected immutable eval cases and content-addressed benchmark reports."""

    FORMAT_VERSION = 1

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_cases: int = 256,
        max_case_bytes: int = 64 * 1024,
        max_report_bytes: int = 4 * 1024 * 1024,
    ):
        if max_cases <= 0:
            raise ValueError("max_cases must be positive")
        if max_case_bytes <= 0 or max_report_bytes <= 0:
            raise ValueError("Skill eval store byte limits must be positive")
        self.runtime = runtime
        self.root = runtime.state_dir / "skill-evals"
        self.cases_dir = self.root / "cases"
        self.reports_dir = self.root / "reports"
        self.max_cases = max_cases
        self.max_case_bytes = max_case_bytes
        self.max_report_bytes = max_report_bytes

    @staticmethod
    def _canonical_bytes(value: object) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _sha256(data: bytes) -> str:
        return f"sha256:{hashlib.sha256(data).hexdigest()}"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".origin-forge-tmp")
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    def _validate_dir(self, path: Path, *, create: bool = False) -> Path:
        state = self.runtime.state_dir.resolve()
        if path.is_symlink():
            raise SkillEvalStoreError(f"Skill eval path may not be a symlink: {path.name}")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as exc:
            raise SkillEvalStoreError(f"cannot resolve Skill eval path: {path}") from exc
        try:
            resolved.relative_to(state)
        except ValueError as exc:
            raise SkillEvalStoreError("Skill eval store escapes .origin-forge") from exc
        if path.exists() and not path.is_dir():
            raise SkillEvalStoreError(f"Skill eval path must be a directory: {path}")
        return resolved

    def ensure(self) -> None:
        self._validate_dir(self.root, create=True)
        self._validate_dir(self.cases_dir, create=True)
        self._validate_dir(self.reports_dir, create=True)

    @staticmethod
    def _case_payload(case: SkillEvalCase) -> dict[str, object]:
        return {
            "format_version": SkillEvalStore.FORMAT_VERSION,
            "case": case.canonical_dict(),
            "case_hash": case.content_hash,
        }

    def put_case(self, case: SkillEvalCase) -> Path:
        """Persist one immutable operator-owned case.

        Rewriting the same ID with byte-identical content is idempotent. A
        changed case under the same ID fails closed; callers must create a new
        case ID so historical benchmark meaning cannot drift.
        """

        self.ensure()
        existing = self.list_case_ids()
        path = self.cases_dir / f"{case.case_id}.json"
        data = self._canonical_bytes(self._case_payload(case))
        if len(data) > self.max_case_bytes:
            raise SkillEvalStoreError(
                f"Skill eval case exceeds byte limit ({len(data)} > {self.max_case_bytes})"
            )
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise SkillEvalStoreError(f"invalid Skill eval case path: {case.case_id}")
            current = path.read_bytes()
            if current != data:
                raise SkillEvalStoreError(
                    f"Skill eval case ID is immutable and already exists: {case.case_id}"
                )
            return path
        if len(existing) >= self.max_cases:
            raise SkillEvalStoreError(
                f"Skill eval case catalog exceeds limit ({len(existing) + 1} > {self.max_cases})"
            )
        self._atomic_write(path, data)
        return path

    def list_case_ids(self) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for item in sorted(self.cases_dir.iterdir(), key=lambda path: path.name):
            if item.is_symlink() or not item.is_file() or item.suffix != ".json":
                raise SkillEvalStoreError(
                    f"Skill eval case registry contains unsupported entry: {item.name}"
                )
            values.append(item.stem)
            if len(values) > self.max_cases:
                raise SkillEvalStoreError(
                    f"Skill eval case catalog exceeds limit ({len(values)} > {self.max_cases})"
                )
        return tuple(values)

    def load_case(self, case_id: str) -> SkillEvalCase:
        # Constructing a minimal case validates the same bounded ID syntax used
        # by SkillEvalCase without duplicating its regular expression here.
        try:
            SkillEvalCase(case_id=case_id, objective="validate-id")
        except ValueError as exc:
            raise SkillEvalStoreError(f"invalid Skill eval case ID: {case_id!r}") from exc
        self.ensure()
        path = self.cases_dir / f"{case_id}.json"
        if path.is_symlink() or not path.is_file():
            raise KeyError(case_id)
        with path.open("rb") as handle:
            data = handle.read(self.max_case_bytes + 1)
        if len(data) > self.max_case_bytes:
            raise SkillEvalStoreError(
                f"Skill eval case exceeds byte limit ({len(data)} > {self.max_case_bytes})"
            )
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillEvalStoreError(f"invalid Skill eval case JSON: {case_id}") from exc
        if not isinstance(raw, dict) or set(raw) != {"format_version", "case", "case_hash"}:
            raise SkillEvalStoreError(f"invalid Skill eval case envelope: {case_id}")
        if raw["format_version"] != self.FORMAT_VERSION:
            raise SkillEvalStoreError(
                f"unsupported Skill eval case format: {raw['format_version']}"
            )
        value = raw["case"]
        if not isinstance(value, dict):
            raise SkillEvalStoreError(f"Skill eval case payload must be an object: {case_id}")
        allowed = {
            "case_id",
            "objective",
            "acceptance_criteria",
            "constraints",
            "required_capabilities",
            "context_paths",
            "tags",
        }
        if set(value) != allowed:
            raise SkillEvalStoreError(f"Skill eval case fields are invalid: {case_id}")

        def strings(field: str) -> tuple[str, ...]:
            item = value[field]
            if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
                raise SkillEvalStoreError(f"Skill eval case {field} is invalid: {case_id}")
            return tuple(item)

        if not isinstance(value["case_id"], str) or not isinstance(value["objective"], str):
            raise SkillEvalStoreError(f"Skill eval case scalar fields are invalid: {case_id}")
        try:
            case = SkillEvalCase(
                case_id=value["case_id"],
                objective=value["objective"],
                acceptance_criteria=strings("acceptance_criteria"),
                constraints=strings("constraints"),
                required_capabilities=strings("required_capabilities"),
                context_paths=strings("context_paths"),
                tags=strings("tags"),
            )
        except ValueError as exc:
            raise SkillEvalStoreError(f"Skill eval case validation failed: {case_id}") from exc
        if case.case_id != case_id:
            raise SkillEvalStoreError(
                f"Skill eval case filename/ID mismatch: {case_id} != {case.case_id}"
            )
        if raw["case_hash"] != case.content_hash:
            raise SkillEvalStoreError(f"Skill eval case hash mismatch: {case_id}")
        return case

    def load_cases(self, case_ids: Iterable[str]) -> tuple[SkillEvalCase, ...]:
        ids = tuple(dict.fromkeys(case_ids))
        if not ids:
            raise SkillEvalStoreError("at least one Skill eval case ID is required")
        if len(ids) > self.max_cases:
            raise SkillEvalStoreError(
                f"Skill eval case request exceeds limit ({len(ids)} > {self.max_cases})"
            )
        return tuple(self.load_case(case_id) for case_id in ids)

    @staticmethod
    def _suite_hash(report: SkillBenchmarkReport) -> str:
        pairs = sorted(
            (comparison.case_id, comparison.case_hash)
            for comparison in report.comparisons
        )
        data = SkillEvalStore._canonical_bytes(pairs)
        return SkillEvalStore._sha256(data)

    def save_report(self, report: SkillBenchmarkReport) -> StoredSkillBenchmark:
        self.ensure()
        suite_hash = self._suite_hash(report)
        envelope = {
            "format_version": self.FORMAT_VERSION,
            "suite_hash": suite_hash,
            "report": report.to_dict(),
        }
        data = self._canonical_bytes(envelope)
        if len(data) > self.max_report_bytes:
            raise SkillEvalStoreError(
                f"Skill benchmark report exceeds byte limit ({len(data)} > {self.max_report_bytes})"
            )
        content_hash = self._sha256(data)
        report_id = f"SKILL-EVAL-{content_hash.removeprefix('sha256:')[:20]}"
        path = self.reports_dir / f"{report_id}.json"
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise SkillEvalStoreError(
                    f"Skill benchmark report ID collision: {report_id}"
                )
        else:
            self._atomic_write(path, data)
        return StoredSkillBenchmark(report_id, content_hash, suite_hash, path)
