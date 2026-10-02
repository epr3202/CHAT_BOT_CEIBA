import re
from dataclasses import dataclass


def sanitize_customer_reason(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Escribe el motivo que verá el cliente")
    if re.search(r"http|www", value, flags=re.IGNORECASE):
        raise ValueError("No incluyas enlaces en el motivo")
    return " ".join(value.split())[:200].rstrip()


@dataclass(frozen=True)
class CustomerRejectionReason:
    """Explicit human decision value; arbitrary customer text is not renderable."""

    text: str

    def __post_init__(self) -> None:
        if sanitize_customer_reason(self.text) != self.text:
            raise ValueError("El motivo visible requiere saneamiento previo")
