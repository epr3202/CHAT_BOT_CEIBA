from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.reservation.models import Reservation

RESERVATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "PAYMENT_PENDING": frozenset({"PAYMENT_REVIEW", "EXPIRED", "CANCELLED"}),
    "PAYMENT_REVIEW": frozenset({"PAYMENT_PENDING", "RESERVED", "CANCELLED"}),
    "RESERVED": frozenset({"CANCELLED"}),
    "EXPIRED": frozenset(),
    "CANCELLED": frozenset(),
}


class InvalidReservationTransition(ValueError):
    """The requested transition is absent from the D2 matrix."""


async def transition_reservation(
    session: AsyncSession,
    reservation: Reservation,
    new_status: str,
    *,
    actor: str,
    reason: str,
    request_id: str,
) -> None:
    """Validate D2 and append its audit in the caller's transaction, without commit.

    Business guards (human payment confirmation, availability, calendar and holds)
    are applied by the caller in B1b/B2. This function only validates the matrix
    and nonempty actor/reason; it neither validates payments nor calls calendars.
    The caller owns locking and the transaction for the reservation mutation.
    """
    if not actor or not actor.strip():
        raise ValueError("El actor es obligatorio.")
    if not reason or not reason.strip():
        raise ValueError("El motivo es obligatorio.")
    old_status = reservation.status
    if new_status not in RESERVATION_TRANSITIONS.get(old_status, frozenset()):
        raise InvalidReservationTransition(
            f"No se permite cambiar la reserva de {old_status} a {new_status}."
        )
    reservation_id = str(reservation.reservation_id)
    reservation.status = new_status
    session.add(AuditEvent(
        actor=actor,
        action="RESERVATION_STATUS_CHANGED",
        entity="reservation",
        old_value={"status": old_status, "reservation_id": reservation_id},
        new_value={"status": new_status, "reservation_id": reservation_id},
        reason=reason,
        request_id=request_id,
    ))
