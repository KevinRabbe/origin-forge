from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


PROTECTED_ROOTS = frozenset({".git", ".origin-forge"})


def is_protected_root(name: str) -> bool:
    """Return whether a top-level path component is infrastructure state.

    Comparison is deliberately case-insensitive even on case-sensitive hosts so
    a proposal/context path has identical security semantics when a repository
    later runs on Windows or another case-insensitive filesystem.
    """

    return name.casefold() in PROTECTED_ROOTS


def portable_relative_path(raw: str) -> PurePosixPath:
    """Parse one cross-platform Origin Forge repository path.

    Serialized repository paths use POSIX (`/`) separators on every host.
    Ambiguous or host-dependent spellings are rejected rather than normalized,
    so the same durable Task/Artifact always names the same repository object.
    """

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty string")
    if "\x00" in raw:
        raise ValueError("path may not contain NUL")
    if "\\" in raw:
        raise ValueError("repository paths must use '/' separators")

    windows = PureWindowsPath(raw)
    if windows.drive or windows.root:
        raise ValueError("path must be project-relative on every supported host")

    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("path is invalid")

    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts:
        raise ValueError("path must be project-relative")
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
