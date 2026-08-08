from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .runtime import OriginForgeRuntime
from .skill_evaluation import SkillBenchmarkReport, SkillEvalCase
from .skills import SkillRegistry


_REPORT_ID_RE = re.compile(r"^SKILL-EVAL-[0-9a-f]{20}$")


class SkillEvalStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSkillBenchmark:
    report_id: str
    content_hash: str
    suite_hash: str
    path: Path


@dataclass(frozen=True)
class LoadedSkillBenchmark:
    report_id: str
    content_hash: str
    suite_hash: str
    envelope: dict[str, object]


class SkillEvalStore:
    """Protected immutable eval cases and bounded content-addressed reports."""

    FORMAT_VERSION = 1

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_cases: int = 256,
        max_reports: int = 1024,
        max_case_bytes: int = 64 * 1024,
        max_report_bytes: int = 4 * 1024 * 1024,
    ):
        if max_cases <= 0 or max_reports <= 0:
            raise ValueError("Skill eval store count limits must be positive")
        if max_case_bytes <= 0 or max_report_bytes <= 0:
            raise ValueError("Skill eval store byte limits must be positive")
        self.runtime = runtime
        self.root = runtime.state_dir / "skill-evals"
        self.cases_dir = self.root / "cases"
        self.reports_dir = self.root / "reports"
        self.max_cases = max_cases
        self.max_reports = max_reports
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
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise SkillEvalStoreError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise SkillEvalStoreError(
                f"{label} exceeds byte limit ({len(data)} > {maximum})"
            )
        return data

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
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

    def put_case(self, case: SkillEvalCase) -> Path:
        self.ensure()
        path = self.cases_dir / f"{case.case_id}.json"
        data = self._canonical_bytes(self._case_payload(case))
        if len(data) > self.max_case_bytes:
            raise SkillEvalStoreError(
                f"Skill eval case exceeds byte limit ({len(data)} > {self.max_case_bytes})"
            )
        if path.exists() or path.is_symlink():
            current = self._bounded_read(path, self.max_case_bytes, "Skill eval case")
            if current != data:
                raise SkillEvalStoreError(
                    f"Skill eval case ID is immutable and already exists: {case.case_id}"
                )
            return path
        if len(self.list_case_ids()) >= self.max_cases:
            raise SkillEvalStoreError(
                f"Skill eval case catalog exceeds limit ({self.max_cases + 1} > {self.max_cases})"
            )
        self._atomic_write(path, data)
        return path

    def load_case(self, case_id: str) -> SkillEvalCase:
        try:
            SkillEvalCase(
                case_id=case_id,
                fixture_ref="validate-fixture",
                scorer_ref="validate-scorer",
                objective="validate-id",
            )
        except ValueError as exc:
            raise SkillEvalStoreError(f"invalid Skill eval case ID: {case_id!r}") from exc
        self.ensure()
        path = self.cases_dir / f"{case_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(case_id)
        data = self._bounded_read(path, self.max_case_bytes, "Skill eval case")
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
            "fixture_ref",
            "scorer_ref",
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

        scalar_fields = ("case_id", "fixture_ref", "scorer_ref", "objective")
        if any(not isinstance(value[field], str) for field in scalar_fields):
            raise SkillEvalStoreError(f"Skill eval case scalar fields are invalid: {case_id}")
        try:
            case = SkillEvalCase(
                case_id=value["case_id"],
                fixture_ref=value["fixture_ref"],
                scorer_ref=value["scorer_ref"],
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

    @classmethod
    def suite_hash_for_report(cls, report: SkillBenchmarkReport) -> str:
        pairs = sorted(
            (comparison.case_id, comparison.case_hash)
            for comparison in report.comparisons
        )
        return cls._sha256(cls._canonical_bytes(pairs))

    def _assert_report_inputs_current(self, report: SkillBenchmarkReport) -> None:
        seen_cases: set[str] = set()
        for comparison in report.comparisons:
            if comparison.case_id in seen_cases:
                raise SkillEvalStoreError(
                    f"Skill benchmark report contains duplicate case ID: {comparison.case_id}"
                )
            seen_cases.add(comparison.case_id)
            try:
                current = self.load_case(comparison.case_id)
            except KeyError as exc:
                raise SkillEvalStoreError(
                    f"Skill benchmark case is not durably stored: {comparison.case_id}"
                ) from exc
            if current.content_hash != comparison.case_hash:
                raise SkillEvalStoreError(
                    f"Skill benchmark case changed before report save: {comparison.case_id}"
                )

        registry = SkillRegistry(self.runtime)
        for ref in report.skill_refs:
            if "@" not in ref:
                raise SkillEvalStoreError(f"invalid Skill ref in benchmark report: {ref}")
            name = ref.split("@", 1)[0]
            try:
                current = registry.load(name)
            except Exception as exc:
                raise SkillEvalStoreError(
                    f"Skill benchmark Skill is unavailable before report save: {name}"
                ) from exc
            if current.ref != ref:
                raise SkillEvalStoreError(
                    f"Skill benchmark Skill changed before report save: {ref}"
                )

    def list_report_ids(self) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for item in sorted(self.reports_dir.iterdir(), key=lambda path: path.name):
            if item.is_symlink() or not item.is_file() or item.suffix != ".json":
                raise SkillEvalStoreError(
                    f"Skill eval report registry contains unsupported entry: {item.name}"
                )
            if not _REPORT_ID_RE.fullmatch(item.stem):
                raise SkillEvalStoreError(f"invalid Skill eval report filename: {item.name}")
            values.append(item.stem)
            if len(values) > self.max_reports:
                raise SkillEvalStoreError(
                    f"Skill eval report catalog exceeds limit ({len(values)} > {self.max_reports})"
                )
        return tuple(values)

    def save_report(self, report: SkillBenchmarkReport) -> StoredSkillBenchmark:
        self.ensure()
        self._assert_report_inputs_current(report)
        suite_hash = self.suite_hash_for_report(report)
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
        if path.exists() or path.is_symlink():
            current = self._bounded_read(path, self.max_report_bytes, "Skill benchmark report")
            if current != data:
                raise SkillEvalStoreError(
                    f"Skill benchmark report ID collision: {report_id}"
                )
        else:
            if len(self.list_report_ids()) >= self.max_reports:
                raise SkillEvalStoreError(
                    f"Skill eval report catalog exceeds limit ({self.max_reports + 1} > {self.max_reports})"
                )
            self._atomic_write(path, data)
        return StoredSkillBenchmark(report_id, content_hash, suite_hash, path)

    def load_report(self, report_id: str) -> LoadedSkillBenchmark:
        if not _REPORT_ID_RE.fullmatch(report_id):
            raise SkillEvalStoreError(f"invalid Skill benchmark report ID: {report_id!r}")
        self.ensure()
        path = self.reports_dir / f"{report_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(report_id)
        data = self._bounded_read(path, self.max_report_bytes, "Skill benchmark report")
        content_hash = self._sha256(data)
        expected_id = f"SKILL-EVAL-{content_hash.removeprefix('sha256:')[:20]}"
        if expected_id != report_id:
            raise SkillEvalStoreError(
                f"Skill benchmark report content/ID mismatch: {report_id} != {expected_id}"
            )
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillEvalStoreError(f"invalid Skill benchmark report JSON: {report_id}") from exc
        if not isinstance(raw, dict) or set(raw) != {"format_version", "suite_hash", "report"}:
            raise SkillEvalStoreError(f"invalid Skill benchmark report envelope: {report_id}")
        if raw["format_version"] != self.FORMAT_VERSION:
            raise SkillEvalStoreError(
                f"unsupported Skill benchmark report format: {raw['format_version']}"
            )
        if not isinstance(raw["suite_hash"], str) or not isinstance(raw["report"], dict):
            raise SkillEvalStoreError(f"invalid Skill benchmark report fields: {report_id}")
        return LoadedSkillBenchmark(
            report_id=report_id,
            content_hash=content_hash,
            suite_hash=raw["suite_hash"],
            envelope=raw,
        )
