"""Locale-code resolution against GET /v1/languages (no I/O)."""

from __future__ import annotations

from arbitr.errors import AmbiguousLocaleCodesError, UnknownLocaleCodesError
from arbitr.generated.models import LanguageListResponse, LanguageResponse, Page


def resolve_locale_codes(codes: list[str], known: set[str]) -> list[str]:
    """Map caller locale input to canonical lowercased BCP-47 tags.

    Exact matches (any case) win. A language prefix such as ``ja`` expands
    only when it uniquely matches one known tag (``ja-jp``). Ambiguous
    prefixes (``fr`` → ``fr-fr`` and ``fr-ca``) and unknown codes error.
    """
    by_lower = {code.lower(): code for code in known}
    resolved: list[str] = []
    unknown: list[str] = []
    for code in codes:
        low = code.lower()
        if low in by_lower:
            resolved.append(by_lower[low])
            continue
        matches = sorted(
            canonical
            for canonical in known
            if canonical.lower() == low or canonical.lower().startswith(f"{low}-")
        )
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) > 1:
            raise AmbiguousLocaleCodesError(code, matches)
        else:
            unknown.append(code)
    if unknown:
        raise UnknownLocaleCodesError(unknown)
    return resolved


def filter_language_list(data: LanguageListResponse, search: str) -> LanguageListResponse:
    """Return a new list whose names or BCP-47 tags contain ``search`` (case-insensitive)."""
    query = search.lower()
    matched = [
        lang for lang in data.languages if query in lang.bcp47.lower() or query in lang.name.lower()
    ]
    return LanguageListResponse(
        languages=matched,
        page=Page(number=1, has_more=False, limit=len(matched)),
    )


def language_bcp47_set(languages: list[LanguageResponse]) -> set[str]:
    """The canonical BCP-47 tags from a language list response."""
    return {lang.bcp47 for lang in languages}
