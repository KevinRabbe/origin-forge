from __future__ import annotations

from dataclasses import dataclass

from .runtime import OriginForgeRuntime
from .skill_eval_store import SkillEvalStore, SkillEvalStoreError
from .skills import SkillRegistry


@dataclass(frozen=True)
class SkillBenchmarkReplayStatus:
    report_id: str
    content_hash: str
    suite_hash: str
    protocol_id: str
    environment_fingerprint: str
    replayable: bool
    stale_case_ids: tuple[str, ...]
    stale_skill_refs: tuple[str, ...]


class SkillEvalReplayInspector:
    """Verify stored report semantics and whether its live inputs still match."""

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

    def list_report_ids(self) -> tuple[str, ...]:
        return self.store.list_report_ids()

    @staticmethod
    def _case_pairs(report: dict[str, object]) -> tuple[tuple[str, str], ...]:
        comparisons = report.get("comparisons")
        if not isinstance(comparisons, list):
            raise SkillEvalStoreError("Skill benchmark report comparisons must be an array")
        if len(comparisons) > 128:
            raise SkillEvalStoreError("Skill benchmark report exceeds comparison limit")
        pairs: list[tuple[str, str]] = []
        for item in comparisons:
            if not isinstance(item, dict):
                raise SkillEvalStoreError("Skill benchmark comparison must be an object")
            case_id = item.get("case_id")
            case_hash = item.get("case_hash")
            if not isinstance(case_id, str) or not isinstance(case_hash, str):
                raise SkillEvalStoreError("Skill benchmark comparison case identity is invalid")
            pairs.append((case_id, case_hash))
        if not pairs:
            raise SkillEvalStoreError("Skill benchmark report has no comparisons")
        if len(pairs) != len({case_id for case_id, _ in pairs}):
            raise SkillEvalStoreError("Skill benchmark report contains duplicate case IDs")
        return tuple(pairs)

    @staticmethod
    def _validate_top_level(report: dict[str, object]) -> tuple[str, str, tuple[str, ...]]:
        expected = {
            "protocol_id",
            "environment_fingerprint",
            "skill_refs",
            "repetitions",
            "seed_base",
            "overall_verdict",
            "improved_cases",
            "regressed_cases",
            "comparisons",
        }
        if set(report) != expected:
            raise SkillEvalStoreError("Skill benchmark report fields are invalid")
        protocol_id = report["protocol_id"]
        environment = report["environment_fingerprint"]
        refs = report["skill_refs"]
        repetitions = report["repetitions"]
        if protocol_id != "paired-skill-ab-v1":
            raise SkillEvalStoreError(f"unsupported Skill benchmark protocol: {protocol_id}")
        if not isinstance(environment, str) or not environment:
            raise SkillEvalStoreError("Skill benchmark environment fingerprint is invalid")
        if not isinstance(repetitions, int) or isinstance(repetitions, bool) or not 1 <= repetitions <= 20:
            raise SkillEvalStoreError("Skill benchmark repetitions are invalid")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            raise SkillEvalStoreError("Skill benchmark skill_refs are invalid")
        return protocol_id, environment, tuple(refs)

    def inspect(self, report_id: str) -> SkillBenchmarkReplayStatus:
        loaded = self.store.load_report(report_id)
        report = loaded.envelope["report"]
        assert isinstance(report, dict)
        protocol_id, environment, refs = self._validate_top_level(report)
        pairs = self._case_pairs(report)

        expected_suite_hash = self.store._sha256(
            self.store._canonical_bytes(sorted(pairs))
        )
        if loaded.suite_hash != expected_suite_hash:
            raise SkillEvalStoreError(
                f"Skill benchmark suite hash mismatch: {loaded.suite_hash} != {expected_suite_hash}"
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

        stale_refs: list[str] = []
        for ref in refs:
            if "@" not in ref:
                raise SkillEvalStoreError(f"invalid Skill ref in benchmark report: {ref}")
            name = ref.split("@", 1)[0]
            try:
                current = self.registry.load(name)
            except Exception:
                stale_refs.append(ref)
                continue
            if current.ref != ref:
                stale_refs.append(ref)

        return SkillBenchmarkReplayStatus(
            report_id=loaded.report_id,
            content_hash=loaded.content_hash,
            suite_hash=loaded.suite_hash,
            protocol_id=protocol_id,
            environment_fingerprint=environment,
            replayable=not stale_cases and not stale_refs,
            stale_case_ids=tuple(stale_cases),
            stale_skill_refs=tuple(stale_refs),
        )
