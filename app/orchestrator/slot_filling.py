from __future__ import annotations

from dataclasses import dataclass, field

QUESTION_CODE_BY_ACTION = {
    "COLLECT_EVENT_TYPE": "RESP-EVENT-DATA-013",
    "COLLECT_GUEST_COUNT": "RESP-EVENT-DATA-004",
    "COLLECT_EVENT_DATE": "RESP-EVENT-DATA-001",
    "COLLECT_CUSTOMER_NAME": "RESP-CUSTOMER-001",
    "COLLECT_BUDGET": "RESP-BUDGET-001",
    "COLLECT_SERVICES": "RESP-EVENT-DATA-006",
}

QUESTION_ORDER = (
    "COLLECT_EVENT_TYPE",
    "COLLECT_GUEST_COUNT",
    "COLLECT_EVENT_DATE",
    "COLLECT_CUSTOMER_NAME",
    "COLLECT_BUDGET",
    "COLLECT_SERVICES",
)


@dataclass(frozen=True)
class CaptureProgress:
    event_type: str | None = None
    guest_count: int | None = None
    guest_count_min: int | None = None
    guest_count_max: int | None = None
    date_resolved: bool = False
    full_name: str | None = None
    full_name_needs_confirmation: bool = False
    budget_data_status: str = "NOT_ASKED"
    services_requested: bool = False
    pending_fields: list[str] = field(default_factory=list)

    @property
    def has_guest_count(self) -> bool:
        return self.guest_count is not None or (
            self.guest_count_min is not None and self.guest_count_max is not None
        )


def select_next_question(progress: CaptureProgress) -> str | None:
    if not progress.event_type:
        return "COLLECT_EVENT_TYPE"
    if not progress.has_guest_count:
        return "COLLECT_GUEST_COUNT"
    if not progress.date_resolved:
        return "COLLECT_EVENT_DATE"
    if not progress.full_name or progress.full_name_needs_confirmation:
        return "COLLECT_CUSTOMER_NAME"
    if progress.budget_data_status in {"NOT_ASKED", "ASKED_PENDING"}:
        return "COLLECT_BUDGET"
    if not progress.services_requested:
        return "COLLECT_SERVICES"
    return None


def pending_fields_for(progress: CaptureProgress) -> list[str]:
    pending: list[str] = []
    if not progress.event_type:
        pending.append("event_type")
    if not progress.has_guest_count:
        pending.append("guest_count")
    if not progress.date_resolved:
        pending.append("event_date")
    if not progress.full_name or progress.full_name_needs_confirmation:
        pending.append("full_name")
    if progress.budget_data_status in {"NOT_ASKED", "ASKED_PENDING"}:
        pending.append("estimated_budget")
    if not progress.services_requested:
        pending.append("requested_services")
    return pending


def minimum_quote_data_complete(progress: CaptureProgress) -> bool:
    return bool(
        progress.event_type
        and progress.has_guest_count
        and progress.date_resolved
        and progress.full_name
        and not progress.full_name_needs_confirmation
    )
