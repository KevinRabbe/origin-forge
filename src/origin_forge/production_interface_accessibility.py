from __future__ import annotations


_STYLE_MARKER = "</style>"
_MAIN_MARKER = '<main id="main" class="cockpit-main">'
_OVERVIEW_CURRENT = '<a href="/" aria-current="page">Overview</a>'
_ACCESSIBILITY_CSS = """
.cockpit-main [id] { scroll-margin-top: 90px; }
.cockpit-main:focus { outline: none; }
.cockpit-main:focus-visible { box-shadow: inset 0 3px 0 var(--accent); }
@media (max-width: 700px) {
  .cockpit-main [id] { scroll-margin-top: 78px; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}
"""


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit accessibility marker is missing")
    return page.replace(old, new, 1)


def _base(page: str) -> str:
    page = _replace_once(page, _STYLE_MARKER, _ACCESSIBILITY_CSS + _STYLE_MARKER)
    return _replace_once(
        page,
        _MAIN_MARKER,
        '<main id="main" class="cockpit-main" tabindex="-1">',
    )


def decorate_overview_accessibility(page: str) -> str:
    page = _base(page)
    if _OVERVIEW_CURRENT not in page:
        raise ValueError("overview current-page marker is missing")
    return page


def decorate_detail_accessibility(page: str) -> str:
    page = _base(page)
    return _replace_once(page, _OVERVIEW_CURRENT, '<a href="/">Overview</a>')
