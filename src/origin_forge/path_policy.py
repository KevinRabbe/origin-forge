from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath


PROTECTED_ROOTS = frozenset({".git", ".origin-forge"})
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_BASES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "clock$",
        "conin$",
        "conout$",
    }
)
_WINDOWS_RESERVED_NUMBERED = re.compile(r"^(?:com|lpt)[1-9]$", re.IGNORECASE)


def is_protected_root(name: str) -> bool:
    """Return whether a top-level path component is infrastructure state.

    Comparison is deliberately case-insensitive even on case-sensitive hosts so
    a proposal/context path has identical security semantics when a repository
    later runs on Windows or another case-insensitive filesystem.
    """

    return name.casefold() in PROTECTED_ROOTS


def _validate_portable_component(component: str) -> None:
    if component in {"", ".", ".."}:
        raise ValueError("path is invalid")
    if unicodedata.normalize("NFC", component) != component:
        raise ValueError("repository path components must use NFC Unicode normalization")
    if component.endswith((" ", ".")):
        raise ValueError("repository path components may not end with space or dot")
    if any(ord(char) < 32 for char in component):
        raise ValueError("repository path components may not contain control characters")
    if any(char in _WINDOWS_INVALID_CHARS for char in component):
        raise ValueError("repository path contains characters unsafe on Windows")

    # Windows reserves these names even when an extension is present, e.g.
    # NUL.txt. A colon is already rejected above, also closing NTFS ADS syntax
    # such as file.py:metadata.
    base = component.split(".", 1)[0].casefold()
    if base in _WINDOWS_RESERVED_BASES or _WINDOWS_RESERVED_NUMBERED.fullmatch(base):
        raise ValueError(f"repository path uses Windows-reserved name: {component}")


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
    for component in raw_parts:
        _validate_portable_component(component)

    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts:
        raise ValueError("path must be project-relative")
    if is_protected_root(path.parts[0]):
        raise ValueError("path enters protected Origin Forge state")
    return path


def portable_path_key(path: str | PurePosixPath) -> str:
    """Return a conservative cross-platform identity key for a repo path.

    Case-folding plus NFC normalization intentionally rejects mutation paths that
    could alias on case-insensitive or Unicode-normalizing filesystems. Such a
    pair cannot participate safely in one durable cross-platform Task.
    """

    value = path if isinstance(path, PurePosixPath) else portable_relative_path(path)
    return unicodedata.normalize("NFC", value.as_posix()).casefold()
