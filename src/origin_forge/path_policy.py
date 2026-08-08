from __future__ import annotations

from pathlib import PurePosixPath


PROTECTED_ROOTS = frozenset({".git", ".origin-forge"})


def is_protected_root(name: str) -> bool:
    """Return whether a top-level path component is infrastructure state.

    Comparison is deliberately case-insensitive even on case-sensitive hosts so
    a proposal/context path has identical security semantics when a repository
    later runs on Windows or another case-insensitive filesystem.
    """

    return name.casefold() in PROTECTED_ROOTS


def portable_relative_path(raw: str) -> PurePosixPath:
    """Parse an Origin Forge repository path using one cross-platform syntax.

    Origin Forge-generated paths are POSIX-style (`/`) regardless of the host.
    Backslashes are rejected rather than interpreted differently on Windows and
    Linux. This prevents one serialized Task/Artifact from naming different
    files depending on the machine that consumes it.
    """

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty string")
    if "\\" in raw:
        raise ValueError("repository paths must use '/' separators")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts:
        raise ValueError("path must be project-relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path is invalid")
    if is_protected_root(path.parts[0]):
        raise ValueError("path enters protected Origin Forge state")
    return path


def portable_path_key(path: str | PurePosixPath) -> str:
    """Return a conservative cross-platform identity key for a repo path.

    Case-folding intentionally rejects two proposed paths that differ only by
    case. Such a pair cannot be represented safely on common Windows filesystems
    and would make deterministic audit/application semantics host-dependent.
    """

    value = path if isinstance(path, PurePosixPath) else portable_relative_path(path)
    return value.as_posix().casefold()
