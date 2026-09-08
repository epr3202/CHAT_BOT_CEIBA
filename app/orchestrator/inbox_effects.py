"""Defer existing agenda service calls out of the inbox settlement transaction.

This adapter does not change appointment rules or their separate transactions. A replay
uses only results obtained by this acquisition; abandoned mutating calls require review.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


class DeferredAgendaCall(Exception):
    def __init__(self, method: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        super().__init__(method.__name__)
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self.name = method.__name__
        self.mutating = self.name in {
            "confirm_appointment",
            "reschedule_appointment",
            "cancel_appointment",
        }


@dataclass
class AgendaResults:
    results: list[tuple[str, Any]] = field(default_factory=list)
    position: int = 0


agenda_results: ContextVar[AgendaResults | None] = ContextVar("inbox_agenda_results", default=None)


class DeferredAgendaService:
    def __init__(self, service: Any, results: AgendaResults) -> None:
        self.service = service
        self.results = results

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.service, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            index = self.results.position
            self.results.position += 1
            if index < len(self.results.results):
                expected, result = self.results.results[index]
                if expected != name:
                    raise RuntimeError("Agenda replay changed operation order")
                return result
            raise DeferredAgendaCall(method, args, kwargs)

        return call


def defer_agenda_service(service: Any) -> Any:
    results = agenda_results.get()
    return service if results is None else DeferredAgendaService(service, results)
