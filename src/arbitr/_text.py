"""Text-translate request body and usage query construction (no I/O)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arbitr.generated.models import Requester, TextFormat, TextToTranslate, TextUsageType


def text_translate_body(
    texts: Sequence[TextToTranslate],
    *,
    format: TextFormat | str | None,
    usage_type: TextUsageType | str | None,
    requester: Requester | None,
) -> dict[str, Any]:
    """JSON body for POST /v1/text/translate.

    Locale codes are sent as given, in any case: the API checks them against
    ``GET /v1/languages``. Region-less ones such as ``ar`` can be catalogue tags.
    Omitted options are left out so the API's defaults apply.
    """
    body: dict[str, Any] = {
        "texts": [text.model_dump(mode="json", exclude_none=True) for text in texts]
    }
    if format is not None:
        body["format"] = str(format)
    if usage_type is not None:
        body["usage_type"] = str(usage_type)
    if requester is not None:
        body["requester"] = requester.model_dump(mode="json", exclude_none=True)
    return body


def usage_list_params(*, from_: str, to: str, page: int, limit: int) -> dict[str, Any]:
    """Query params for GET /v1/usage; ``from_`` is sent as ``from``."""
    return {"from": from_, "to": to, "page": page, "limit": limit}
