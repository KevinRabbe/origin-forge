from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .audio_models import (
    AudioOperation,
    canonical_bytes,
    content_hash,
    validate_sha256,
)
from .ids import IdKind, new_id, validate_id
from .runtime import OriginForgeRuntime


_MAX_PROFILE_BYTES = 64 * 1024
_MAX_PROFILES = 256
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")


class AudioProfileError(RuntimeError):
    pass


class AudioProfileKind(StrEnum):
    PROCEDURAL_SFX = "PROCEDURAL_SFX"
    PROCEDURAL_MUSIC = "PROCEDURAL_MUSIC"
    FFMPEG_PCM16 = "FFMPEG_PCM16"
    PIPER_TTS = "PIPER_TTS"
    NEURAL_AUDIO = "NEURAL_AUDIO"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise AudioProfileError(f"{label} must be a bounded identity token")
    return value


@dataclass(frozen=True)
class GovernedAudioProfile:
    profile_id: str
    kind: AudioProfileKind
    operation: AudioOperation
    backend_id: str
    backend_version: str
    runtime_hash: str
    target_sample_rate: int
    target_channels: int
    model_id: str | None = None
    model_hash: str | None = None
    model_config_hash: str | None = None
    license_id: str | None = None
    license_hash: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.profile_id, IdKind.AUDIO_PROFILE):
            raise AudioProfileError("profile_id must be an AUDPROF ID")
        if not isinstance(self.kind, AudioProfileKind):
            raise AudioProfileError("kind must be an AudioProfileKind")
        if not isinstance(self.operation, AudioOperation):
            raise AudioProfileError("operation must be an AudioOperation")
        object.__setattr__(self, "backend_id", _token(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _token(self.backend_version, "backend_version")
        )
        try:
            validate_sha256(self.runtime_hash, "runtime_hash")
        except ValueError as exc:
            raise AudioProfileError(str(exc)) from exc
        if not isinstance(self.target_sample_rate, int) or not 8_000 <= self.target_sample_rate <= 192_000:
            raise AudioProfileError("target_sample_rate is outside allowed range")
        if self.target_channels not in {1, 2}:
            raise AudioProfileError("target_channels must be mono or stereo")
        if (self.model_id is None) != (self.model_hash is None):
            raise AudioProfileError("model_id and model_hash must be supplied together")
        if self.model_id is not None:
            object.__setattr__(self, "model_id", _token(self.model_id, "model_id"))
            try:
                validate_sha256(self.model_hash or "", "model_hash")
            except ValueError as exc:
                raise AudioProfileError(str(exc)) from exc
        if self.model_config_hash is not None:
            try:
                validate_sha256(self.model_config_hash, "model_config_hash")
            except ValueError as exc:
                raise AudioProfileError(str(exc)) from exc
            if self.model_id is None:
                raise AudioProfileError("model_config_hash requires a model identity")
        if (self.license_id is None) != (self.license_hash is None):
            raise AudioProfileError("license_id and license_hash must be supplied together")
        if self.license_id is not None:
            object.__setattr__(self, "license_id", _token(self.license_id, "license_id"))
            try:
                validate_sha256(self.license_hash or "", "license_hash")
            except ValueError as exc:
                raise AudioProfileError(str(exc)) from exc
        self._validate_kind()

    def _validate_kind(self) -> None:
        expected_operation = {
            AudioProfileKind.PROCEDURAL_SFX: AudioOperation.SYNTHESIZE_SFX,
            AudioProfileKind.PROCEDURAL_MUSIC: AudioOperation.GENERATE_MUSIC,
            AudioProfileKind.FFMPEG_PCM16: AudioOperation.PROCESS_AUDIO,
            AudioProfileKind.PIPER_TTS: AudioOperation.SYNTHESIZE_SPEECH,
        }.get(self.kind)
        if expected_operation is not None and self.operation is not expected_operation:
            raise AudioProfileError(
                f"{self.kind.value} requires operation {expected_operation.value}"
            )
        if self.kind in {AudioProfileKind.PIPER_TTS, AudioProfileKind.NEURAL_AUDIO}:
            if (
                self.model_id is None
                or self.model_config_hash is None
                or self.license_id is None
                or self.license_hash is None
            ):
                raise AudioProfileError(
                    f"{self.kind.value} requires exact model, config, and license evidence"
                )
        elif (
            self.model_id is not None
            or self.model_config_hash is not None
            or self.license_id is not None
            or self.license_hash is not None
        ):
            raise AudioProfileError(
                f"{self.kind.value} may not bind model or license evidence"
            )

    @classmethod
    def create(
        cls,
        *,
        kind: AudioProfileKind,
        operation: AudioOperation,
        backend_id: str,
        backend_version: str,
        runtime_hash: str,
        target_sample_rate: int,
        target_channels: int,
        model_id: str | None = None,
        model_hash: str | None = None,
        model_config_hash: str | None = None,
        license_id: str | None = None,
        license_hash: str | None = None,
    ) -> "GovernedAudioProfile":
        return cls(
            profile_id=new_id(IdKind.AUDIO_PROFILE),
            kind=kind,
            operation=operation,
            backend_id=backend_id,
            backend_version=backend_version,
            runtime_hash=runtime_hash,
            target_sample_rate=target_sample_rate,
            target_channels=target_channels,
            model_id=model_id,
            model_hash=model_hash,
            model_config_hash=model_config_hash,
            license_id=license_id,
            license_hash=license_hash,
        )

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "profile_id": self.profile_id,
            "kind": self.kind.value,
            "operation": self.operation.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "runtime_hash": self.runtime_hash,
            "target_sample_rate": self.target_sample_rate,
            "target_channels": self.target_channels,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "model_config_hash": self.model_config_hash,
            "license_id": self.license_id,
            "license_hash": self.license_hash,
        }

    @property
    def profile_hash(self) -> str:
        return content_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["profile_hash"] = self.profile_hash
        return value


@dataclass(frozen=True)
class StoredAudioProfile:
    profile_id: str
    profile_hash: str
    path: Path
    byte_count: int


class AudioProfileStore:
    """Protected immutable registry for reviewed audio execution profiles."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_profile_bytes: int = _MAX_PROFILE_BYTES,
        max_profiles: int = _MAX_PROFILES,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(max_profile_bytes, int) or not 1 <= max_profile_bytes <= _MAX_PROFILE_BYTES:
            raise ValueError("max_profile_bytes is outside allowed range")
        if not isinstance(max_profiles, int) or not 1 <= max_profiles <= _MAX_PROFILES:
            raise ValueError("max_profiles is outside allowed range")
        self.runtime = runtime
        self.root = runtime.state_dir / "audio-profiles"
        self.max_profile_bytes = max_profile_bytes
        self.max_profiles = max_profiles

    def _root(self, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.root.is_symlink():
            raise AudioProfileError("audio profile root may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise AudioProfileError("audio profile root escapes protected state") from exc
        if not resolved.is_dir():
            raise AudioProfileError("audio profile root must be a directory")
        return resolved

    @staticmethod
    def _name(profile_id: str, profile_hash: str) -> str:
        if not validate_id(profile_id, IdKind.AUDIO_PROFILE):
            raise AudioProfileError("profile_id must be an AUDPROF ID")
        try:
            validate_sha256(profile_hash, "profile_hash")
        except ValueError as exc:
            raise AudioProfileError(str(exc)) from exc
        return f"{profile_id}--{profile_hash.removeprefix('sha256:')}.json"

    def _catalog(self) -> tuple[Path, ...]:
        root = self._root(create=False)
        if not root.exists():
            return ()
        result: list[Path] = []
        for path in root.iterdir():
            if path.is_symlink():
                raise AudioProfileError("audio profile store contains a symlink")
            if not path.is_file() or path.suffix != ".json":
                raise AudioProfileError("audio profile store contains an undeclared entry")
            if path.stat().st_size > self.max_profile_bytes:
                raise AudioProfileError("stored audio profile exceeds byte limit")
            result.append(path)
            if len(result) > self.max_profiles:
                raise AudioProfileError("audio profile catalog exceeds item limit")
        return tuple(sorted(result, key=lambda path: path.name))

    def put(self, profile: GovernedAudioProfile) -> StoredAudioProfile:
        if not isinstance(profile, GovernedAudioProfile):
            raise TypeError("profile must be a GovernedAudioProfile")
        root = self._root(create=True)
        catalog = self._catalog()
        data = canonical_bytes(profile.to_dict())
        if len(data) > self.max_profile_bytes:
            raise AudioProfileError("audio profile exceeds byte limit")
        target = root / self._name(profile.profile_id, profile.profile_hash)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise AudioProfileError("audio profile content-addressed target is unsafe or drifted")
            return StoredAudioProfile(profile.profile_id, profile.profile_hash, target, len(data))
        if len(catalog) >= self.max_profiles:
            raise AudioProfileError("audio profile catalog is full")
        temp = root / f".{target.name}.{os.getpid()}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                    raise AudioProfileError("competing audio profile publication drifted")
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return StoredAudioProfile(profile.profile_id, profile.profile_hash, target, len(data))

    @staticmethod
    def _parse(value: object) -> GovernedAudioProfile:
        if not isinstance(value, dict):
            raise AudioProfileError("stored audio profile must be an object")
        expected = {
            "schema_version",
            "profile_id",
            "kind",
            "operation",
            "backend_id",
            "backend_version",
            "runtime_hash",
            "target_sample_rate",
            "target_channels",
            "model_id",
            "model_hash",
            "model_config_hash",
            "license_id",
            "license_hash",
            "profile_hash",
        }
        if set(value) != expected or value.get("schema_version") != 2:
            raise AudioProfileError("stored audio profile has unknown or missing fields")
        try:
            profile = GovernedAudioProfile(
                profile_id=value["profile_id"],
                kind=AudioProfileKind(value["kind"]),
                operation=AudioOperation(value["operation"]),
                backend_id=value["backend_id"],
                backend_version=value["backend_version"],
                runtime_hash=value["runtime_hash"],
                target_sample_rate=value["target_sample_rate"],
                target_channels=value["target_channels"],
                model_id=value["model_id"],
                model_hash=value["model_hash"],
                model_config_hash=value["model_config_hash"],
                license_id=value["license_id"],
                license_hash=value["license_hash"],
            )
        except (KeyError, TypeError, ValueError, AudioProfileError) as exc:
            raise AudioProfileError("stored audio profile is invalid") from exc
        if value["profile_hash"] != profile.profile_hash:
            raise AudioProfileError("stored audio profile hash mismatch")
        return profile

    def get(self, profile_id: str, profile_hash: str) -> GovernedAudioProfile:
        path = self._root(create=False) / self._name(profile_id, profile_hash)
        if path.is_symlink() or not path.is_file():
            raise KeyError((profile_id, profile_hash))
        if path.stat().st_size > self.max_profile_bytes:
            raise AudioProfileError("stored audio profile exceeds byte limit")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AudioProfileError("stored audio profile is not valid UTF-8 JSON") from exc
        profile = self._parse(value)
        if profile.profile_id != profile_id or profile.profile_hash != profile_hash:
            raise AudioProfileError("stored audio profile identity mismatch")
        return profile

    def list(self) -> tuple[StoredAudioProfile, ...]:
        result: list[StoredAudioProfile] = []
        for path in self._catalog():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                profile = self._parse(value)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AudioProfileError("stored audio profile is invalid") from exc
            if path.name != self._name(profile.profile_id, profile.profile_hash):
                raise AudioProfileError("stored audio profile filename/identity mismatch")
            result.append(
                StoredAudioProfile(
                    profile.profile_id,
                    profile.profile_hash,
                    path,
                    path.stat().st_size,
                )
            )
        return tuple(result)
