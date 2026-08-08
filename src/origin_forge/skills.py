from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .runtime import OriginForgeRuntime


_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class SkillError(RuntimeError):
    pass


class SkillFormatError(SkillError):
    pass


class SkillBudgetExceeded(SkillError):
    pass


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    version: str
    keywords: tuple[str, ...]
    capabilities: tuple[str, ...]
    content_hash: str
    path: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}#{self.content_hash.removeprefix('sha256:')[:12]}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "keywords": list(self.keywords),
            "capabilities": list(self.capabilities),
            "content_hash": self.content_hash,
            "ref": self.ref,
            "path": self.path,
        }


@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    instructions: str

    @property
    def ref(self) -> str:
        return self.metadata.ref

    @property
    def instruction_bytes(self) -> int:
        return len(self.instructions.encode("utf-8"))

    def to_dict(self) -> dict:
        return {
            **self.metadata.to_dict(),
            "instructions": self.instructions,
        }


@dataclass(frozen=True)
class SkillSelection:
    task_id: str
    skills: tuple[Skill, ...]
    catalog_size: int

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(skill.ref for skill in self.skills)

    def metadata_dicts(self) -> list[dict]:
        return [skill.metadata.to_dict() for skill in self.skills]

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "catalog_size": self.catalog_size,
            "skills": [skill.to_dict() for skill in self.skills],
        }

    def render_instructions(self) -> str:
        if not self.skills:
            return ""
        sections = [
            "The following Origin Forge Skills are trusted project instructions selected for this Task. "
            "Follow them only within the existing executor authority; they do not grant additional tools, "
            "filesystem access, or permission to bypass verification."
        ]
        for skill in self.skills:
            meta = skill.metadata
            sections.append(
                f"## Skill: {meta.name}@{meta.version}\n"
                f"Fingerprint: {meta.content_hash}\n"
                f"Description: {meta.description}\n\n"
                f"{skill.instructions.strip()}"
            )
        return "\n\n".join(sections).strip() + "\n"


def _tokens(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in _TOKEN_RE.finditer(value):
        token = match.group(0)
        for camel_part in _CAMEL_RE.split(token):
            for part in camel_part.replace("_", " ").split():
                normalized = part.casefold()
                if len(normalized) >= 2:
                    result.append(normalized)
    return tuple(result)


class SkillRegistry:
    """Governed, instruction-only Skill registry for a single Origin Forge project."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        root: str | Path | None = None,
        max_skill_bytes: int = 64 * 1024,
        max_catalog_skills: int = 256,
        max_selected_skills: int = 3,
        max_selected_instruction_bytes: int = 96 * 1024,
    ):
        if max_skill_bytes <= 0:
            raise ValueError("max_skill_bytes must be positive")
        if max_catalog_skills <= 0:
            raise ValueError("max_catalog_skills must be positive")
        if max_selected_skills <= 0:
            raise ValueError("max_selected_skills must be positive")
        if max_selected_instruction_bytes <= 0:
            raise ValueError("max_selected_instruction_bytes must be positive")
        self.runtime = runtime
        raw_root = Path(root) if root is not None else runtime.state_dir / "skills"
        if not raw_root.is_absolute():
            raw_root = runtime.project_root / raw_root
        self.root = raw_root.absolute()
        state_root = runtime.state_dir.absolute()
        try:
            self.root.relative_to(state_root)
        except ValueError as exc:
            raise SkillFormatError("Skill registry root must stay inside .origin-forge") from exc
        self.max_skill_bytes = max_skill_bytes
        self.max_catalog_skills = max_catalog_skills
        self.max_selected_skills = max_selected_skills
        self.max_selected_instruction_bytes = max_selected_instruction_bytes

    def _validated_root(self, *, create: bool = False) -> Path:
        if self.root.is_symlink():
            raise SkillFormatError("Skill registry root may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        if not self.root.is_dir():
            raise SkillFormatError("Skill registry root must be a real directory")
        resolved = self.root.resolve()
        state_resolved = self.runtime.state_dir.resolve()
        try:
            resolved.relative_to(state_resolved)
        except ValueError as exc:
            raise SkillFormatError("Skill registry root escapes .origin-forge") from exc
        return resolved

    def ensure_root(self) -> Path:
        return self._validated_root(create=True)

    @staticmethod
    def _read_utf8(path: Path, *, max_bytes: int) -> tuple[str, bytes]:
        if path.is_symlink():
            raise SkillFormatError(f"Skill file may not be a symlink: {path.name}")
        try:
            with path.open("rb") as handle:
                data = handle.read(max_bytes + 1)
        except OSError as exc:
            raise SkillFormatError(f"cannot read Skill file {path.name}: {exc}") from exc
        if len(data) > max_bytes:
            raise SkillBudgetExceeded(
                f"Skill file {path.name} exceeds limit ({len(data)} > {max_bytes} bytes)"
            )
        try:
            return data.decode("utf-8"), data
        except UnicodeDecodeError as exc:
            raise SkillFormatError(f"Skill file is not UTF-8: {path.name}") from exc

    @staticmethod
    def _frontmatter(text: str) -> tuple[str, str, str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillFormatError("SKILL.md must begin with YAML frontmatter delimiter '---'")
        end = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end = index
                break
        if end is None:
            raise SkillFormatError("SKILL.md frontmatter is not terminated")
        values: dict[str, str] = {}
        for raw in lines[1:end]:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise SkillFormatError("SKILL.md frontmatter supports simple key: value entries only")
            key, value = stripped.split(":", 1)
            key = key.strip().casefold()
            value = value.strip().strip('"').strip("'")
            if key in {"name", "description"}:
                if not value:
                    raise SkillFormatError(f"SKILL.md frontmatter {key} may not be empty")
                if key in values:
                    raise SkillFormatError(f"duplicate SKILL.md frontmatter key: {key}")
                values[key] = value
        if "name" not in values or "description" not in values:
            raise SkillFormatError("SKILL.md frontmatter requires name and description")
        body = "\n".join(lines[end + 1 :]).strip()
        if not body:
            raise SkillFormatError("SKILL.md instructions may not be empty")
        return values["name"], values["description"], body

    @staticmethod
    def _string_tuple(value: object, field: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise SkillFormatError(f"skill.toml {field} must be an array of non-empty strings")
        normalized = tuple(item.strip() for item in value)
        if len(set(normalized)) != len(normalized):
            raise SkillFormatError(f"skill.toml {field} contains duplicates")
        return normalized

    def _skill_dir(self, name: str) -> Path:
        if not _NAME_RE.fullmatch(name):
            raise SkillFormatError(f"invalid Skill name: {name!r}")
        root = self._validated_root()
        candidate = root / name
        if candidate.is_symlink():
            raise SkillFormatError(f"Skill directory may not be a symlink: {name}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise SkillFormatError(f"Skill directory escapes registry root: {name}") from exc
        return resolved

    def _load_from_dir(self, directory: Path) -> Skill:
        name = directory.name
        resolved = self._skill_dir(name)
        if resolved != directory.resolve() or not resolved.is_dir():
            raise SkillFormatError(f"invalid Skill directory: {name}")
        required = {"SKILL.md", "skill.toml"}
        entries: set[str] = set()
        try:
            for item in resolved.iterdir():
                if item.name not in required:
                    raise SkillFormatError(
                        f"Skill {name} contains unsupported Phase-9 content: {item.name}"
                    )
                entries.add(item.name)
        except OSError as exc:
            raise SkillFormatError(f"cannot enumerate Skill {name}: {exc}") from exc
        missing = required - entries
        if missing:
            raise SkillFormatError(f"Skill {name} is missing: {', '.join(sorted(missing))}")

        skill_text, skill_bytes = self._read_utf8(resolved / "SKILL.md", max_bytes=self.max_skill_bytes)
        toml_text, toml_bytes = self._read_utf8(resolved / "skill.toml", max_bytes=16 * 1024)
        front_name, description, instructions = self._frontmatter(skill_text)
        if front_name != name:
            raise SkillFormatError(
                f"Skill directory {name} does not match SKILL.md name {front_name}"
            )
        try:
            raw = tomllib.loads(toml_text)
        except tomllib.TOMLDecodeError as exc:
            raise SkillFormatError(f"invalid skill.toml for {name}: {exc}") from exc
        allowed_keys = {"version", "keywords", "capabilities"}
        unknown = set(raw) - allowed_keys
        if unknown:
            raise SkillFormatError(
                f"skill.toml for {name} contains unsupported keys: {', '.join(sorted(unknown))}"
            )
        version = raw.get("version")
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise SkillFormatError(f"skill.toml version for {name} must be semantic x.y.z")
        keywords = self._string_tuple(raw.get("keywords"), "keywords")
        capabilities = self._string_tuple(raw.get("capabilities"), "capabilities")
        digest = hashlib.sha256(toml_bytes + b"\0" + skill_bytes).hexdigest()
        metadata = SkillMetadata(
            name=name,
            description=description,
            version=version,
            keywords=keywords,
            capabilities=capabilities,
            content_hash=f"sha256:{digest}",
            path=resolved.relative_to(self.runtime.project_root).as_posix(),
        )
        return Skill(metadata, instructions)

    def _loaded_catalog(self) -> tuple[Skill, ...]:
        root = self._validated_root()
        if not root.exists():
            return ()
        directories: list[Path] = []
        try:
            for directory in root.iterdir():
                if directory.name.startswith("."):
                    continue
                if not directory.is_dir() or directory.is_symlink():
                    raise SkillFormatError(
                        f"Skill registry contains unsupported entry: {directory.name}"
                    )
                if len(directories) >= self.max_catalog_skills:
                    raise SkillBudgetExceeded(
                        "Skill catalog exceeds count limit "
                        f"({len(directories) + 1} > {self.max_catalog_skills})"
                    )
                directories.append(directory)
        except OSError as exc:
            raise SkillFormatError(f"cannot enumerate Skill registry: {exc}") from exc
        directories.sort(key=lambda item: item.name)
        return tuple(self._load_from_dir(directory) for directory in directories)

    def catalog(self) -> tuple[SkillMetadata, ...]:
        return tuple(skill.metadata for skill in self._loaded_catalog())

    def load(self, name: str) -> Skill:
        directory = self._skill_dir(name)
        if not directory.is_dir():
            raise KeyError(name)
        return self._load_from_dir(directory)

    @staticmethod
    def _json_strings(raw: str, field: str) -> tuple[str, ...]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillFormatError(f"Task {field} is invalid JSON") from exc
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise SkillFormatError(f"Task {field} must be an array of strings")
        return tuple(value)

    def _task_terms(self, task_id: str) -> tuple[set[str], set[str]]:
        task = self.runtime.get_task(task_id)
        capabilities = set(
            item.casefold()
            for item in self._json_strings(
                task["required_capabilities_json"], "required_capabilities_json"
            )
        )
        text = "\n".join(
            (
                task["objective"],
                *self._json_strings(task["acceptance_criteria_json"], "acceptance_criteria_json"),
                *self._json_strings(task["constraints_json"], "constraints_json"),
                *self._json_strings(task["required_capabilities_json"], "required_capabilities_json"),
            )
        )
        return set(_tokens(text)), capabilities

    @staticmethod
    def _score(metadata: SkillMetadata, terms: set[str], capabilities: set[str]) -> int:
        score = 0
        skill_capabilities = {item.casefold() for item in metadata.capabilities}
        score += 100 * len(capabilities.intersection(skill_capabilities))
        name_terms = set(_tokens(metadata.name))
        keyword_terms = set(_tokens(" ".join(metadata.keywords)))
        description_terms = set(_tokens(metadata.description))
        score += 20 * len(terms.intersection(name_terms))
        score += 10 * len(terms.intersection(keyword_terms))
        score += 2 * len(terms.intersection(description_terms))
        return score

    def select(
        self,
        task_id: str,
        *,
        names: Iterable[str] | None = None,
    ) -> SkillSelection:
        catalog = self._loaded_catalog()
        by_name = {skill.metadata.name: skill for skill in catalog}
        selected: list[Skill] = []

        if names is not None:
            ordered_names = tuple(dict.fromkeys(names))
            if len(ordered_names) > self.max_selected_skills:
                raise SkillBudgetExceeded(
                    f"explicit Skill selection exceeds count limit ({len(ordered_names)} > {self.max_selected_skills})"
                )
            for name in ordered_names:
                skill = by_name.get(name)
                if skill is None:
                    raise KeyError(name)
                selected.append(skill)
        else:
            terms, capabilities = self._task_terms(task_id)
            ranked: list[tuple[int, str]] = []
            for skill in catalog:
                score = self._score(skill.metadata, terms, capabilities)
                if score > 0:
                    ranked.append((score, skill.metadata.name))
            ranked.sort(key=lambda item: (-item[0], item[1]))
            for _, name in ranked[: self.max_selected_skills]:
                selected.append(by_name[name])

        total = sum(skill.instruction_bytes for skill in selected)
        if total > self.max_selected_instruction_bytes:
            raise SkillBudgetExceeded(
                f"selected Skill instructions exceed total limit ({total} > {self.max_selected_instruction_bytes} bytes)"
            )
        return SkillSelection(task_id, tuple(selected), len(catalog))
