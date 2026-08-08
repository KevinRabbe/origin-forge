from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .tool_catalog import AuthorizedToolView, ToolDescriptor


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class ToolSearchError(RuntimeError):
    pass


class ToolAccessDenied(ToolSearchError):
    pass


class ToolSearchBudgetExceeded(ToolSearchError):
    pass


class ToolDiscoveryEventType(StrEnum):
    SEARCH = "SEARCH"
    DESCRIBE = "DESCRIBE"


@dataclass(frozen=True)
class ToolSearchResult:
    tool_id: str
    ref: str
    score: int
    description: str
    capabilities: tuple[str, ...]
    effects: tuple[str, ...]
    deterministic: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "ref": self.ref,
            "score": self.score,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "effects": list(self.effects),
            "deterministic": self.deterministic,
        }


@dataclass(frozen=True)
class ToolDiscoveryEvent:
    event_type: ToolDiscoveryEventType
    ordinal: int
    query: str | None = None
    result_tool_ids: tuple[str, ...] = ()
    tool_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type.value,
            "ordinal": self.ordinal,
            "query": self.query,
            "result_tool_ids": list(self.result_tool_ids),
            "tool_id": self.tool_id,
        }


def _tokens(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in _TOKEN_RE.finditer(value):
        token = match.group(0)
        for camel in _CAMEL_RE.split(token):
            for part in camel.replace("_", " ").split():
                normalized = part.casefold()
                if len(normalized) >= 2:
                    result.append(normalized)
    return tuple(result)


def _score(descriptor: ToolDescriptor, query: str, terms: set[str]) -> int:
    if not terms:
        return 0
    score = 0
    capability_terms = set(_tokens(" ".join(descriptor.capabilities)))
    id_terms = set(_tokens(descriptor.tool_id.replace(".", " ").replace("-", " ")))
    keyword_terms = set(_tokens(" ".join(descriptor.keywords)))
    description_terms = set(_tokens(descriptor.description))

    score += 100 * len(terms.intersection(capability_terms))
    score += 40 * len(terms.intersection(id_terms))
    score += 20 * len(terms.intersection(keyword_terms))
    score += 4 * len(terms.intersection(description_terms))

    normalized_query = " ".join(_tokens(query))
    if normalized_query:
        normalized_id = " ".join(_tokens(descriptor.tool_id.replace(".", " ").replace("-", " ")))
        normalized_description = " ".join(_tokens(descriptor.description))
        if normalized_query == normalized_id:
            score += 80
        elif normalized_query in normalized_id:
            score += 40
        if normalized_query in normalized_description:
            score += 10
    return score


class ToolSearchSession:
    """Bounded progressive disclosure over one immutable authorized tool view.

    Search sees only descriptors already admitted to the view by external
    authority policy. Describe can hydrate only those same descriptors. Neither
    operation grants invocation authority or expands the hidden catalog.
    """

    def __init__(
        self,
        view: AuthorizedToolView,
        *,
        max_searches: int = 16,
        max_results_per_search: int = 8,
        max_hydrated_tools: int = 12,
        max_query_chars: int = 1024,
        max_query_terms: int = 32,
        max_search_description_chars: int = 320,
    ):
        for value, name in (
            (max_searches, "max_searches"),
            (max_results_per_search, "max_results_per_search"),
            (max_hydrated_tools, "max_hydrated_tools"),
            (max_query_chars, "max_query_chars"),
            (max_query_terms, "max_query_terms"),
            (max_search_description_chars, "max_search_description_chars"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.view = view
        self.max_searches = max_searches
        self.max_results_per_search = max_results_per_search
        self.max_hydrated_tools = max_hydrated_tools
        self.max_query_chars = max_query_chars
        self.max_query_terms = max_query_terms
        self.max_search_description_chars = max_search_description_chars
        self._searches = 0
        self._hydrated: set[str] = set()
        self._events: list[ToolDiscoveryEvent] = []

    @property
    def searches_used(self) -> int:
        return self._searches

    @property
    def hydrated_tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._hydrated))

    @property
    def events(self) -> tuple[ToolDiscoveryEvent, ...]:
        return tuple(self._events)

    def search_tools(
        self,
        query: str,
        *,
        limit: int | None = None,
    ) -> tuple[ToolSearchResult, ...]:
        if not isinstance(query, str) or not query.strip():
            raise ToolSearchError("tool search query must be a non-empty string")
        if len(query) > self.max_query_chars:
            raise ToolSearchError(
                f"tool search query exceeds character limit ({len(query)} > {self.max_query_chars})"
            )
        terms = set(_tokens(query))
        if not terms:
            raise ToolSearchError("tool search query has no searchable terms")
        if len(terms) > self.max_query_terms:
            raise ToolSearchError(
                f"tool search query exceeds term limit ({len(terms)} > {self.max_query_terms})"
            )
        if self._searches >= self.max_searches:
            raise ToolSearchBudgetExceeded(
                f"tool search budget exhausted ({self._searches} >= {self.max_searches})"
            )
        if limit is None:
            bounded_limit = self.max_results_per_search
        else:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise ToolSearchError("tool search limit must be a positive integer")
            bounded_limit = min(limit, self.max_results_per_search)

        ranked: list[tuple[int, str, ToolDescriptor]] = []
        for descriptor in self.view.descriptors:
            score = _score(descriptor, query, terms)
            if score > 0:
                ranked.append((score, descriptor.tool_id, descriptor))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        results: list[ToolSearchResult] = []
        for score, _, descriptor in ranked[:bounded_limit]:
            description = descriptor.description
            if len(description) > self.max_search_description_chars:
                description = description[: self.max_search_description_chars] + "…"
            results.append(
                ToolSearchResult(
                    tool_id=descriptor.tool_id,
                    ref=descriptor.ref,
                    score=score,
                    description=description,
                    capabilities=descriptor.capabilities,
                    effects=tuple(effect.value for effect in descriptor.effects),
                    deterministic=descriptor.deterministic,
                )
            )

        self._searches += 1
        self._events.append(
            ToolDiscoveryEvent(
                ToolDiscoveryEventType.SEARCH,
                len(self._events) + 1,
                query=query.strip(),
                result_tool_ids=tuple(result.tool_id for result in results),
            )
        )
        return tuple(results)

    def describe_tool(self, tool_id: str) -> dict[str, object]:
        if not isinstance(tool_id, str) or not tool_id:
            raise ToolAccessDenied("tool_id must be a non-empty string")
        try:
            descriptor = self.view.get(tool_id)
        except KeyError as exc:
            # Do not distinguish unknown-from-hidden here. The model should not
            # gain information about tools outside its authorized view.
            raise ToolAccessDenied(f"tool is not available in this authority scope: {tool_id}") from exc

        if tool_id not in self._hydrated:
            if len(self._hydrated) >= self.max_hydrated_tools:
                raise ToolSearchBudgetExceeded(
                    "tool hydration budget exhausted "
                    f"({len(self._hydrated)} >= {self.max_hydrated_tools})"
                )
            self._hydrated.add(tool_id)

        self._events.append(
            ToolDiscoveryEvent(
                ToolDiscoveryEventType.DESCRIBE,
                len(self._events) + 1,
                tool_id=tool_id,
            )
        )
        return {
            **descriptor.canonical_dict(),
            "ref": descriptor.ref,
            "content_hash": descriptor.content_hash,
            "catalog_hash": self.view.catalog_hash,
            "authority_hash": self.view.authority_hash,
        }
