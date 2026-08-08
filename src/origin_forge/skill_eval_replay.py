from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .runtime import OriginForgeRuntime
from .skill_eval_store import SkillEvalStore, SkillEvalStoreError
from .skills import SkillRegistry


_REPORT_ID_RE = re.compile(r"^SKILL-EVAL-[0-9a-f]{20}$")


@dataclass(frozen=True)
class SkillBenchmarkReplayStatus:
    report_id: str
    content_hash: str
    suite_hash: str
    replayable: bool
    stale_case_ids: tuple[str, ...]
    stale_skill_refs: tuple[str, ...]


class SkillEvalReplayInspector:
    """Verify stored report integrity and whether its live inputs still match."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        store: SkillEvalStore | None = None,
        registry: SkillRegistry | None = None,
    ):
        self.runtime = runtime
        self.store = store or SkillEvalStore(runtime)
        self.registry = registry or SkillRegistry(runtime)

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

    @classmethod
    def _hash(cls, value: object) -> str:
        return f"sha256:{hashlib.sha256(cls._canonical_bytes(value)).hexdigest()}"

    def list_report_ids(self) -> tuple[str, ...]:
        self.store.ensure()
        values: list[str] = []
        for item in sorted(self.store.reports_dir.iterdir(), key=lambda path: path.name):
            if item.is_symlink() or not item.is_file() or item.suffix != ".json":
                raise SkillEvalStoreError(
                    f"Skill eval report registry contains unsupported entry: {item.name}"
                )
            if not _REPORT_ID_RE.fullmatch(item.stem):
                raise SkillEvalStoreError(f"invalid Skill eval report filename: {item.name}")
            values.append(item.stem)
        return tuple(values)

    def load_report_envelope(self, report_id: str) -> dict[str, object]:
        if not _REPORT_ID_RE.fullmatch(report_id):
            raise SkillEvalStoreError(f"invalid Skill benchmark report ID: {report_id!r}")
        self.store.ensure()
        path = self.store.reports_dir / f"{report_id}.json"
        if path.is_symlink() or not path.is_file():
            raise KeyError(report_id)
        with path.open("rb") as handle:
            data = handle.read(self.store.max_report_bytes + 1)
        if len(data) > self.store.max_report_bytes:
            raise SkillEvalStoreError(
                f"Skill benchmark report exceeds byte limit ({len(data)} > {self.store.max_report_bytes})"
            )
        content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
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
        if raw["format_version"] != self.store.FORMAT_VERSION:
            raise SkillEvalStoreError(
                f"unsupported Skill benchmark report format: {raw['format_version']}"
            )
        if not isinstance(raw["suite_hash"], str) or not isinstance(raw["report"], dict):
            raise SkillEvalStoreError(f"invalid Skill benchmark report fields: {report_id}")
        return raw

    @staticmethod
    def _report_cases(report: dict[str, object]) -> tuple[tuple[str, str], ...]:
        comparisons = report.get("comparisons")
        if not isinstance(comparisons, list):
            raise SkillEvalStoreError("Skill benchmark report comparisons must be an array")
        pairs: list[tuple[str, str]] = []
        for item in comparisons:
            if not isinstance(item, dict):
                raise SkillEvalStoreError("Skill benchmark comparison must be an object")
            case_id = item.get("case_id")
            case_hash = item.get("case_hash")
            if not isinstance(case_id, str) or not isinstance(case_hash, str):
                raise SkillEvalStoreError("Skill benchmark comparison case identity is invalid")
            pairs.append((case_id, case_hash))
        if len(pairs) != len({case_id for case_id, _ in pairs}):
            raise SkillEvalStoreError("Skill benchmark report contains duplicate case IDs")
        return tuple(pairs)

    def inspect(self, report_id: str) -> SkillBenchmarkReplayStatus:
        envelope = self.load_report_envelope(report_id)
        report = envelope["report"]
        assert isinstance(report, dict)
        pairs = self._report_cases(report)
        expected_suite_hash = self._hash(sorted(pairs))
        suite_hash = envelope["suite_hash"]
        assert isinstance(suite_hash, str)
        if suite_hash != expected_suite_hash:
            raise SkillEvalStoreError(
                f"Skill benchmark suite hash mismatch: {suite_hash} != {expected_suite_hash}"
            )

        stale_cases: list[str] = []
        for case_id, expected_hash in pairs:
            try:
                case = self.store.load_case(case_id)
            except (KeyError, SkillEvalStoreError):
                stale_cases.append(case_id)
                continue
            if case.content_hash != expected_hash:
                stale_cases.append(case_id)

        refs = report.get("skill_refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise SkillEvalStoreError("Skill benchmark report skill_refs are invalid")
        stale_refs: list[str] = []
        for ref in refs:
            if "@" not in ref:
                raise SkillEvalStoreError(f"invalid Skill ref in benchmark report: {ref}")
            name = ref.split("@", 1)[0]
            try:
                current = self.registry.load(name)
            except (KeyError, Exception) as exc:
                # Missing/invalid live Skills make the old report non-replayable,
                # not invalid as historical evidence.
                stale_refs.append(ref)
                continue
            if current.ref != ref:
                stale_refs.append(ref)

        path = self.store.reports_dir / f"{report_id}.json"
        data = path.read_bytes()
        content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        return SkillBenchmarkReplayStatus(
            report_id=report_id,
            content_hash=content_hash,
            suite_hash=suite_hash,
            replayable=not stale_cases and not stale_refs,
            stale_case_ids=tuple(stale_cases),
            stale_skill_refs=tuple(stale_refs),
        )
