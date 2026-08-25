"""Project-wait state machine. No I/O — callers sleep themselves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from arbitr._constants import (
    AGENT_SELECTION_CONFIRM_POLLS,
    TERMINAL_STATUSES,
    OnActionRequired,
)
from arbitr.errors import ClientInputError
from arbitr.generated.models import ProjectResponse

WaitKind = Literal["terminal", "parked", "continue"]


@dataclass(frozen=True)
class WaitDecision:
    """One poll of projects.wait() without sleeping."""

    kind: WaitKind
    status: str | None
    agent_selection_streak: int
    project: ProjectResponse


def parse_on_action_required(value: str) -> OnActionRequired:
    """Parse ``on_action_required`` from untyped input."""
    if value == "raise" or value == "wait":
        return value
    raise ClientInputError("on_action_required must be 'raise' or 'wait'")


def decide_project_wait(
    project: ProjectResponse,
    *,
    agent_selection_streak: int,
    on_action_required: OnActionRequired,
    confirm_polls: int = AGENT_SELECTION_CONFIRM_POLLS,
) -> WaitDecision:
    """Advance wait state from one GET /v1/projects/{id} body.

    ``agent_selection`` is confirmed across ``confirm_polls`` consecutive
    observations before it counts as parked (live AI_TRANSLATION transits
    that status briefly). ``awaiting_payment`` parks on first sight.
    """
    status = project.status
    if status in TERMINAL_STATUSES:
        return WaitDecision("terminal", status, 0, project)

    streak = agent_selection_streak + 1 if status == "agent_selection" else 0
    parked = status == "awaiting_payment" or (
        status == "agent_selection" and streak >= confirm_polls
    )
    if parked and on_action_required == "raise":
        return WaitDecision("parked", status, streak, project)
    return WaitDecision("continue", status, streak, project)
